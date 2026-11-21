"""Compact camera-pass depth evidence; never a character/root-depth estimate."""
import hashlib
import json
import numpy as np
from storage import atomic_json,read_json

VERSION=1
MAX_EDGE=768


def signature(root):
    paths=('models/camera/model.pt','vendor/MoGe/moge/model/v2.py','worker/camera_depth.py')
    rows=[]
    for name in paths:
        path=root/name
        if not path.is_file():rows.append((name,None));continue
        stat=path.stat();rows.append((name,hashlib.sha256(path.read_bytes()).hexdigest() if stat.st_size<8*1024**2 else (stat.st_size,stat.st_mtime_ns)))
    return hashlib.sha256(json.dumps([VERSION,MAX_EDGE,'nearest-exact-pixel-centers',rows],sort_keys=True).encode()).hexdigest()


def image_signature(image):
    value=np.ascontiguousarray(image)
    return hashlib.sha256(str(value.shape).encode()+value.tobytes()).hexdigest()


def save(root,folder,image,intrinsics,depth,valid,normal=None):
    import cv2
    h,w=image.shape[:2]
    value=np.asarray(depth,dtype=np.float32).squeeze();mask=np.asarray(valid,dtype=bool).squeeze()
    if value.shape!=(h,w) or mask.shape!=value.shape:raise ValueError('MoGe returned a depth map in an unexpected image frame')
    mask=mask & np.isfinite(value) & (value>0)
    value=np.where(mask,value,0).astype(np.float32)
    factor=min(1.,MAX_EDGE/max(h,w));size=(max(1,round(w*factor)),max(1,round(h*factor)))
    if size!=(w,h):
        value=cv2.resize(value,size,interpolation=cv2.INTER_NEAREST_EXACT)
        mask=cv2.resize(mask.astype(np.uint8),size,interpolation=cv2.INTER_NEAREST_EXACT)>0
    path=folder/'camera-depth.npz';temporary=path.with_suffix('.partial')
    with temporary.open('wb') as stream:np.savez_compressed(stream,depth=value.astype(np.float32),valid=mask)
    temporary.replace(path)
    metadata=dict(version=VERSION,provider='MoGe-2',stage='reference-camera-depth',modelSignature=signature(root),imageSha256=image_signature(image),
                  imageSize=[w,h],size=list(size),intrinsics=intrinsics,units='metres-estimated',
                  mapping='depth pixel center = (original pixel center + 0.5) * size / imageSize - 0.5',
                  path=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                  limits='Learned surface depth along the reference camera. Not pelvis depth, DAZ world Z or verified physical distance.')
    atomic_json(path.with_suffix('.json'),metadata)
    if normal is not None:save_normals(root,folder,image,normal,valid,metadata)
    return metadata


def cache_identity(root,metadata,provider):
    if metadata.get('version')!=VERSION or metadata.get('provider','MoGe-2')!=provider:return False
    if provider=='MoGe-3':
        # Read-only support for depth cached by older saved interactions.
        value=metadata.get('modelSignature','')
        return isinstance(value,str) and len(value)==64 and all(c in '0123456789abcdef' for c in value)
    return provider=='MoGe-2' and metadata.get('modelSignature')==signature(root)


def load(root,folder,image=None,provider='MoGe-2'):
    name='camera-depth-moge3' if provider=='MoGe-3' else 'camera-depth'
    metadata=read_json(folder/(name+'.json'),{})
    if not cache_identity(root,metadata,provider):return None
    if image is not None and metadata.get('imageSha256')!=image_signature(image):return None
    if metadata.get('path')!=name+'.npz':return None
    path=folder/(name+'.npz')
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=metadata.get('sha256'):return None
    try:
        with np.load(path,allow_pickle=False) as packed:depth=packed['depth'].copy();valid=packed['valid'].copy()
        if depth.dtype!=np.float32 or valid.dtype!=bool or list(depth.shape[::-1])!=metadata['size'] or valid.shape!=depth.shape or max(depth.shape)>MAX_EDGE:return None
        if not np.isfinite(depth).all() or np.any(depth[valid]<=0):return None
    except (OSError,ValueError,KeyError):return None
    return metadata,depth,valid


def sample(depth,valid,xy,image_size):
    points=np.asarray(xy,dtype=float);size=np.asarray(depth.shape[::-1]);original=np.asarray(image_size)
    pixels=np.rint((points+.5)*size/original-.5).astype(int)
    inside=np.all((pixels>=0)&(pixels<size),axis=-1);values=np.full(len(points),np.nan)
    selected=pixels[inside];accepted=valid[selected[:,1],selected[:,0]]
    rows=np.flatnonzero(inside)[accepted];values[rows]=depth[pixels[rows,1],pixels[rows,0]]
    return values



def save_normals(root,folder,image,normal,valid,depth_metadata):
    import cv2
    h,w=image.shape[:2];values=np.asarray(normal,dtype=np.float32).squeeze()
    mask=np.asarray(valid,dtype=bool).squeeze()
    if values.shape!=(h,w,3) or mask.shape!=(h,w):raise ValueError('Geometry normals have an unexpected image frame')
    lengths=np.linalg.norm(values,axis=-1)
    mask=mask&np.isfinite(values).all(axis=-1)&(lengths>.5)
    values=np.where(mask[...,None],values/np.maximum(lengths[...,None],1e-6),0).astype(np.float32)
    size=tuple(depth_metadata['size'])
    if size!=(w,h):
        values=cv2.resize(values,size,interpolation=cv2.INTER_NEAREST_EXACT)
        mask=cv2.resize(mask.astype(np.uint8),size,interpolation=cv2.INTER_NEAREST_EXACT)>0
    path=folder/'camera-normal.npz';temporary=path.with_suffix('.partial')
    with temporary.open('wb') as stream:np.savez_compressed(stream,normal=values,valid=mask)
    temporary.replace(path)
    metadata=dict(depth_metadata,path=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),stage='reference-camera-normal',
                  basis='x-right,y-down,z-forward',units='unit-vector',limits='Predicted visible surface orientation; not anatomical facing or hidden joint twist.')
    atomic_json(path.with_suffix('.json'),metadata)


def load_normals(root,folder,image=None):
    name='camera-normal'
    meta=read_json(folder/(name+'.json'),{})
    if not cache_identity(root,meta,'MoGe-2'):return None
    if image is not None and meta.get('imageSha256')!=image_signature(image):return None
    path=folder/(name+'.npz')
    if meta.get('path')!=path.name or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=meta.get('sha256'):return None
    try:
        with np.load(path,allow_pickle=False) as packed:values=packed['normal'].copy();valid=packed['valid'].copy()
        if values.ndim!=3 or valid.ndim!=2 or list(values.shape[1::-1])!=meta.get('size') or values.dtype!=np.float32 or values.shape[:2]!=valid.shape or values.shape[-1]!=3 or valid.dtype!=bool or max(valid.shape)>MAX_EDGE or not np.isfinite(values).all():return None
    except (OSError,ValueError,KeyError):return None
    return meta,values,valid
