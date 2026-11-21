"""CPU-only transfer of an edited Genesis pose. Never changes either rig."""
import copy
import numpy as np
from scipy.spatial.transform import Rotation
from retarget import fk, rotation, align, constrained_rotation
from rigs import evaluated_channels, pose_bone
from daz import validate_pose

def semantics(rig):
    ids={n['id'] for n in rig['nodes']};out={}
    def add(key,*names):
        match=next((n for n in names if n in ids),None)
        if match:out[key]=match
    for key,names in {'hip':['hip'],'pelvis':['pelvis'],'spine1':['abdomenLower','spine1'],
        'spine2':['abdomenUpper','spine2'],'spine3':['chestLower','spine3'],'spine4':['chestUpper','spine4'],
        'neck1':['neckLower','neck1'],'neck2':['neckUpper','neck2'],'head':['head']}.items():add(key,*names)
    for side in ('l','r'):
        for key,names in {'shoulder':['Collar','_shoulder'],'upperarm':['ShldrTwist','_upperarm','ShldrBend'],
            'forearm':['ForearmTwist','_forearm','ForearmBend'],'hand':['Hand','_hand'],
            'thigh':['ThighTwist','_thigh','ThighBend'],'shin':['Shin','_shin'],
            'foot':['Foot','_foot'],'toes':['Toe','_toes']}.items():add(side+'_'+key,*(side+n for n in names))
        for finger in ('Thumb','Index','Mid','Ring','Pinky'):
            for segment in (1,2,3):add(f'{side}_{finger.lower()}{segment}',f'{side}{finger}{segment}',f'{side}_{finger.lower()}{segment}')
    return out

def rest_frame(rig,key,mapping):
    """Anatomical axes include hand width to retain palm/finger roll."""
    nodes={n['id']:n for n in rig['nodes']};node=nodes[mapping[key]]
    start=node
    bend={'upperarm':'ShldrBend','forearm':'ForearmBend','thigh':'ThighBend'}
    side=key[:1];part=key[2:]
    if part in bend and side+bend[part] in nodes:start=nodes[side+bend[part]]
    endpart={'shoulder':'upperarm','upperarm':'forearm','forearm':'hand','hand':'mid1','thigh':'shin','shin':'foot','foot':'toes'}.get(part)
    end=nodes.get(mapping.get(side+'_'+endpart)) if endpart else None
    if end and endpart in bend and side+bend[endpart] in nodes:end=nodes[side+bend[endpart]]
    direction=np.asarray(end['center'] if end else start['end'])-start['center']
    if key in ('hip','pelvis','head','neck1','neck2','spine1','spine2','spine3','spine4'):return np.eye(3)
    if np.linalg.norm(direction)<1e-7:return np.eye(3)
    y=direction/np.linalg.norm(direction);guide=np.array([0.,0.,1.])
    if part=='hand' or any(part.startswith(f) for f in ('thumb','index','mid','ring','pinky')):
        index=nodes.get(mapping.get(side+'_index1'));pinky=nodes.get(mapping.get(side+'_pinky1'))
        if index and pinky:
            width=np.asarray(index['center'])-pinky['center']
            guide=np.cross(y,width)*(1 if side=='l' else -1)
    if part in ('foot','toes'):guide=np.array([0.,1.,0.])
    z=guide-y*(y@guide)
    if np.linalg.norm(z)<1e-7:z=np.array([1.,0.,0.])-y*y[0]
    z/=np.linalg.norm(z);x=np.cross(y,z)
    return np.column_stack((x,y,z))

def convert_pose(pose,target):
    validate_pose(pose)
    if pose['rigId']==target['id']:return copy.deepcopy(pose)
    source=pose['rig'];sm=semantics(source);tm=semantics(target)
    if any(k not in sm or k not in tm for k in ('hip','head')):raise ValueError('This rig lacks supported body metadata. Refresh its connection in Settings.')
    source_root=next(n for n in source['nodes'] if not n['parent']);target_root=next(n for n in target['nodes'] if not n['parent'])
    source_channels=dict(pose['rotations']);source_channels[source_root['id']]=pose.get('rootRotation',[0,0,0])
    source_world,_=fk(source,source_channels)
    inverse={name:key for key,name in tm.items()}
    for side in ('l','r'):
        for part,bend in [('upperarm','ShldrBend'),('forearm','ForearmBend'),('thigh','ThighBend')]:
            if any(n['id']==side+bend for n in target['nodes']):inverse[side+bend]=side+'_'+part
    channels={n['id']:[0.,0.,0.] for n in target['nodes'] if pose_bone(n)}
    channels[target_root['id']]=[0.,0.,0.];world={};limited=[];pending=list(target['nodes'])
    while pending:
        advanced=False
        for node in pending[:]:
            if node['parent'] and node['parent'] not in world:continue
            parent=world.get(node['parent'],np.eye(3));orient=rotation(node['orientation']);key=inverse.get(node['id'])
            if not node['parent']:desired=source_world[source_root['id']]
            elif key in sm:
                calibration=rest_frame(source,key,sm)@rest_frame(target,key,tm).T
                desired=source_world[sm[key]]@calibration
                if node['id'].endswith('Bend'):
                    axis=np.asarray(node['end'])-node['center'];desired=parent@align(axis,parent.T@desired@axis)
            else:desired=parent
            if key in sm or not node['parent']:
                fitnode=copy.deepcopy(node)
                for axis in node.get('driven',[]):fitnode['limits'][axis]={**fitnode['limits'].get(axis,{}),'locked':True}
                values,changed=constrained_rotation(fitnode,orient.T@parent.T@desired@orient)
                channels[node['id']]=values
                if changed:limited.append(node['id'])
            effective=evaluated_channels(target,channels).get(node['id'],[0,0,0])
            world[node['id']]=parent@orient@rotation(effective,node['order'])@orient.T
            pending.remove(node);advanced=True
        if not advanced:raise ValueError('This target has an invalid rig hierarchy. Refresh its connection.')
    result=copy.deepcopy(pose);result.update(rigId=target['id'],sourceId=target['sourceId'],rig=copy.deepcopy(target),
        rotations={n['id']:channels[n['id']] for n in target['nodes'] if pose_bone(n)},rootRotation=channels[target_root['id']],edited=True)
    result['warnings']=list(dict.fromkeys(pose.get('warnings',[])+([f"Conversion to {target['label']} reached movement limits: "+', '.join(limited)] if limited else [])))
    if pose.get('pins'):
        preview=dict(result['rotations']);preview[target_root['id']]=result['rootRotation']
        frames,positions=fk(target,preview,result['translation']);pins={}
        target_ids={n['id'] for n in target['nodes'] if n['type']=='bone'}
        source_keys={name:key for key,name in sm.items()}
        for side in ('l','r'):
            for part,bend in [('upperarm','ShldrBend'),('forearm','ForearmBend'),('thigh','ThighBend')]:source_keys[side+bend]=side+'_'+part
        for name,pin in pose['pins'].items():
            mapped=name if name in target_ids else tm.get(source_keys.get(name))
            if mapped not in target_ids:continue
            capture=pins.setdefault(mapped,{})
            if 'position' in pin:capture['position']=positions[mapped].tolist()
            if 'rotation' in pin:capture['rotation']=Rotation.from_matrix(frames[mapped]).as_quat().tolist()
        result['pins']=pins
        result['warnings'].append('Joint pins recaptured on the converted rig; unsupported pins omitted.' if len(pins)!=len(pose['pins']) else 'Joint pins recaptured on the converted rig.')
    validate_pose(result);return result
