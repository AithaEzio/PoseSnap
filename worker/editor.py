"""Pose-channel editing and local drafts. Rig definitions stay immutable."""
import copy
import math
import re
import time
import uuid
from daz import validate_pose
from rigs import profile, pose_bone
from instances import cached_source, identity
from storage import image_dir, read_json, atomic_json, current_editor_draft

def session_folder(root,image_id):
    if re.fullmatch(r'pose-[0-9a-f]{32}',str(image_id)):
        return root/'data/poses'/image_id
    return image_dir(root,image_id)

def new_pose(root,rig_id):
    rig=profile(root,rig_id)
    pose=dict(version=1,rigId=rig_id,label='Untitled pose',imageId='pose-'+uuid.uuid4().hex,
        personId=1,sourceId=rig['sourceId'],rig=rig,origin='editor',edited=True,
        rotations={n['id']:[0.,0.,0.] for n in rig['nodes'] if pose_bone(n)},
        translation=[0.,0.,0.],rootRotation=[0.,0.,0.],warnings=[],handRefinement=False)
    validate_pose(pose)
    folder=session_folder(root,pose['imageId'])
    atomic_json(folder/'editor-draft.json',dict(version=1,imageId=pose['imageId'],personKeys=['editor/'+rig_id],poses=[pose],created=time.time()))
    return pose

def pose_history(root,references=None):
    rows=[]
    for folder in (root/'data/poses').glob('pose-*'):
        if not re.fullmatch(r'pose-[0-9a-f]{32}',folder.name):continue
        try:
            draft=read_json(folder/'editor-draft.json',{});poses=draft.get('poses',[])
            if draft.get('version')!=1 or not 1<=len(poses)<=4 or not current_editor_draft(poses) or any(p.get('origin')!='editor' for p in poses):continue
            pose=poses[0]
            rows.append(dict(id=folder.name,name=(str(len(poses))+' mannequins · Pose studio' if len(poses)>1 else pose.get('label','Untitled pose')+' · '+pose['rig'].get('label',pose['rigId'])),
                thumbnail='/logo.svg',created=(folder/'editor-draft.json').stat().st_mtime,solved=True,kind='pose'))
        except (OSError,ValueError,KeyError,TypeError,AttributeError):continue
    if references is None:
        from storage import history
        references=history(root)
    for reference in references:
        path=image_dir(root,reference['id'])/'editor-draft.json'
        try:
            draft=read_json(path,{});poses=draft.get('poses',[])
            if draft.get('version')!=1 or not poses or not current_editor_draft(poses) or any(p.get('imageId')!=reference['id'] for p in poses):continue
            rows.append(dict(id=reference['id'],name=reference['name']+' · Pose edit',thumbnail=reference['thumbnail'],
                created=path.stat().st_mtime,solved=True,kind='pose'))
        except (OSError,ValueError,KeyError,TypeError,AttributeError):continue
    return rows

def same_profile(a,b):
    """Preserve structural identity, allowing only floating-point transport noise.

    Python → Rust → JavaScript JSON can change the final binary rounding bit.
    This tolerance is far below any exported degree or centimetre precision.
    """
    if isinstance(a,bool) or isinstance(b,bool):return type(a) is type(b) and a==b
    if isinstance(a,(int,float)) and isinstance(b,(int,float)):
        return math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-10)
    if isinstance(a,dict) and isinstance(b,dict):
        if 'nodes' in a and 'nodes' in b and 'id' in a and 'id' in b:
            # A legacy cached default and the same bundled rig differ only in
            # provenance. Geometry, limits and formulas must still match.
            a={k:v for k,v in a.items() if k!='metadataSource'}
            b={k:v for k,v in b.items() if k!='metadataSource'}
        return a.keys()==b.keys() and all(same_profile(a[k],b[k]) for k in a)
    if isinstance(a,list) and isinstance(b,list):return len(a)==len(b) and all(same_profile(x,y) for x,y in zip(a,b))
    return type(a) is type(b) and a==b

def reach(pose,bone,target):
    import numpy as np
    from scipy.optimize import least_squares
    from retarget import fk
    validate_pose(pose);target=np.asarray(target,dtype=float)
    if target.shape!=(3,) or not np.isfinite(target).all():raise ValueError('Enter a finite reach target in centimetres.')
    nodes={n['id']:n for n in pose['rig']['nodes']}
    if bone not in ('lHand','rHand','l_hand','r_hand','lFoot','rFoot','l_foot','r_foot') or bone not in nodes:raise ValueError('Reach targets support hands and feet. Choose one of those joints.')
    if pose.get('pins',{}).get(bone,{}).get('position'):raise ValueError('Unpin Position for this joint before fitting a new reach target.')
    arm='hand' in bone.lower();chain=[];parent=nodes[bone]['parent']
    while parent in nodes:
        name=parent.lower()
        if name in ('hip','pelvis') or nodes[parent]['type']!='bone':break
        if arm and not any(p in name for p in ('forearm','shldr','upperarm','collar','shoulder')):break
        if not arm and not any(p in name for p in ('thigh','shin')):break
        chain.append(parent);parent=nodes[parent]['parent']
    variables=[];base=[];lower=[];upper=[]
    for name in chain:
        for axis in range(3):
            limit=nodes[name].get('limits',{}).get('xyz'[axis],{})
            if limit.get('locked') or 'xyz'[axis] in nodes[name].get('driven',[]):continue
            lo=limit.get('min',-180) if limit.get('clamped') else -180
            hi=limit.get('max',180) if limit.get('clamped') else 180
            if hi-lo<1e-5:continue
            variables.append((name,axis));base.append(float(np.clip(pose['rotations'].get(name,[0,0,0])[axis],lo,hi)));lower.append(lo);upper.append(hi)
    if not variables:raise ValueError('This limb has no editable parent rotation channels. Refresh its rig metadata or choose another joint.')
    root=next(n['id'] for n in pose['rig']['nodes'] if not n['parent'])
    def candidate(values):
        channels={k:list(v) for k,v in pose['rotations'].items()}
        for (name,axis),value in zip(variables,values):channels.setdefault(name,[0,0,0])[axis]=float(value)
        preview=dict(channels);preview[root]=pose.get('rootRotation',[0,0,0])
        frames,positions=fk(pose['rig'],preview,pose['translation'])
        return channels,positions[bone],frames,positions
    def residual(values):
        from scipy.spatial.transform import Rotation
        _,actual,frames,positions=candidate(values);pin_errors=[]
        for name,pin in pose.get('pins',{}).items():
            if 'position' in pin:pin_errors.extend((positions[name]-pin['position'])*4)
            if 'rotation' in pin:pin_errors.extend(Rotation.from_matrix(frames[name]@Rotation.from_quat(pin['rotation']).as_matrix().T).as_rotvec()*40)
        return np.r_[(actual-target)/2,pin_errors,(np.asarray(values)-base)/90*.08]
    fit=least_squares(residual,base,bounds=(lower,upper),max_nfev=100,ftol=1e-7,xtol=1e-7,gtol=1e-7)
    channels,actual,_,_=candidate(fit.x);result=copy.deepcopy(pose);result['rotations']=channels;result['edited']=True
    error=float(np.linalg.norm(actual-target))
    return dict(pose=result,actual=actual.tolist(),distanceCm=error,reached=error<=.5)

def checked_poses(root,image_id,poses):
    if not isinstance(poses,list) or not 1<=len(poses)<=4 or len({p.get('personId') for p in poses})!=len(poses):raise ValueError('The editor draft has invalid participants.')
    if not current_editor_draft(poses):raise ValueError('This test draft belongs to an earlier development build.')
    if any(p.get('origin')=='editor' for p in poses):
        if not re.fullmatch(r'pose-[0-9a-f]{32}',str(image_id)):raise ValueError('Invalid studio pose session.')
        if all(p.get('studio') is True for p in poses):
            keys=[]
            for pose in poses:
                validate_pose(pose)
                if pose.get('imageId')!=image_id or pose.get('origin')!='editor' or type(pose.get('personId')) is not int or pose['personId']<1 or pose.get('layout'):raise ValueError('The mannequin belongs to another studio scene.')
                if not same_profile(pose['rig'],profile(root,pose['rigId'])):raise ValueError('The rig metadata changed. Refresh or recreate this studio scene.')
                source=pose.get('studioSource')
                if source:
                    source_folder=image_dir(root,source['imageId']);people=read_json(source_folder/'people.json',[])
                    person=next((p for p in people if p['id']==source['personId']),None)
                    if not person or identity(person)!=source.get('personKey') or not cached_source(source_folder,person,source.get('extractionMethod','smart'),context=source.get('sourceGuidance') or dict(version=1,id='original')):raise ValueError('The source detection or extraction changed. Reopen its current extraction to edit it.')
                    keys.append(source['personKey'])
                else:
                    if pose.get('quality'):raise ValueError('A neutral mannequin cannot have extraction confidence.')
                    keys.append('editor/'+str(pose['personId']))
            return session_folder(root,image_id),keys
        if len(poses)!=1:raise ValueError('Invalid manual pose session.')
        pose=poses[0];validate_pose(pose)
        if pose.get('imageId')!=image_id or pose.get('personId')!=1 or pose.get('layout') or pose.get('quality'):raise ValueError('The manual pose belongs to a different session.')
        if not same_profile(pose['rig'],profile(root,pose['rigId'])):raise ValueError('The rig connection changed. Start a new pose using its current metadata.')
        return session_folder(root,image_id),['editor/'+pose['rigId']]
    folder=image_dir(root,image_id);people=read_json(folder/'people.json',[]);keys=[]
    for pose in poses:
        validate_pose(pose)
        if pose.get('imageId')!=image_id:raise ValueError('The editor draft belongs to a different reference.')
        if not same_profile(pose['rig'],profile(root,pose['rigId'])):raise ValueError('The rig connection changed. Extract or rebuild before using this editor draft.')
        person=next((p for p in people if p['id']==pose['personId']),None)
        if not person or not cached_source(folder,person,pose.get('extractionMethod','smart'),context=pose.get('sourceGuidance') or dict(version=1,id='original')):raise ValueError('The detection or extraction changed. Extract the participant again before using this draft.')
        keys.append(identity(person))
    layouts=[p.get('layout') for p in poses]
    if any(layouts) and (not all(layouts) or len({p['id'] for p in layouts})!=1 or any(set(p['personIds'])!={v['personId'] for v in poses} for p in layouts)):
        raise ValueError('The editor draft has an inconsistent interaction layout.')
    return folder,keys

def operation(root,payload,progress):
    kind=payload.get('editorOperation')
    if kind=='new_pose':
        result=new_pose(root,payload['rigId']);progress('Neutral editor pose ready',100);return result
    if kind=='convert_pose':
        poses=payload['poses'];pose=payload['pose'];checked_poses(root,pose['imageId'],poses)
        if not any(p==pose for p in poses):raise ValueError('The selected mannequin changed. Retry from its current pose.')
        baseline=payload.get('baseline',pose)
        checked_poses(root,pose['imageId'],[baseline] if not pose.get('layout') else payload.get('baselines',poses))
        if baseline['personId']!=pose['personId'] or baseline['rigId']!=pose['rigId']:raise ValueError('The reset baseline no longer matches this mannequin.')
        from studio import convert_pose
        target=profile(root,payload['rigId']);progress('Transferring edited body and finger channels',30)
        result=dict(pose=convert_pose(pose,target),baseline=convert_pose(baseline,target));progress('Edited pose converted',100);return result
    if kind=='add_mannequin':
        poses=payload['poses'];checked_poses(root,poses[0]['imageId'],poses)
        if len(poses)>=4:raise ValueError('This lightweight studio supports four mannequins per scene. Start another scene to add more.')
        studio=all(p.get('studio') for p in poses);scene_id=poses[0]['imageId'] if studio else 'pose-'+uuid.uuid4().hex
        members=copy.deepcopy(poses)
        for member in members:
            if member.get('origin')!='editor':
                folder=image_dir(root,member['imageId']);person=next(p for p in read_json(folder/'people.json',[]) if p['id']==member['personId'])
                member['studioSource']=dict(imageId=member['imageId'],personId=member['personId'],personKey=identity(person),extractionMethod=member.get('extractionMethod','smart'),sourceGuidance=member.get('sourceGuidance'))
            member.update(imageId=scene_id,studio=True,origin='editor');member.pop('layout',None)
        rig=profile(root,payload['rigId']);new_id=max(p['personId'] for p in members)+1
        member=dict(version=1,rigId=rig['id'],label='Mannequin '+str(new_id),imageId=scene_id,personId=new_id,sourceId=rig['sourceId'],rig=rig,
            origin='editor',studio=True,edited=True,rotations={n['id']:[0.,0.,0.] for n in rig['nodes'] if pose_bone(n)},
            translation=[max(p['translation'][0] for p in members)+100.,0.,members[0]['translation'][2]],rootRotation=[0.,0.,0.],warnings=[],handRefinement=False)
        members.append(member);folder,keys=checked_poses(root,scene_id,members)
        atomic_json(folder/'editor-draft.json',dict(version=1,imageId=scene_id,personKeys=keys,poses=members))
        return dict(poses=members,selected=new_id)
    if kind=='reach':
        pose=payload['pose'];poses=payload.get('poses',[pose]);checked_poses(root,pose['imageId'],poses)
        if not any(p==pose for p in poses):raise ValueError('The selected pose no longer matches this editor session. Retry from the current pose.')
        progress('Fitting the existing limb rotation channels',30)
        result=reach(pose,payload['bone'],payload['target']);progress('Reach target evaluated',100);return result
    if kind=='save_draft':
        poses=payload['poses'];folder,keys=checked_poses(root,payload['imageId'],poses)
        atomic_json(folder/'editor-draft.json',dict(version=1,imageId=payload['imageId'],personKeys=keys,poses=poses))
        return dict(saved=True)
    if kind=='load_draft':
        folder=session_folder(root,payload['imageId']);draft=read_json(folder/'editor-draft.json')
        if not draft or draft.get('version')!=1:raise ValueError('No editor draft is saved for this reference yet.')
        _,keys=checked_poses(root,payload['imageId'],draft.get('poses'))
        if draft.get('personKeys')!=keys:raise ValueError('This editor draft uses older person detections. Rebuild it from current extractions.')
        return draft
    raise ValueError('Unknown editor operation')
