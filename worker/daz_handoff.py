"""Bounded acknowledgment wait; the short-lived DAZ launcher is not the session."""
import json, os, time
from pathlib import Path

def daz_running(executable):
    """Check the exact application path. Unknown inspection never means closed."""
    if os.name != 'nt':return None
    import ctypes
    from ctypes import wintypes
    class Entry(ctypes.Structure):
        _fields_=[('size',wintypes.DWORD),('usage',wintypes.DWORD),('pid',wintypes.DWORD),('heap',ctypes.c_size_t),('module',wintypes.DWORD),('threads',wintypes.DWORD),('parent',wintypes.DWORD),('priority',wintypes.LONG),('flags',wintypes.DWORD),('exe',wintypes.WCHAR*260)]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes=[wintypes.DWORD,wintypes.DWORD];kernel.CreateToolhelp32Snapshot.restype=wintypes.HANDLE
    for name in ('Process32FirstW','Process32NextW'):
        fn=getattr(kernel,name);fn.argtypes=[wintypes.HANDLE,ctypes.POINTER(Entry)];fn.restype=wintypes.BOOL
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)];kernel.QueryFullProcessImageNameW.restype=wintypes.BOOL
    kernel.CloseHandle.argtypes=[wintypes.HANDLE];kernel.CloseHandle.restype=wintypes.BOOL
    snapshot=kernel.CreateToolhelp32Snapshot(2,0)
    if snapshot == ctypes.c_void_p(-1).value:return None
    wanted=os.path.normcase(str(Path(executable).resolve()));uncertain=False;entry=Entry();entry.size=ctypes.sizeof(Entry)
    try:
        if not kernel.Process32FirstW(snapshot,ctypes.byref(entry)):return None
        while True:
            if entry.exe.lower()==Path(executable).name.lower():
                handle=kernel.OpenProcess(0x1000,False,entry.pid)
                if not handle:uncertain=True
                else:
                    try:
                        size=wintypes.DWORD(32768);path=ctypes.create_unicode_buffer(size.value)
                        if not kernel.QueryFullProcessImageNameW(handle,0,path,ctypes.byref(size)):uncertain=True
                        elif os.path.normcase(path.value)==wanted:return True
                    finally:kernel.CloseHandle(handle)
            if not kernel.Process32NextW(snapshot,ctypes.byref(entry)):break
        return None if uncertain else False
    finally:kernel.CloseHandle(snapshot)

PHASES={'controls':('Reading facial controls in DAZ',30),'preflight':('Checking facial controllers in DAZ',40),'outputs':('Checking affected expression channels',50),'snapshot':('Protecting body pose and identity',60),'zero':('Zeroing facial controls in DAZ',75),'verify':('Verifying the expression reset',90)}

def wait_for_ack(ack,cancel,status,job_id,executable,launch,progress,was_running=False,timeout=60):
    start=time.monotonic();deadline=start+timeout;next_check=start;seen=was_running;last_phase=None
    try:
        while time.monotonic()<deadline:
            if cancel.exists():raise InterruptedError('Expression task cancelled. Your previous PoseSnap result is preserved.')
            if ack.is_file():
                try:result=json.loads(ack.read_text(encoding='utf-8-sig'))
                except (OSError,ValueError):result=None
                if result is not None:
                    if not isinstance(result,dict) or result.get('version')!=1 or result.get('jobId')!=job_id:raise ValueError('DAZ acknowledgment does not match this facial task')
                    if not result.get('success'):raise ValueError(result.get('message','DAZ did not accept the expression'))
                    return result
            if status.is_file():
                try:state=json.loads(status.read_text(encoding='utf-8-sig'))
                except (OSError,ValueError):state={}
                if isinstance(state,dict) and state.get('version')==1 and state.get('jobId')==job_id and state.get('phase') in PHASES and state['phase']!=last_phase:
                    last_phase=state['phase'];progress(*PHASES[last_phase])
            now=time.monotonic()
            if now>=next_check:
                alive=daz_running(executable);seen=seen or alive is True;next_check=now+1
                if alive is False and (seen or now-start>=5 and launch.poll() is not None):raise ValueError('DAZ Studio closed before confirming this task. Your PoseSnap expression is kept. Reopen DAZ and check the figure before retrying.')
            time.sleep(.2)
        raise ValueError('DAZ did not confirm this task within 60 seconds. PoseSnap stopped waiting. Check blocking dialogs and the selected figure in DAZ before retrying.')
    except BaseException:
        # A queued script must not apply later after the UI has reported failure.
        cancel.write_text('cancelled or expired',encoding='ascii')
        raise
