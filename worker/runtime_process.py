"""Private GPU discovery and owned Windows helper lifetime management."""
import os
import subprocess


def devices():
    try:
        result = subprocess.run(['nvidia-smi', '--query-gpu=index,uuid,name,memory.free,driver_version', '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=8, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        return [dict(index=int(a[0]), id=a[1].strip(), name=a[2].strip(), freeMb=int(a[3]), driver=a[4].strip()) for line in result.stdout.splitlines() if len(a := line.split(',')) == 5]
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []


def process_job(child):
    """Closing the parent worker also closes its private helper processes."""
    if os.name != 'nt': return None
    import ctypes
    from ctypes import wintypes as w
    class Basic(ctypes.Structure):
        _fields_ = [('processTime', ctypes.c_int64), ('jobTime', ctypes.c_int64), ('flags', w.DWORD), ('minWorking', ctypes.c_size_t), ('maxWorking', ctypes.c_size_t), ('processLimit', w.DWORD), ('affinity', ctypes.c_size_t), ('priority', ctypes.c_int), ('scheduling', ctypes.c_int)]
    class IO(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in ('readOps', 'writeOps', 'otherOps', 'readBytes', 'writeBytes', 'otherBytes')]
    class Extended(ctypes.Structure):
        _fields_ = [('basic', Basic), ('io', IO), ('processMemory', ctypes.c_size_t), ('jobMemory', ctypes.c_size_t), ('peakProcess', ctypes.c_size_t), ('peakJob', ctypes.c_size_t)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]; kernel.CreateJobObjectW.restype = w.HANDLE
    kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    handle = kernel.CreateJobObjectW(None, None); limits = Extended(); limits.basic.flags = 0x2000
    if not handle or not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)) or not kernel.AssignProcessToJobObject(handle, int(child._handle)):
        if handle: kernel.CloseHandle(handle)
        child.kill(); child.wait()
        raise ValueError('Could not contain the local helper for safe cancellation.')
    return kernel, handle


def working_memory(child=None):
    """Actual Windows process counters, including the observed working-set peak."""
    import ctypes
    from ctypes import wintypes as w
    class Counters(ctypes.Structure):
        _fields_=[('cb',w.DWORD),('faults',w.DWORD)]+[(k,ctypes.c_size_t) for k in
            ('peakWorkingSet','workingSet','peakPaged','paged','peakNonpaged','nonpaged','pagefile','peakPagefile')]
    counters=Counters();counters.cb=ctypes.sizeof(counters)
    kernel=ctypes.WinDLL('kernel32');kernel.GetCurrentProcess.restype=w.HANDLE
    api=ctypes.WinDLL('psapi').GetProcessMemoryInfo;api.argtypes=[w.HANDLE,ctypes.c_void_p,w.DWORD]
    handle=int(child._handle) if child else kernel.GetCurrentProcess()
    if not api(handle,ctypes.byref(counters),counters.cb):return dict(unavailable=True)
    return dict(peakWorkingSetBytes=counters.peakWorkingSet,workingSetBytes=counters.workingSet,peakPagefileBytes=counters.peakPagefile)
