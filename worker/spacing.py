"""Experimental camera-relative spacing, with immutable local pose and scale.

MoGe observes surfaces, not skeleton roots. Rays are compared with a fixed torso
ellipsoid proxy; this is deliberately labelled approximate, pending the pilot.
"""
import copy
import hashlib
import json
import re
import time
import uuid
import numpy as np
from storage import atomic_json,read_json,image_dir
from measurements import target_points,project_target,AXES,stamp
from studio import semantics

VERSION=1
BOUND_CM=25.


def mask_signature(folder,people):
    from instances import identity
    values=[]
    for person in people:
        for suffix in ('.png','.json'):
            path=folder/('mask-'+identity(person)+suffix)
            values.append((path.name,hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None))
    return stamp(values)


def torso_surface(pose,xy):
    points,_,(frames,joints)=target_points(pose,include_frames=True);mapping=semantics(pose['rig'])
    hip=(points['l_hip']+points['r_hip'])/2;chest=(points['l_shoulder']+points['r_shoulder'])/2
    up=chest-hip;length=np.linalg.norm(up);up/=max(length,1e-9)
    right=points['l_shoulder']-points['r_shoulder'];right-=up*(right@up);width=np.linalg.norm(right);right/=max(width,1e-9)
    front=np.cross(right,up);front/=max(np.linalg.norm(front),1e-9)
    center=(hip+chest)/2;camera=pose['referenceCamera'];k=np.asarray(camera['intrinsics'])
    rotation=np.column_stack((right,up,front))*AXES[:,None]
    center=(center+camera['originCm'])*AXES
    radius=np.array([max(6.,width*.55),max(8.,length*.7),max(5.,width*.3)])
    rays=np.column_stack(((np.asarray(xy)[:,0]-k[0,2])/k[0,0],(np.asarray(xy)[:,1]-k[1,2])/k[1,1],np.ones(len(xy))))
    direction=(rays@rotation)/radius;origin=(-center@rotation)/radius
    a=np.sum(direction**2,axis=1);b=2*(direction@origin);c=origin@origin-1;discriminant=b*b-4*a*c
    z=(-b-np.sqrt(np.maximum(discriminant,0)))/(2*a)
    return np.where((discriminant>=0)&(z>0),z,np.nan)


def torso_samples(person,mask,others,depth,valid,image_size):
    import cv2
    from camera_depth import sample
    k=person.get('keypoints',[])
    if len(k)<13 or any(len(k[i])<3 or k[i][2]<.7 for i in (5,6,11,12)):
        raise ValueError('Visible shoulders and hips are needed to inspect spacing. The current layout is kept.')
    w,h=image_size;polygon=np.asarray([k[i][:2] for i in (5,6,12,11)],dtype=np.float32)
    center=polygon.mean(0);polygon=center+(polygon-center)*.65
    area=np.zeros((h,w),dtype=np.uint8);cv2.fillConvexPoly(area,np.rint(polygon).astype(np.int32),1)
    kernel=np.ones((7,7),dtype=np.uint8);interior=cv2.erode(np.asarray(mask,dtype=np.uint8),kernel)>0
    usable=(area>0)&interior
    for other in others:usable &= ~cv2.dilate(np.asarray(other,dtype=np.uint8),kernel).astype(bool)
    y,x=np.nonzero(usable)
    if len(x)<64:raise ValueError('Too little unoccluded torso surface is visible for spacing. The current layout is kept.')
    rows=np.linspace(0,len(x)-1,min(1024,len(x))).round().astype(int);xy=np.column_stack((x[rows],y[rows]))
    values=sample(depth,valid,xy,image_size);known=np.isfinite(values)
    if np.count_nonzero(known)<48:raise ValueError('Torso depth evidence is incomplete. The current layout is kept.')
    xy,values=xy[known],values[known]
    median=float(np.median(values));mad=float(np.median(np.abs(values-median)))
    if mad>max(.04,median*.08):raise ValueError('Torso depth evidence varies too much to refine spacing safely. The current layout is kept.')
    return dict(xy=xy,depthCm=values*100,medianCm=median*100,madCm=mad*100)


def fit(poses,samples,contacts=(),progress=lambda *_:None):
    from scipy.optimize import least_squares
    from textpose import protected
    original=copy.deepcopy(poses);result=copy.deepcopy(poses)
    if len(poses)<2 or len(samples)!=len(poses):raise ValueError('Refine spacing needs at least two selected people.')
    if any(p.get('referenceCamera')!=poses[0].get('referenceCamera') for p in poses):raise ValueError('Spacing needs a shared reference camera. Arrange the interaction again.')
    parent=list(range(len(poses)))
    def find(i):
        while parent[i]!=i:i=parent[i]
        return i
    by_id={p['personId']:i for i,p in enumerate(poses)}
    for contact in contacts:
        if contact.get('enabled') and contact.get('confirmed') and contact.get('personId') in by_id and contact.get('otherId') in by_id:
            a,b=by_id[contact['personId']],by_id[contact['otherId']];parent[find(b)]=find(a)
    groups=sorted({find(i) for i in parent});fixed={find(i) for i,p in enumerate(poses) if any('position' in pin for pin in p.get('pins',{}).values())}
    # A confirmed contact requires a common rigid translation. Since spacing
    # refines relative positions, its entire linked component remains anchored.
    fixed.update(g for g in groups if sum(find(i)==g for i in parent)>1)
    variables=[g for g in groups if g not in fixed]
    predicted=[torso_surface(p,s['xy']) for p,s in zip(poses,samples)]
    active=[]
    for s,z in zip(samples,predicted):
        known=np.isfinite(z)
        if np.count_nonzero(known)<32:raise ValueError('The posed torso proxy does not overlap enough visible surface. Inspect Reference; the current layout is kept.')
        active.append(known)
    observed=np.array([np.median(s['depthCm'][known]) for s,known in zip(samples,active)])
    initial=np.array([np.median(z[known]) for z,known in zip(predicted,active)])
    # A common depth offset is unobservable here. Compare actor differences;
    # never substitute a torso depth median for an actor's pelvis coordinate.
    observed-=observed.mean();initial_relative=initial-initial.mean()
    initial_error=float(np.median(np.abs(initial_relative-observed)))
    diagnostic=dict(version=VERSION,experimental=True,changed=False,beforeResidualCm=initial_error,afterResidualCm=initial_error,
                    limitCm=BOUND_CM,surface='fixed captured-rig torso ellipsoid',stage='camera-relative-placement',
                    limits='Learned source surface evidence and proxy geometry; physical distances and DAZ world Z are unverified.',translations=[])
    if not variables or initial_error<1.:
        diagnostic['reason']='Pins, confirmed contacts or already consistent depth leave no safe spacing correction.'
        return result,diagnostic
    def apply(values):
        shifts={g:float(v) for g,v in zip(variables,values)}
        for i,(p,before) in enumerate(zip(result,original)):
            delta=shifts.get(find(i),0.)
            # Preserve floor height. Camera-forward is workspace -Z in this
            # extraction convention, not the destination scene's world axes.
            p['translation']=[before['translation'][0],before['translation'][1],before['translation'][2]-delta]
        return shifts
    def residual(values):
        apply(values);medians=[]
        for p,s,known in zip(result,samples,active):
            z=torso_surface(p,s['xy'])[known]
            if not np.isfinite(z).all():return np.r_[np.full(len(poses),1000.),values/20.,[np.mean(values)/2.]]
            medians.append(np.median(z))
        relative=np.array(medians)-np.mean(medians)
        return np.r_[(relative-observed)/2.,values/20.,[np.mean(values)/2.]]
    progress('Comparing visible torso surfaces in the reference camera',70)
    solved=least_squares(residual,np.zeros(len(variables)),bounds=(-BOUND_CM,BOUND_CM),max_nfev=35,ftol=1e-6)
    shifts=apply(solved.x);final=np.array([np.median(torso_surface(p,s['xy'])[known]) for p,s,known in zip(result,samples,active)])
    final_error=float(np.median(np.abs(final-final.mean()-observed)))
    try:
        for before,after in zip(original,result):
            if before['rotations']!=after['rotations'] or before['rig']!=after['rig']:raise ValueError('Spacing changed protected rig state')
            protected(before,after,[])
            old,_=target_points(before);new,_=target_points(after)
            keys=[k for k in old if k.endswith(('shoulder','hip','knee','ankle'))]
            drift=np.linalg.norm(project_target([new[k] for k in keys],after['referenceCamera'])-project_target([old[k] for k in keys],before['referenceCamera']),axis=1)
            if np.max(drift)>max(3.,.01*before['referenceCamera']['imageSize'][1]):raise ValueError('Spacing would visibly worsen the shared-camera projection')
        if not np.isfinite(final_error) or final_error>initial_error*.9:raise ValueError('Depth evidence cannot improve this layout safely')
    except ValueError as error:
        diagnostic['reason']=str(error)+'. The current layout is kept.'
        return original,diagnostic
    diagnostic.update(changed=True,afterResidualCm=final_error,reason='Inspect the camera-relative placement before applying.',
                      translations=[dict(personId=p['personId'],cameraForwardCm=shifts.get(find(i),0.)) for i,p in enumerate(poses)])
    return result,diagnostic


def geometry_provider(poses):
    engines={(pose.get('referenceEvidence') or {}).get('geometryEngine','moge2') for pose in poses}
    if len(engines)!=1 or not engines<={'moge2','moge3'}:
        raise ValueError('These people use different geometry engines. Rebuild the interaction with one engine before refining spacing.')
    return 'MoGe-3' if engines=={'moge3'} else 'MoGe-2'


def transaction(root,payload,progress,camera_provider=None):
    from editor import checked_poses
    from posture import context_key
    from camera_depth import load
    from qualification import signature
    action=payload.get('action','preview');image_id=payload['imageId'];folder=image_dir(root,image_id)
    token=payload.get('previewId','')
    if action in ('apply','cancel'):
        if not re.fullmatch('[a-f0-9]{32}',token):raise ValueError('Invalid spacing preview')
        path=root/'temp/spacing-previews'/f'{token}.json'
        if action=='cancel':path.unlink(missing_ok=True);return dict(cancelled=True)
        pending=read_json(path)
        if not pending or pending['imageId']!=image_id or time.time()-pending['created']>1800:raise ValueError('Spacing preview expired. Preview again.')
    elif action!='preview':raise ValueError('Unknown spacing operation')
    current=copy.deepcopy(payload.get('currentPoses',[]));checked_poses(root,image_id,current)
    if len(current)<2 or any(not p.get('referenceCamera') for p in current):raise ValueError('Arrange two or more reference people before refining spacing.')
    from PIL import Image
    image=np.asarray(Image.open(folder/'source.png').convert('RGB'))
    people=read_json(folder/'people.json',[]);chosen=[next((p for p in people if p['id']==pose['personId']),None) for pose in current]
    if any(p is None for p in chosen):raise ValueError('The reference people changed. Extract their current selections again.')
    # Pins, captured rig geometry and source ownership are part of the pending
    # edit too. A new pin must invalidate a preview even if no joint moved yet.
    context=stamp([context_key(current),current,people,payload.get('contacts',[])])
    component=signature('relative-spacing',root)
    if read_json(folder/'image.json',{}).get('inputKind','photo')!='photo':
        raise ValueError('Camera-relative spacing needs a photograph. Use Studio placement for a depth reference.')
    provider=geometry_provider(current)
    depth_options={'provider':provider} if provider!='MoGe-2' else {}
    if action=='apply':
        depth=load(root,folder,image,**depth_options)
        if not depth or pending.get('depthProvider','MoGe-2')!=provider or pending['context']!=context or pending['componentSignature']!=component or pending['depthSha256']!=depth[0]['sha256'] or pending['maskSignature']!=mask_signature(folder,chosen) or pending.get('resultSignature')!=stamp(pending['result']):
            raise ValueError('The pose, people, contacts or depth evidence changed. Preview spacing again.')
        result=pending['result']
        if not result['diagnostics']['spacing']['changed']:raise ValueError('This preview retained the current layout; there is no correction to apply.')
        # Commit poses and their diagnostic receipt together. A failed write
        # leaves the accepted draft and retryable preview intact.
        _,keys=checked_poses(root,image_id,result['poses'])
        atomic_json(folder/'editor-draft.json',dict(version=1,imageId=image_id,personKeys=keys,poses=result['poses'],spacing=result))
        path.unlink(missing_ok=True)
        return result
    evidence=load(root,folder,image,**depth_options)
    if evidence is None:
        if provider!='MoGe-2':raise ValueError('Legacy geometry evidence is unavailable. Rebuild this interaction with the current engine, inspect it and Apply before refining spacing. The accepted poses are kept.')
        if camera_provider is None:raise ValueError('Camera depth is unavailable. Extract the reference again.')
        camera_provider(image,progress,folder)
        evidence=load(root,folder,image,**depth_options)
    if evidence is None:raise ValueError('Camera depth could not be cached. The current layout is kept.')
    from segmentation import selected_mask
    masks=[]
    for person in chosen:
        progress('Checking visible surface ownership for Person '+str(person['id']),35)
        masks.append(selected_mask(root,folder,image,person,[p for p in people if p['id']!=person['id']],progress)[0,:,:,0])
    meta,depth,valid=evidence
    samples=[torso_samples(person,mask,[m for j,m in enumerate(masks) if j!=i],depth,valid,meta['imageSize']) for i,(person,mask) in enumerate(zip(chosen,masks))]
    poses,diagnostic=fit(current,samples,payload.get('contacts',[]),progress)
    for pose in poses:
        if diagnostic['changed'] and pose.get('quality'):pose['quality']['stale']=True
    result=dict(version=3,id=uuid.uuid4().hex,imageId=image_id,poses=poses,operation='spacing',warnings=[diagnostic['limits']],contacts=payload.get('contacts',[]),
                diagnostics=dict(accepted=diagnostic['changed'],contacts=0,armAdjustments=0,maximumProxyOverlapCm=0.,depthUncertain=True,spacing=diagnostic),created=time.time())
    token=uuid.uuid4().hex;result['previewId']=token
    atomic_json(root/'temp/spacing-previews'/f'{token}.json',dict(imageId=image_id,context=context,componentSignature=component,depthProvider=provider,depthSha256=meta['sha256'],maskSignature=mask_signature(folder,chosen),created=time.time(),result=result,resultSignature=stamp(result)))
    progress('Spacing preview ready · current layout is unchanged',100)
    return result
