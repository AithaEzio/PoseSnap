"""Derived-source signatures, separate from accepted pose/history records."""
import hashlib
import json
import ast
from functools import lru_cache

SOURCE_FILES = ('worker/inference.py', 'worker/extraction.py', 'worker/evidence.py',
                'worker/instances.py', 'worker/segmentation.py', 'worker/cache_provenance.py',
                'worker/camera_depth.py', 'worker/body_uncertainty.py', 'worker/diagnostic-components.json',
                'vendor/sam-3d-body/sam_3d_body/models/meta_arch/sam3d_body.py',
                'vendor/sam-3d-body/sam_3d_body/sam_3d_body_estimator.py')
MODEL_FILES = ('models/body/model.ckpt', 'models/body/assets/mhr_model.pt',
               'models/body/model_config.yaml', 'models/camera/model.pt',
               'models/segmentation/sam2.1_hiera_tiny.pt',
               'vendor/sam2/sam2/configs/sam2.1/sam2.1_hiera_t.yaml',
               'models/diagnostics/clue/sam3dbody_clue.safetensors')


@lru_cache(maxsize=256)
def content(path, size, modified):
    with open(path, 'rb') as stream:return hashlib.sha256(stream.read()).hexdigest()


def stage_signature(root,files):
    """Bind a derived cache to only the code, preprocessing and models it uses."""
    values=[]
    for relative in files:
        path=root/relative
        if not path.is_file():values.append((relative,None));continue
        stat=path.stat()
        value=content(str(path),stat.st_size,stat.st_mtime_ns) if stat.st_size<8*1024**2 else (stat.st_size,stat.st_mtime_ns)
        values.append((relative,value))
    return hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()[:24]


@lru_cache(maxsize=64)
def function_content(path,size,modified,names):
    """Fingerprint source routines and their local helpers, excluding target code."""
    with open(path,encoding='utf-8') as stream:tree=ast.parse(stream.read())
    functions={n.name:n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
    needed=set(names);pending=list(names)
    while pending:
        name=pending.pop()
        if name not in functions:raise ValueError('Source cache dependency is missing: '+name)
        for node in ast.walk(functions[name]):
            if isinstance(node,ast.Name) and node.id in functions and node.id not in needed:needed.add(node.id);pending.append(node.id)
    selected=[n for n in tree.body if not (isinstance(n,ast.Expr) and isinstance(n.value,ast.Constant) and isinstance(n.value.value,str)) and (not isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) or n.name in needed)]
    return hashlib.sha256(ast.dump(ast.Module(body=selected,type_ignores=[]),include_attributes=False).encode()).hexdigest()


def source_functions(root,selectors):
    values=[]
    for relative,names in selectors:
        path=root/relative;stat=path.stat() if path.is_file() else None
        values.append((relative,function_content(str(path),stat.st_size,stat.st_mtime_ns,tuple(names)) if stat else None))
    return values


def provenance(root, extra=()):
    from body_uncertainty import enabled
    values = [('clueEnabled',enabled(root))]
    vendor=root/'vendor/sam-3d-body/sam_3d_body'
    vendor_files=tuple(p.relative_to(root).as_posix() for p in sorted(vendor.rglob('*.py'))) if vendor.is_dir() else ()
    plugin=root/'worker/sam3dbody_clue'
    plugin_files=tuple(p.relative_to(root).as_posix() for p in sorted(plugin.rglob('*.py'))) if plugin.is_dir() else ()
    for relative in dict.fromkeys((*SOURCE_FILES, *MODEL_FILES, *extra,*vendor_files,*plugin_files)):
        path = root/relative
        if not path.is_file():
            values.append((relative, None))
            continue
        stat = path.stat()
        # The component verifier checks large weights against pinned hashes.
        # Track their identity/stamps here without re-reading GB on each edit.
        value = content(str(path), stat.st_size, stat.st_mtime_ns) if stat.st_size < 8*1024**2 else (stat.st_size, stat.st_mtime_ns)
        values.append((relative, value))
    lock = root/'assets.lock.json'
    if lock.is_file():
        pinned = json.loads(lock.read_text(encoding='utf-8')).get('files', {})
        values.append(('modelPins', {p:pinned.get(p) for p in MODEL_FILES}))
    return hashlib.sha256(json.dumps([2, values], sort_keys=True).encode()).hexdigest()[:24]
