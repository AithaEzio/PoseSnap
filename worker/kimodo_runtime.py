"""Optional Q8 CPU encoder + official CUDA motion core, in owned private processes."""
import atexit
from collections import OrderedDict
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import time
import uuid

from storage import read_json

VERSION = 1
MODEL = 'Kimodo-SOMA-RP-v1.2'
CACHE_BYTES = 16*1024**2
IDLE_SECONDS = 120
_verified = set()


def components():
    return read_json(Path(__file__).with_name('kimodo-components.json'), {'components': []})['components']


def installed(root, component):
    return bool(component.get('files')) and all((root/f['path']).is_file() and (root/f['path']).stat().st_size == f['size'] for f in component['files'])


def verify(root, progress):
    catalogue = components()
    if {c['id'] for c in catalogue} != {'kimodo-encoder', 'kimodo-motion', 'kimodo-runtime'}:
        raise ValueError('The optional Kimodo catalogue is unavailable. Repair the app sources.')
    for component in catalogue:
        if not installed(root, component): raise ValueError('Install or import '+component['label']+' in Engine settings.')
        for row in component['files']:
            path = root/row['path']; stat = path.stat()
            stamp = (str(path.resolve()), stat.st_size, stat.st_mtime_ns, row['sha256'])
            if stamp in _verified: continue
            h = hashlib.sha256()
            with path.open('rb') as stream:
                while block := stream.read(8*1024**2):
                    progress('Verifying '+component['label'], -1); h.update(block)
            if h.hexdigest() != row['sha256']: raise ValueError(component['label']+' failed its checksum. Repair or import it in Settings.')
            _verified.add(stamp)


def pack_signature():
    code = {name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in ('kimodo_runtime.py', 'kimodo_motion.py', 'kimodo_generation.py', 'soma.py', 'body_contacts.py', 'hand_design.py', 'textpose.py', 'textconstraints.py', 'instructions.py', 'textsolve.py', 'contact_geometry.py', 'measurements.py', 'pose_design.py', 'runtime_process.py', 'body_profiles.py', 'text_settings.py')}
    return hashlib.sha256(json.dumps(dict(version=VERSION, components=components(), code=code), sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def eligible(payload):
    return payload.get('output','pose')=='pose' and isinstance(payload.get('actors'),list) and 1<=len(payload['actors'])<=2


def provider(payload):
    if payload.get('bodyGenerator','kimodo')!='kimodo':raise ValueError('Text to Pose uses Kimodo for body generation.')
    return 'kimodo'


def available_memory():
    if os.name != 'nt': return None
    import ctypes
    class Memory(ctypes.Structure):
        _fields_ = [('length', ctypes.c_uint32), ('load', ctypes.c_uint32), *[(name, ctypes.c_uint64) for name in ('total', 'available', 'pageTotal', 'pageAvailable', 'virtualTotal', 'virtualAvailable', 'extended')]]
    state = Memory(); state.length = ctypes.sizeof(state)
    return state.available if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state)) else None


def pipe_bytes(child, amount, deadline, tick):
    """Cancelable reads with a deadline; no thread survives unloading a helper."""
    output = bytearray()
    while len(output) < amount:
        tick()
        if time.monotonic() > deadline: raise ValueError('Kimodo timed out. The accepted result is kept. Unload it and retry.')
        if os.name == 'nt':
            import ctypes, msvcrt
            from ctypes import wintypes as w
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.PeekNamedPipe.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD, ctypes.c_void_p, ctypes.POINTER(w.DWORD), ctypes.c_void_p]
            available = w.DWORD()
            ok = kernel.PeekNamedPipe(msvcrt.get_osfhandle(child.stdout.fileno()), None, 0, None, ctypes.byref(available), None)
            count = min(available.value, amount-len(output)) if ok else 0
        else:
            import select
            count = amount-len(output) if select.select([child.stdout], [], [], 0)[0] else 0
        if count:
            block = os.read(child.stdout.fileno(), count)
            if not block: raise ValueError('Kimodo closed its response pipe.')
            output.extend(block)
        elif child.poll() is not None: raise ValueError('Kimodo stopped. See logs/kimodo.log; the accepted result is kept.')
        else: time.sleep(.025)
    return bytes(output)


class Runtime:
    def __init__(self, root):
        self.root = Path(root); self.encoder = None; self.motion = None
        self.jobs = []; self.logs = []; self.cache = OrderedDict(); self.error = ''
        self.last_used = 0.; self.signature = None; self.timings = {}
        atexit.register(self.release)

    def release(self):
        for child in (self.motion, self.encoder):
            if child:
                if child.poll() is None:
                    child.terminate()
                    try: child.wait(timeout=3)
                    except subprocess.TimeoutExpired: child.kill(); child.wait()
                for stream in (child.stdin, child.stdout):
                    if stream: stream.close()
        self.motion = self.encoder = None
        for kernel, handle in self.jobs: kernel.CloseHandle(handle)
        self.jobs.clear()
        for log in self.logs: log.close()
        self.logs.clear(); self.signature = None
        self.cache.clear()

    def idle(self):
        free = available_memory()
        if self.encoder and (time.monotonic()-self.last_used >= IDLE_SECONDS or free is not None and free < 2*1024**3): self.release()

    def status(self):
        self.idle()
        if any(child and child.poll() is not None for child in (self.encoder, self.motion)):
            self.release(); self.error = 'A Kimodo helper stopped. Load it again to retry.'
        if self.signature and self.signature != pack_signature(): self.release(); self.error = 'Kimodo files changed. Load the matching pack again.'
        found = {c['id']: installed(self.root, c) for c in components()}
        present = len(found) == 3 and all(found.values())
        ready = bool(self.encoder and self.motion)
        return dict(version=VERSION, ready=ready, phase='ready' if ready else 'attention' if self.error else 'unloaded' if present else 'missing', error=self.error,
                    encoderReady=bool(self.encoder), motionReady=bool(self.motion), installed=found, experimental=True, idleSeconds=IDLE_SECONDS, cacheBytes=sum(len(x) for x in self.cache.values()), timings=self.timings)

    def spawn(self, args, env):
        from runtime_process import process_job
        path = self.root/'logs/kimodo.log'; path.parent.mkdir(parents=True, exist_ok=True)
        log = path.open('ab'); self.logs.append(log)
        child = subprocess.Popen(args, cwd=self.root, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, bufsize=0, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        job = process_job(child)
        if job: self.jobs.append(job)
        return child

    def message(self, request, progress, timeout=180):
        self.motion.stdin.write((json.dumps(request, allow_nan=False)+'\n').encode()); self.motion.stdin.flush()
        deadline = time.monotonic()+timeout
        current = ['Kimodo · '+request.get('label', 'Preparing motion'), -1]
        last_tick = [0.]
        def tick():
            if time.monotonic()-last_tick[0] >= .15:
                progress(*current); last_tick[0] = time.monotonic()
        while True:
            line = bytearray()
            while not line.endswith(b'\n'):
                line.extend(pipe_bytes(self.motion, 1, deadline, tick))
                if len(line) > 1024**2: raise ValueError('Kimodo response exceeds the protocol limit.')
            event = json.loads(line)
            if event.get('type') == 'progress':
                current[:] = [event['label'], event['percent']]; progress(*current)
            elif event.get('type') == 'result': return event['result']
            elif event.get('type') == 'error': raise ValueError(event['message'])
            else: raise ValueError('Unknown Kimodo response.')

    def load(self, progress):
        if self.status()['ready']: self.last_used = time.monotonic(); return self.status()
        self.release(); self.error = ''; start = time.monotonic()
        try:
            verify(self.root, progress)
            free = available_memory()
            if free is not None and free < 10*1024**3: raise ValueError('Kimodo needs about 10 GiB free system RAM to load its CPU Q8 encoder. Close other apps, unload unused engines, then retry.')
            from runtime_process import devices
            gpu = next((g for g in devices() if g['freeMb'] >= 4096), None)
            if not gpu: raise ValueError('Kimodo needs an NVIDIA GPU with at least 4 GiB free VRAM. Its motion generator does not fall back to CPU.')
            env = dict(os.environ, KIMODO_BACKEND='cpu', KIMODO_TEXT_LAYER_CHUNK='32', KIMODO_TEXT_RESIDENT_LIMIT_MIB='10000', KIMODO_THREADS=str(min(16, max(1, (os.cpu_count() or 4)//2))), CUDA_VISIBLE_DEVICES=gpu['id'], HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHONNOUSERSITE='1', OMP_NUM_THREADS='4', MKL_NUM_THREADS='4')
            env['PATH'] = os.pathsep.join((str(self.root/'runtime/kimodo/encoder'), str(self.root/'runtime/python'), str(Path(os.environ.get('SystemRoot', 'C:/Windows'))/'System32')))
            progress('Loading Kimodo CPU Q8 encoder', -1)
            self.encoder = self.spawn([str(self.root/'runtime/kimodo/encoder/posesnap-kimodo-encoder.exe'), str(self.root/'models/kimodo/encoder/Llama-3-Kimodo-Q8_0.gguf')], env)
            if pipe_bytes(self.encoder, 4, time.monotonic()+150, lambda:progress('Loading Kimodo CPU Q8 encoder', -1)) != b'KMD1': raise ValueError('Unsupported Kimodo encoder protocol.')
            self.motion = self.spawn([str(self.root/'runtime/python/python.exe'), '-I', '-B', '-u', str(self.root/'worker/kimodo_motion.py'), '--root', str(self.root)], env)
            self.message(dict(method='load', label='Loading CUDA motion generator'), progress)
            self.last_used = time.monotonic(); self.signature = pack_signature()
            self.timings['loadSeconds'] = self.last_used-start
            return self.status()
        except BaseException as error:
            self.release(); self.error = '' if isinstance(error, InterruptedError) else str(error); raise

    def unload(self):
        self.release(); self.error = ''; return self.status()

    def encode(self, prompt, progress):
        import numpy as np
        # Match the official sanitizer before caching and before encoding. The
        # pinned native tokenizer adds BOS; no chat template is appropriate.
        import importlib.util
        spec = importlib.util.spec_from_file_location('kimodo_sanitize', self.root/'runtime/kimodo/core/kimodo/sanitize.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        prompt = module.sanitize_text(prompt)
        if not prompt or len(prompt.encode()) > 8192: raise ValueError('Kimodo needs a shorter body description.')
        key = hashlib.sha256((pack_signature()+'\0sanitize-v1\0'+prompt).encode()).hexdigest()
        if key in self.cache:
            value = self.cache.pop(key); self.cache[key] = value
            return prompt, value, True
        start = time.monotonic(); data = prompt.encode()
        self.encoder.stdin.write(struct.pack('<I', len(data))+data); self.encoder.stdin.flush()
        tick = lambda: progress('Encoding body direction on CPU', -1)
        deadline = time.monotonic()+150
        size, = struct.unpack('<I', pipe_bytes(self.encoder, 4, deadline, tick))
        if size:
            if size > 8192: raise ValueError('Invalid Kimodo encoder error packet.')
            raise ValueError(pipe_bytes(self.encoder, size, deadline, tick).decode('utf-8', errors='replace'))
        value = pipe_bytes(self.encoder, 4096*4, deadline, tick)
        if not np.isfinite(np.frombuffer(value, dtype='<f4')).all(): raise ValueError('Invalid Kimodo embedding.')
        self.cache[key] = value
        while sum(len(v) for v in self.cache.values()) > CACHE_BYTES: self.cache.popitem(last=False)
        self.timings['encodeSeconds'] = time.monotonic()-start
        return prompt, value, False

    def clips(self, prompt, seeds, progress):
        import base64
        self.load(progress)
        try:
            processed, embedding, cached = self.encode(prompt, progress)
            folder = self.root/'temp/kimodo'/uuid.uuid4().hex
            folder.mkdir(parents=True)
            result = self.message(dict(method='generate', prompt=processed, embedding=base64.b64encode(embedding).decode(), seeds=seeds, output=str(folder), label='Generating body choices'), progress)
            self.last_used = time.monotonic()
            self.timings.update(result['timings'], embeddingCacheHit=cached)
            return result
        except BaseException as error:
            self.release(); self.error = '' if isinstance(error, InterruptedError) else str(error); raise
