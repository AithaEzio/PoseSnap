"""Explicit per-reference depth calibration; never changes accepted pose files."""
import copy
import math
import numpy as np
from pathlib import Path
from storage import read_json,atomic_json,image_dir,current_reference
VERSION = 2
PROJECTIONS = ('perspective', 'orthographic')


def finite(value, shape, label):
    try:
        result = np.asarray(value, dtype=float)
    except (ValueError, TypeError) as error:
        raise ValueError('Invalid '+label) from error
    if result.shape != shape or not np.isfinite(result).all():
        raise ValueError('Invalid '+label)
    return result


def validate(camera, image_size=None):
    if not isinstance(camera, dict) or camera.get('version') != VERSION or camera.get('projection') not in PROJECTIONS:
        raise ValueError('Choose a version 2 perspective or orthographic camera.')
    size = finite(camera.get('imageSize'), (2,), 'camera image size')
    if np.any(size < 2) or np.any(size != np.floor(size)) or size.prod() > 40_000_000:
        raise ValueError('Camera image size is outside the supported image limits.')
    if image_size is not None and not np.array_equal(size, image_size):
        raise ValueError('Calibration dimensions do not match this image. Scale its calibration explicitly first.')
    intrinsic = finite(camera.get('intrinsics'), (3, 3), 'camera intrinsics')
    if min(intrinsic[0, 0], intrinsic[1, 1]) <= 0 or not np.allclose(intrinsic[2], [0, 0, 1], atol=1e-9) or abs(intrinsic[0, 1])+abs(intrinsic[1, 0]) > 1e-9:
        raise ValueError('Only finite, zero-skew camera intrinsics are supported.')
    transform = finite(camera.get('worldToCamera'), (4, 4), 'camera transform')
    rotation = transform[:3, :3]
    if not np.allclose(transform[3], [0, 0, 0, 1], atol=1e-9) or not np.allclose(rotation @ rotation.T, np.eye(3), atol=1e-6) or not math.isclose(np.linalg.det(rotation), 1., abs_tol=1e-6):
        raise ValueError('Camera orientation must be a proper rotation, without mirroring or scale.')
    if np.any(finite(camera.get('distortion', [0]*5), (5,), 'lens distortion')):
        raise ValueError('Undistort this image before importing calibration with lens distortion.')
    if type(camera.get('locked', False)) is not bool:
        raise ValueError('Invalid camera lock.')
    if type(camera.get('metricScale', False)) is not bool:
        raise ValueError('Metric scale needs an explicit calibration flag.')
    return copy.deepcopy(camera)

def settings(root,payload):
    folder=image_dir(root,payload['imageId']);meta=read_json(folder/'image.json',{})
    if meta.get('inputKind') not in ('relative-depth','metric-depth') or not current_reference(meta):
        raise ValueError('Open a depth reference to edit its calibration.')
    old=meta.get('referenceDepth',{})
    if not any(k in payload for k in ('scaleCm','encoding','calibrationPath')):return dict(kind=meta['inputKind'],**old)
    value=dict(old)
    if 'scaleCm' in payload:
        raw=payload['scaleCm']
        if isinstance(raw,bool) or not isinstance(raw,(float,int)) or not math.isfinite(raw) or not 0<raw<=1000:raise ValueError('Enter the known positive centimetres per depth value.')
        value['scaleCm']=raw
    if 'encoding' in payload:
        if payload['encoding'] not in ('camera-z','ray-distance'):raise ValueError('Choose camera-Z or distance along the camera ray.')
        value['encoding']=payload['encoding']
    if payload.get('calibrationPath'):
        path=Path(payload['calibrationPath'])
        if not path.is_file() or path.stat().st_size>1024**2:raise ValueError('Choose a camera calibration JSON file smaller than 1 MB.')
        camera=read_json(path)
        if isinstance(camera,dict) and 'camera' in camera:camera=camera['camera']
        camera=validate(camera,[meta['width'],meta['height']])
        if not camera.get('metricScale') or camera.get('provenance')!='calibrated':raise ValueError('Metric depth requires calibrated camera geometry with known physical scale.')
        value['camera']=camera
    if value.get('encoding') == 'ray-distance' and value.get('camera', {}).get('projection') == 'orthographic':
        raise ValueError('Ray-distance depth requires a calibrated perspective camera. Use camera Z for orthographic depth.')
    value['version']=1;meta['referenceDepth']=value
    atomic_json(folder/'image.json',meta)
    return dict(kind=meta['inputKind'],**value)

def calibrated(meta):
    value=meta.get('referenceDepth',{})
    if not value.get('camera') or not value.get('scaleCm') or value.get('encoding') not in ('camera-z','ray-distance'):
        raise ValueError('Metric depth needs units, depth encoding and camera calibration. Open Depth settings below the reference before extracting.')
    camera = validate(value['camera'], [meta['width'], meta['height']])
    validate_view_encoding(meta['inputKind'], value['encoding'], value['scaleCm'], camera)
    return dict(value, camera=camera)


def validate_view_encoding(kind, convention, scale, camera):
    """Keep the declaration separate from any depth used in fitting."""
    if convention not in ('unknown', 'white-near', 'white-far', 'camera-z', 'ray-distance'):
        raise ValueError('Unknown depth encoding.')
    if scale is not None and (type(scale) not in (int, float) or not math.isfinite(scale) or not 0 < scale <= 1000):
        raise ValueError('Depth scale must be positive centimetres per source value.')
    if convention in ('camera-z', 'ray-distance'):
        if kind != 'metric-depth' or scale is None or camera.get('metricScale') is not True or camera.get('provenance') != 'calibrated':
            raise ValueError('Metric depth needs source units and a calibrated camera.')
        if convention == 'ray-distance' and camera.get('projection') != 'perspective':
            raise ValueError('Ray-distance depth requires a calibrated perspective camera. Use camera Z for orthographic depth.')
