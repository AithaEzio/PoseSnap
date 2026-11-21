"""DSON rotation math. The exported channel values are authoritative for preview FK."""
import warnings
import numpy as np
from scipy.spatial.transform import Rotation, Slerp
from scipy.optimize import least_squares
from rigs import evaluated_channels, pose_bone

def rotation(values,order='XYZ'):
    lookup=dict(zip('XYZ',values))
    # DSON applies the listed axes in world/extrinsic order. Verified against
    # DAZ Studio 6 world positions (its getWSRot quaternion uses the inverse convention).
    return Rotation.from_euler(order.lower(),[lookup[a] for a in order],degrees=True).as_matrix()

def euler(matrix,order):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        values=Rotation.from_matrix(matrix).as_euler(order.lower(),degrees=True)
    lookup=dict(zip(order,values))
    return [float(lookup[a]) for a in 'XYZ']

def align(a,b):
    a=np.asarray(a,dtype=float);b=np.asarray(b,dtype=float)
    if min(np.linalg.norm(a),np.linalg.norm(b))<1e-7:return np.eye(3)
    a/=np.linalg.norm(a);b/=np.linalg.norm(b)
    cross=np.cross(a,b);length=np.linalg.norm(cross);dot=np.clip(a@b,-1.,1.)
    if length<1e-7:
        if dot>0:return np.eye(3)
        axis=np.cross(a,[1,0,0] if abs(a[0])<.8 else [0,1,0]);axis/=np.linalg.norm(axis)
        return Rotation.from_rotvec(axis*np.pi).as_matrix()
    return Rotation.from_rotvec(cross/length*np.arctan2(length,dot)).as_matrix()

def normalized(name):
    return name.lower().replace('_','').replace('-','')

def constrained_rotation(node, desired):
    """Fit within the rig's channels, prioritizing the visible bone direction.

    Simply clipping a decomposed Euler angle can move a knee or finger in a
    different direction. A bounded fit retains its direction when twist is limited.
    """
    raw=euler(desired,node['order']);values=raw.copy();lower=[];upper=[];free=[]
    for i,axis in enumerate('xyz'):
        limit=node['limits'].get(axis,{})
        lo=limit.get('min',-360) if limit.get('clamped') else -360
        hi=limit.get('max',360) if limit.get('clamped') else 360
        if limit.get('locked') or hi-lo<1e-6:values[i]=0. if limit.get('locked') else lo
        else:free.append(i);lower.append(lo);upper.append(hi);values[i]=float(np.clip(values[i],lo,hi))
    if np.linalg.norm(rotation(values,node['order'])-desired)<1e-5:return values,False
    orient=rotation(node['orientation']);axis=np.asarray(node['end'])-node['center'];axis=orient.T@axis
    axis=axis/max(np.linalg.norm(axis),1e-9);target=desired@axis
    def residual(candidate):
        candidate_values=values.copy()
        for i,value in zip(free,candidate):candidate_values[i]=value
        matrix=rotation(candidate_values,node['order'])
        return np.concatenate(((matrix@axis-target)*6.,(matrix-desired).ravel()*.3))
    if free:
        best=least_squares(residual,[values[i] for i in free],bounds=(lower,upper),max_nfev=50,ftol=1e-6,xtol=1e-6,gtol=1e-6)
        for i,value in zip(free,best.x):values[i]=float(value)
    changed=Rotation.from_matrix(rotation(values,node['order']).T@desired).magnitude()>np.radians(1.)
    return values,changed

def source_map(names):
    """Semantic aliases are resolved against named MHR joints, never keypoint indices."""
    lookup={normalized(n):i for i,n in enumerate(names)}
    aliases={
      'hip':['root','hips','pelvis'], 'pelvis':['root','pelvis'],
      'abdomenLower':['c_spine0','spine1'], 'abdomenUpper':['c_spine1','spine2'],
      'chestLower':['c_spine2','spine3'], 'chestUpper':['c_spine3','spine4'],
      'neckLower':['c_neck','neck1'], 'neckUpper':['c_neck','neck2'], 'head':['c_head','head'],
      'spine1':['c_spine0','spine1'],'spine2':['c_spine1','spine2'],'spine3':['c_spine2','spine3'],'spine4':['c_spine3','spine4'],
      'neck1':['c_neck','neck1'],'neck2':['c_neck','neck2'],
    }
    for side in ('l','r'):
        semantic={'Collar':['clavicle','clav','shoulder'],'ShldrBend':['upperarm','uparm'],'ShldrTwist':['upperarm','uparm'],
          'ForearmBend':['lowarm','lowerarm','loarm','forearm'],'ForearmTwist':['lowarm','lowerarm','loarm','forearm'],
          'Hand':['wrist','hand'],'ThighBend':['upleg','thigh','upperleg'],'ThighTwist':['upleg','thigh','upperleg'],
          'Shin':['lowleg','lowerleg','shin','calf'],'Foot':['foot','ankle'],'Toe':['toes','toe','ball']}
        equivalents={'Collar':'shoulder','ShldrBend':'upperarm','ForearmBend':'forearm','Hand':'hand','ThighBend':'thigh','Shin':'shin','Foot':'foot','Toe':'toes'}
        for target,bases in semantic.items():
            options=[side+x for x in bases]+[x+side for x in bases]+[('left' if side=='l' else 'right')+x for x in bases]
            aliases[side+target]=options
            if target in equivalents:aliases[side+'_'+equivalents[target]]=options
        for finger,mhr in [('Thumb','thumb'),('Index','index'),('Mid','middle'),('Ring','ring'),('Pinky','pinky')]:
            for segment in (1,2,3):
                options=[f'{side}{base}{segment}' for base in (mhr,finger.lower(),'little' if finger=='Pinky' else mhr)]
                options+= [f'{side}{base}{segment-1}' for base in (mhr,finger.lower())]
                aliases[f'{side}{finger}{segment}']=options
                aliases[f'{side}_{finger.lower()}{segment}']=options
    result={}
    for target,options in aliases.items():
        match=next((lookup[normalized(o)] for o in options if normalized(o) in lookup),None)
        if match is not None:result[target]=match
    return result

def rest_transforms(rig):
    """Immutable fit-local rest data; never cached against a mutable rig identity."""
    nodes={n['id']:n for n in rig['nodes']}
    return {n['id']:(rotation(n['orientation']),np.asarray(n['center'])-(np.asarray(nodes[n['parent']]['center']) if n['parent'] in nodes else np.zeros(3))) for n in rig['nodes']}


def fk(rig,channels,translation=(0,0,0),rest=None):
    channels=evaluated_channels(rig,channels)
    world={};positions={};nodes={n['id']:n for n in rig['nodes']}
    pending=list(rig['nodes']);identity=np.eye(3);zero=np.zeros(3)
    while pending:
        advanced=False
        for node in pending[:]:
            parent=node['parent']
            if parent in nodes and parent not in world:continue
            parent_r=world.get(parent,identity);parent_p=positions.get(parent,zero)
            orient,offset=rest[node['id']] if rest is not None else (rotation(node['orientation']),np.asarray(node['center'])-(np.asarray(nodes[parent]['center']) if parent in nodes else zero))
            local=orient@rotation(channels.get(node['id'],[0,0,0]),node['order'])@orient.T
            world[node['id']]=parent_r@local
            positions[node['id']]=parent_p+parent_r@offset
            if not parent:positions[node['id']]+=np.asarray(translation)
            pending.remove(node);advanced=True
        if not advanced:raise ValueError('The rig has a cyclic or invalid hierarchy')
    return world,positions

def retarget(source,rig):
    from cropped import zero_nodes, neutral as neutral_crop, annotate
    cropped_nodes=zero_nodes(source,rig)
    mapping=source_map(source['names'])
    required=['head','hip']
    if any(key not in mapping for key in required):raise ValueError('The MHR joint metadata does not match the supported rig mapping')
    rest=np.asarray(source['restPositions']);posed=np.asarray(source['rotations']);neutral=np.asarray(source['restRotations'])
    nodes={n['id']:n for n in rig['nodes']};rotations={};world={};warnings_list=list(source.get('warnings',[]))
    missing=[]
    for node in rig['nodes']:
        parent=node['parent'];parent_r=world.get(parent,np.eye(3));desired=parent_r
        index=mapping.get(node['id'])
        if index is not None:
            # Calibrate bone direction to the target rest geometry. This also handles A/T-pose differences.
            children=[i for i,p in enumerate(source['parents']) if p==index and 'twist' not in source['names'][i].lower() and 'proc' not in source['names'][i].lower()]
            source_name=source['names'][index]
            end_name=source_name.replace('_uparm','_lowarm').replace('_lowarm','_wrist') if '_lowarm' in source_name else source_name.replace('_uparm','_lowarm')
            if source_name.endswith('_wrist'):end_name=source_name.replace('_wrist','_middle1')
            if source_name.endswith('_upleg'):end_name=source_name.replace('_upleg','_lowleg')
            if source_name.endswith('_lowleg'):end_name=source_name.replace('_lowleg','_foot')
            if source_name.endswith('_foot'):end_name=source_name.replace('_foot','_ball')
            if end_name!=source_name and end_name in source['names']:children=[source['names'].index(end_name)]
            child=next((i for i in children if np.linalg.norm(rest[i]-rest[index])>.015),None)
            limb=not node['id'] in ('hip','pelvis','head','neck1','neck2','neckLower','neckUpper','abdomenLower','abdomenUpper','chestLower','chestUpper','spine1','spine2','spine3','spine4')
            calibration=align(np.asarray(node['end'])-np.asarray(node['center']),rest[child]-rest[index]) if child is not None and limb else np.eye(3)
            # Two anatomical axes retain palm roll and foot orientation.
            if source_name.endswith(('_wrist','_foot')):
                from studio import semantics,rest_frame
                side=source_name[0];part='hand' if source_name.endswith('_wrist') else 'foot';key=side+'_'+part
                if key in semantics(rig) and child is not None:
                    direction=rest[child]-rest[index];direction/=max(np.linalg.norm(direction),1e-9)
                    guide=np.array([0.,1.,0.])
                    if part=='hand':
                        first=next((i for i,n in enumerate(source['names']) if n==side+'_index1'),None);last=next((i for i,n in enumerate(source['names']) if n==side+'_pinky1'),None)
                        if first is not None and last is not None:guide=np.cross(direction,rest[first]-rest[last])*(1 if side=='l' else -1)
                    z=guide-direction*(guide@direction)
                    if np.linalg.norm(z)>1e-7:
                        z/=np.linalg.norm(z);frame=np.column_stack((np.cross(direction,z),direction,z))
                        calibration=frame@rest_frame(rig,key,semantics(rig)).T
            desired=posed[index]@neutral[index].T@calibration
            # Genesis 8 has sequential bend/twist nodes. Bend gets swing, twist completes the same desired transform.
            if node['id'].endswith('Bend'):
                axis=np.asarray(node['end'])-np.asarray(node['center'])
                desired=parent_r@align(axis,parent_r.T@desired@axis)
        elif node['type']=='bone' and not any(x in node['id'].lower() for x in ['eye','face','jaw','tongue','teeth','brow','lip','cheek','nose','ear','twist','anchor','toe','metatarsal','metacarpal','pectoral']):
            missing.append(node['id'])
        orient=rotation(node['orientation']);local=parent_r.T@desired
        values,limited=constrained_rotation(node,orient.T@local@orient) if index is not None else ([0.,0.,0.],False)
        if node['id'] in cropped_nodes:values=neutral_crop(node,values)
        if limited:warnings_list.append(f"{node['id']} adjusted to its rig's movement limits")
        if pose_bone(node):rotations[node['id']]=values
        world[node['id']]=parent_r@orient@rotation(values,node['order'])@orient.T
    missing=[name for name in missing if not any(s in name for s in ('chin','squint','nostril','infraorbital'))]
    if missing:warnings_list.append('Unmapped optional bones: '+', '.join(missing))
    world,positions=fk(rig,rotations)
    # Include foot endpoints, then lift the authoritative target rig onto the preview floor.
    heights=[positions[n['id']][1] for n in rig['nodes'] if n['id'].lower() in ('lfoot','rfoot','ltoe','rtoe','l_foot','r_foot','l_toes','r_toes')]
    for n in rig['nodes']:
        if n['id'].lower() in ('lfoot','rfoot','ltoe','rtoe','l_foot','r_foot','l_toes','r_toes'):
            heights.append((positions[n['id']]+world[n['id']]@(np.asarray(n['end'])-np.asarray(n['center'])))[1])
    floor=-min(heights) if heights else 0.
    from extraction import extraction_pose
    return extraction_pose(source,annotate(source,dict(version=1,rigId=rig['id'],label=rig['label'],sourceId=rig['sourceId'],imageId=source['imageId'],personId=source['personId'],
        rotations=rotations,translation=[0.,float(floor),0.],rig=rig,warnings=list(dict.fromkeys(warnings_list)),handRefinement=source.get('handRefinement',False),quality=source.get('quality')),cropped_nodes))
