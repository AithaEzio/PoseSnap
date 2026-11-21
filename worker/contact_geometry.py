"""One immutable proxy contract for fitting, final checks and reported contacts."""
import re
import numpy as np
from measurements import target_points
from studio import semantics
from interaction import segment_distance

VERSION=1


def radii(poses):
    # Optional face bones disappear in the numerical fitting rig. Body anchors
    # remain identical in both rigs, so their rest span defines the same proxy.
    result=[]
    for pose in poses:
        m=semantics(pose['rig']);nodes={n['id']:n for n in pose['rig']['nodes']}
        values=[nodes[m[k]]['center'][1] for k in ('head','l_foot','r_foot')]
        result.append(max(100.,max(values)-min(values))*.065)
    return result


def torso(points):
    return (points['l_hip']+points['r_hip'])/2,(points['l_shoulder']+points['r_shoulder'])/2


def attachment(points,part,frame,mapping,radius):
    if part!='back':return points[part]
    hip,chest=torso(points)
    return hip+(chest-hip)*.65+(frame[mapping['spine4']]@np.array([0.,0.,-1.]))*radius


def palm_normal(points,part):
    side=part[0];v=np.cross(points[side+'_index1']-points[side+'_wrist'],points[side+'_pinky1']-points[side+'_wrist'])
    return v/max(np.linalg.norm(v),1e-9)*(-1 if side=='l' else 1)


def measure(poses,contacts):
    states=[target_points(p,include_frames=True) for p in poses]
    points=[s[0] for s in states];frames=[s[2][0] for s in states];maps=[semantics(p['rig']) for p in poses];radius=radii(poses)
    gaps=[float(np.linalg.norm(points[a][hand]-attachment(points[b],part,frames[b],maps[b],radius[b]))) for a,hand,b,part in contacts]
    hip0,chest0=torso(points[0]);hip1,chest1=torso(points[1])
    overlap=max(0.,sum(radius)*.9-segment_distance(hip0,chest0,hip1,chest1))
    return dict(version=VERSION,gapsCm=gaps,torsoPenetrationCm=float(overlap),radiiCm=radius)
