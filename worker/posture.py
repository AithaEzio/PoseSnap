"""Immutable posture anchors and bounded, camera-relative side preferences.

The reference camera has no measured gravity. Y is the retained workspace
vertical, Z is camera depth; these preferences are intent, not new evidence.
"""
import copy
import re
import numpy as np
from scipy.spatial.transform import Rotation
from measurements import canonical, target_points, stamp
from retarget import fk
from studio import semantics
from storage import atomic_json, read_json, bind_people

POLICY_VERSION=1
CORE=('hip','pelvis','spine1','spine2','spine3','spine4')

def pose_key(pose):
    values=[pose['personId'],pose['rigId'],pose['rotations'],pose['translation'],pose.get('rootRotation',[0,0,0]),pose.get('referenceCamera'),pose.get('pins',{})]
    if pose.get('cropPolicy',{}).get('enabled'):values.append(pose['cropPolicy'])
    return stamp(values)

def context_key(poses):
    return stamp([pose_key(p) for p in poses])

def baseline_signature(sources,poses):
    from refinement import source_signature
    keys=[(s['personId'],source_signature(s),p['rigId'],stamp(p['rig'])) for s,p in zip(sources,poses)]
    # Keep legacy signatures readable; a new target-fitting policy gets a fresh
    # immutable anchor rather than silently reusing the regressed first fit.
    if any(p.get('targetFitVersion') for p in poses):keys.append([p.get('targetFitVersion') for p in poses])
    if any(p.get('cropPolicy',{}).get('enabled') for p in poses):keys.append([p.get('cropPolicy') for p in poses])
    return stamp(keys)

def save_baseline(folder,sources,poses,kind='extraction'):
    """Never replace a baseline for the same source, rig and participant set."""
    ident=baseline_signature(sources,poses)[:24];path=folder/'posture-baselines'/f'{ident}.json'
    saved=read_json(path)
    if saved is None:
        clean=copy.deepcopy(poses)
        for p in clean:p.pop('postureBaseline',None)
        saved=dict(version=1,id=ident,signature=baseline_signature(sources,poses),kind=kind,poses=clean)
        atomic_json(path,bind_people(saved,sources))
    for p in poses:p['postureBaseline']=dict(version=1,id=ident,kind=saved['kind'])
    return saved

def load_baselines(folder,sources,poses):
    """Legacy poses receive an honestly labelled current-pose anchor."""
    missing=[p for p in poses if not p.get('postureBaseline')]
    if missing:persist_baseline(folder,sources,poses,'legacy-current')
    result=[]
    from refinement import source_signature
    for source,pose in zip(sources,poses):
        ident=pose['postureBaseline'].get('id','')
        if not re.fullmatch(r'[a-f0-9]{24}',ident):raise ValueError('Invalid posture baseline. Reopen the current extraction.')
        saved=read_json(folder/'posture-baselines'/f'{ident}.json')
        if not saved or saved.get('version')!=1:raise ValueError('The posture baseline is missing. Reopen or extract this pose again.')
        # The baseline may belong to a larger interaction; validate its source
        # signatures individually, without requiring the current group ordering.
        anchor=next((p for p in saved['poses'] if p['personId']==pose['personId'] and p['rigId']==pose['rigId']),None)
        original=read_json(folder/'posture-baselines'/f'{ident}.sources.json',{})
        if anchor is None or stamp(anchor['rig'])!=stamp(pose['rig']) or original.get(str(source['personId']))!=source_signature(source):
            raise ValueError('The extraction or rig changed. Extract again before refining this pose.')
        result.append(copy.deepcopy(anchor))
    return result

def persist_baseline(folder,sources,poses,kind='extraction'):
    from refinement import source_signature
    saved=save_baseline(folder,sources,poses,kind)
    path=folder/'posture-baselines'/f"{saved['id']}.sources.json"
    if not path.exists():atomic_json(path,{str(s['personId']):source_signature(s) for s in sources})
    return poses

def guidance_options(items,poses):
    ids={p['personId'] for p in poses};out={}
    if not isinstance(items,list) or len(items)>4:raise ValueError('Choose side guidance for each participant once.')
    for item in items:
        ident=item.get('personId');mode=item.get('preset','keep');strength=item.get('strength',.35)
        if ident not in ids or ident in out or mode not in ('keep','upright','forward','backward') or not isinstance(strength,(int,float)) or not np.isfinite(strength) or not .1<=strength<=1:
            raise ValueError('Invalid side-profile preference. Choose a preset and strength between 10% and 100%.')
        out[ident]=dict(personId=ident,preset=mode,strength=float(strength))
    return out

def core_frame(pose,frames=None):
    channels=dict(pose['rotations']);root=next(n['id'] for n in pose['rig']['nodes'] if not n['parent']);channels[root]=pose.get('rootRotation',[0,0,0])
    world,positions=frames if frames is not None else fk(pose['rig'],channels,pose['translation']);mapping=semantics(pose['rig'])
    # Collar motion is an image-fitting observation, not torso lean. Measure
    # posture only from the protected core; shrugging must not reject alignment.
    hip=positions[mapping['hip']];chest=positions[next(mapping[k] for k in ('spine4','spine3','spine2','spine1') if k in mapping)]
    axis=chest-hip;height=max(100.,np.ptp(np.asarray([n['center'] for n in pose['rig']['nodes']])[:,1]))
    return dict(rotations={key:world[mapping[key]] for key in CORE if key in mapping},depth={key:float(positions[mapping[key]][2]-hip[2]) for key in CORE if key in mapping},tilt=float(np.degrees(np.arctan2(axis[2],axis[1]))),height=height,hip=hip)

def drift(pose,anchor):
    a,b=core_frame(pose),core_frame(anchor)
    rotation=max((float(np.degrees(Rotation.from_matrix(a['rotations'][k]@v.T).magnitude())) for k,v in b['rotations'].items() if k in a['rotations']),default=0.)
    depth=max((abs(a['depth'][k]-v) for k,v in b['depth'].items() if k in a['depth']),default=0.)
    root=np.asarray(pose.get('rootRotation',[0,0,0]))-anchor.get('rootRotation',[0,0,0])
    return dict(coreRotationDegrees=rotation,coreDepthCm=depth,rootPitchDegrees=float(root[0]),rootRollDegrees=float(root[2]),torsoTiltDegrees=a['tilt'])

def infer_support(source,pose,warm=False):
    """Use height *before* floor fitting. Missing evidence never means grounded."""
    measured=canonical(source);keypoints=np.asarray(source.get('keypoints3d',[]));feet={}
    if keypoints.ndim==2 and len(keypoints)>20 and np.isfinite(keypoints).all():
        feet={s:keypoints[indices,1] for s,indices in [('l',[15,16,17]),('r',[18,19,20])]}
    target,_=target_points(pose);height=core_frame(pose)['height'];result={}
    both_above=warm and all(min((target[s+'_'+k][1] for k in ('heel','bigtoe','smalltoe') if s+'_'+k in target),default=0)>height*.06 for s in ('l','r'))
    for side in ('l','r'):
        known={p['name']:p for p in measured if p['region']==side+'_foot' and p.get('known',True)}
        heel=known.get(side+'_heel');toe=known.get(side+'_bigtoe')
        if both_above:state='air';reason='Both soles remain above the retained workspace floor.'
        elif feet and min(feet[side])-min(feet['r' if side=='l' else 'l'])>max(.10,height*.0012):state='air';reason='Foot is clearly lifted above the other foot in the original 3D estimate.'
        elif not feet or not heel or not toe:state='unknown';reason='Ground contact is not reliably observed; accepted height is preserved.'
        else:
            raised_heel=feet[side][2]>feet[side][0]+.035 and heel['xy'][1]<toe['xy'][1]-max(8.,source['imageSize'][1]*.015)
            raised_toe=feet[side][0]>feet[side][2]+.035 and toe['xy'][1]<heel['xy'][1]-max(8.,source['imageSize'][1]*.015)
            state='toe' if raised_heel else 'heel' if raised_toe else 'flat';reason='Original heel/toe geometry and visible foot measurements.'
        result[side]=dict(state=state,reason=reason)
    return result
