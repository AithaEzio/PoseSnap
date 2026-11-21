"""Conservative fixed-floor support proxies for static snapshots, not physics."""
import re
import copy
import numpy as np
from instructions import positive_text


def kind(prompt):
    prompt = positive_text(prompt)
    for pattern,label in ((r'\b(?:handstand|inverted)\b','inverted'),(r'\b(?:crawl\w*|on all fours|push.?up)\b','crawl'),(r'\b(?:lying|lies?(?: down)?|prone|supine)\b','lying'),(r'\b(?:kneel\w*)\b','kneel'),(r'\b(?:seated|sitting|sits?|sat)\b','seated')):
        if re.search(pattern,prompt,re.I):return label
    return 'upright'


def requirements(prompt):
    text=positive_text(prompt)
    knee=re.search(r'\bon (?:(?:the|their|her|his) )?(left|right) knee\b|\b(left|right) knee (?:touching|on|resting on|against) (?:the )?(?:floor|ground)\b',text)
    feet={}
    for match in re.finditer(r'\b(left|right|both) (?:foot|feet)\b.{0,22}?\b(flat|on (?:the )?heel|on (?:the )?toes|in (?:the )?air|off (?:the )?(?:floor|ground))\b',text):
        state='flat' if match[2]=='flat' else 'heel' if 'heel' in match[2] else 'toe' if 'toes' in match[2] else 'air'
        feet.update({s:state for s in ('l','r') if match[1]=='both' or s==match[1][0]})
    return dict(facing='supine' if re.search(r'\b(?:supine|on (?:the |their |her |his )?back|face up)\b',text) else 'prone' if re.search(r'\b(?:prone|face down|on (?:the |their |her |his )?stomach)\b',text) else '',
                flatFeet=bool(re.search(r'\b(?:both feet|feet)\b.{0,35}\b(?:flat|resting|on (?:the )?(?:floor|ground))\b',text)),
                bothKnees=bool(re.search(r'\bboth knees\b',text)),kneeSide=(knee[1] or knee[2])[0] if knee else '',feet=feet)


def surfaces(pose,include_frames=False):
    from measurements import target_points
    from studio import semantics
    markers,_,(frames,joints)=target_points(pose,include_frames=True);m=semantics(pose['rig'])
    height=max(n['center'][1] for n in pose['rig']['nodes'])-min(n['center'][1] for n in pose['rig']['nodes'])
    radius=max(height,100.)/175.
    result={s+'_'+p:float(markers[s+'_'+p][1]) for s in ('l','r') for p in ('heel','bigtoe','smalltoe','palm')}
    if pose.get('bodyContacts',{}).get('kind',pose.get('bodyGenerator',{}).get('supportKind')) in ('crawl','inverted'):
        for side in ('l','r'):result[side+'_fingers']=min(float(v[1]) for name,v in markers.items() if re.fullmatch(side+r'_(?:thumb|index|middle|ring|pinky)(?:[123]|tip)',name))
    for s in ('l','r'):
        result[s+'_knee']=float(joints[m[s+'_shin']][1]-3*radius)
        result[s+'_elbow']=float(joints[m[s+'_forearm']][1]-2*radius)
    for key,r in (('hip',8),('spine4',10),('head',8)):
        result[key]=float(joints[m[key]][1]-r*radius)
    if include_frames:return result,joints,m,radius,frames
    return result,joints,m,radius


def reviewed_seed(pose,support_kind,required):
    """Authored starting geometry for a selected-knee half kneel."""
    if support_kind!='kneel' or not required.get('kneeSide') or required.get('bothKnees'):return
    from textpose import aim
    down=required['kneeSide'];front='r' if down=='l' else 'l'
    for side in (down,front):
        sign=1 if side=='l' else -1
        aim(pose,side+'_thigh',[sign*.04,-1.,0.] if side==down else [sign*.05,0.,1.])
        aim(pose,side+'_shin',[0.,0.,-1.] if side==down else [0.,-1.,0.])
        aim(pose,side+'_foot',[0.,-.6,-1.] if side==down else [0.,0.,1.])


def place(pose,support_kind,required=None):
    if required is None:required=pose.get('bodyGenerator',{}).get('floorRequirements',{})
    if support_kind!='lying' or not required.get('facing'):return _place(pose,support_kind,required)
    original=copy.deepcopy(pose)
    try:return _place(pose,support_kind,required)
    except ValueError:
        pose.clear();pose.update(copy.deepcopy(original))
    try:
        # A source body may first need horizontal support before its upward
        # surface is chosen. Keep the direct fit when it already works.
        _place(pose,support_kind,{**required,'facing':''})
        return _place(pose,support_kind,required)
    except ValueError:
        pose.clear();pose.update(original)
        raise


def _place(pose,support_kind,required):
    facing=required.get('facing')
    if support_kind=='lying' and facing:
        from textpose import frame,root_rotation
        from studio import semantics
        from retarget import rotation
        from scipy.spatial.transform import Rotation
        worlds,joints=frame(pose);mapping=semantics(pose['rig'])
        axis=joints[mapping['spine4']]-joints[mapping['hip']];axis/=max(np.linalg.norm(axis),1e-9)
        front=worlds[mapping['spine4']]@np.array([0.,0.,1.]);front-=axis*(front@axis);front/=max(np.linalg.norm(front),1e-9)
        target=np.array([0.,1. if facing=='supine' else -1.,0.]);target-=axis*(target@axis);target/=max(np.linalg.norm(target),1e-9)
        angle=np.arctan2(axis@np.cross(front,target),front@target)
        if abs(angle)>.02:
            if pose.get('pins'):raise ValueError('The requested lying direction conflicts with pinned world positions. The accepted result is kept.')
            rotated=Rotation.from_rotvec(axis*angle).as_matrix()@rotation(pose.get('rootRotation',[0.,0.,0.]))
            root_rotation(pose,Rotation.from_matrix(rotated).as_euler('xyz',degrees=True).tolist())
            pose['bodyGenerator']['floorReorientationDegrees']=float(np.rad2deg(angle))
    points,_,_,_=surfaces(pose)
    # Every proxy must stay above the floor. No knee/hand support is inferred
    # merely from the model's heel/toe labels.
    pose['translation'][1]-=min(points.values())
    pose['bodyContacts']=dict(version=2,kind=support_kind,geometry='conservative-proxies',requirements=required)
    try:
        verify(pose)
        return
    except ValueError:
        pass
    # Retargeting changes proportions. Correct small contact gaps with bounded
    # rotations/placement instead of scaling the source or target skeleton.
    from scipy.optimize import least_squares
    from scipy.spatial.transform import Rotation
    points,_,_,_=surfaces(pose)
    choose=lambda names:min(names,key=points.get)
    if support_kind=='kneel':targets=['l_knee','r_knee'] if required.get('bothKnees') else [required['kneeSide']+'_knee'] if required.get('kneeSide') else [choose(('l_knee','r_knee'))]
    elif support_kind=='crawl':targets=['l_palm','r_palm','l_knee','r_knee']
    elif support_kind=='inverted':targets=['l_palm','r_palm']
    elif support_kind=='lying':targets=sorted(('hip','spine4','head','l_elbow','r_elbow'),key=points.get)[:2]
    elif required.get('flatFeet'):targets=[s+'_'+p for s in ('l','r') for p in ('heel','bigtoe','smalltoe')]
    else:targets=[choose((s+'_heel',s+'_bigtoe',s+'_smalltoe')) for s in ('l','r')]
    foot_states={**({'l':'flat','r':'flat'} if required.get('flatFeet') else {}),**required.get('feet',{})}
    for side,state in foot_states.items():
        if state!='air':targets.extend(side+'_'+part for part in (('heel',) if state=='heel' else ('bigtoe','smalltoe') if state=='toe' else ('heel','bigtoe','smalltoe')))
    targets=list(dict.fromkeys(targets))
    variables=[(None,1)];initial=[pose['translation'][1]];low=[initial[0]-25.];high=[initial[0]+25.]
    for node in pose['rig']['nodes']:
        name=node['id']
        permitted=pose.get('bodyGenerator',{}).get('allowedChannels')
        if permitted is not None and name not in permitted:continue
        if name not in pose['rotations'] or not any(k in name.lower() for k in ('thigh','shin','foot','forearm','shldr','upperarm','shoulder','collar','spine','abdomen','chest','neck','head',*(['hand'] if support_kind in ('crawl','inverted') else []))):continue
        for axis,channel in enumerate('xyz'):
            limit=node['limits'].get(channel,{})
            if limit.get('locked') or channel in node.get('driven',[]):continue
            span=90. if support_kind=='seated' and required.get('flatFeet') and any(k in name.lower() for k in ('thigh','shin','foot')) else 30.
            value=pose['rotations'][name][axis];lo=max(value-span,limit.get('min',-180.)) if limit.get('clamped') else value-span;hi=min(value+span,limit.get('max',180.)) if limit.get('clamped') else value+span
            if hi-lo<1e-6:continue
            variables.append((name,axis));initial.append(value);low.append(lo);high.append(hi)
    initial=np.asarray(initial)
    def residual(values):
        for (name,axis),value in zip(variables,values):(pose['translation'] if name is None else pose['rotations'][name])[axis]=float(value)
        current,joints,mapping,_,frames=surfaces(pose,include_frames=True)
        errors=[current[n]/.5 for n in targets]
        errors.extend(max(0.,-y)/.1 for y in current.values())
        errors.extend(max(0.,.6-current[side+'_'+part])/.1 for side,state in foot_states.items() if state=='air' for part in ('heel','bigtoe','smalltoe'))
        if support_kind in ('crawl','inverted'):
            from studio import rest_frame
            for side in ('l','r'):
                normal=frames[mapping[side+'_hand']]@rest_frame(pose['rig'],side+'_hand',mapping)[:,2]
                errors.append(max(0.,normal[1]+.85)*8)
        if support_kind=='seated' and required.get('flatFeet'):
            for side in ('l','r'):
                thigh=joints[mapping[side+'_shin']]-joints[mapping[side+'_thigh']]
                shin=joints[mapping[side+'_foot']]-joints[mapping[side+'_shin']]
                errors.extend([max(0.,abs(thigh[1])/max(np.linalg.norm(thigh),1e-9)-.45)*12,max(0.,shin[1]/max(np.linalg.norm(shin),1e-9)+.7)*12])
        if support_kind=='lying' and facing:
            front=frames[mapping['spine4']]@np.array([0.,0.,1.]);errors.append(max(0.,.5-front[1]*(1 if facing=='supine' else -1))*12)
        if pose.get('pins'):
            for name,pin in pose['pins'].items():
                if 'position' in pin:errors.extend((joints[name]-pin['position'])/.025)
                if 'rotation' in pin:errors.extend(Rotation.from_matrix(frames[name]@Rotation.from_quat(pin['rotation']).as_matrix().T).as_rotvec()/np.deg2rad(.05))
        return np.r_[errors,(values-initial)/80*.15]
    fitted=least_squares(residual,initial,bounds=(low,high),max_nfev=80,ftol=1e-6)
    residual(fitted.x)
    # Soft fitting penalties may leave a submillimetre penetration. A final
    # rigid placement correction enforces the floor before checking contact gaps.
    final,_,_,_=surfaces(pose)
    pose['translation'][1]-=min(0.,min(final.values()))
    verify(pose)


def verify(pose):
    support_kind=pose.get('bodyContacts',{}).get('kind')
    if not support_kind:return
    points,joints,m,radius,frames=surfaces(pose,include_frames=True)
    if min(points.values()) < -.05:raise ValueError('A floor-support proxy penetrates the ground. Your accepted result is kept.')
    touching={name for name,y in points.items() if abs(y)<=2.}
    knees=touching&{'l_knee','r_knee'};hands=touching&{'l_palm','r_palm'}
    spine=joints[m['spine4']]-joints[m['hip']];vertical=float(spine[1]/max(np.linalg.norm(spine),1e-6))
    required=pose.get('bodyContacts',{}).get('requirements',{})
    ok=(len(knees)==2 if required.get('bothKnees') else bool(knees)) if support_kind=='kneel' else len(knees)==2 and len(hands)==2 and abs(vertical)<.7 if support_kind=='crawl' else len(touching&{'hip','spine4','head','l_elbow','r_elbow'})>=2 and abs(vertical)<.4 if support_kind=='lying' else len(hands)==2 and vertical<-.4 if support_kind=='inverted' else False
    if support_kind=='lying' and required.get('facing'):
        front=frames[m['spine4']]@np.array([0.,0.,1.]);sign=1 if required['facing']=='supine' else -1
        ok=ok and front[1]*sign>=.5
    if support_kind in ('crawl','inverted'):
        from studio import rest_frame
        ok=ok and all((frames[m[s+'_hand']]@rest_frame(pose['rig'],s+'_hand',m)[:,2])[1]<-.5 for s in ('l','r'))
    if support_kind=='kneel' and required.get('kneeSide'):ok=ok and required['kneeSide']+'_knee' in touching
    feet={**({'l':'flat','r':'flat'} if required.get('flatFeet') else {}),**required.get('feet',{})}
    for side,state in feet.items():
        sole=[points[side+'_'+part] for part in ('heel','bigtoe','smalltoe')]
        ok=ok and (min(sole)>.5 if state=='air' else abs(sole[0])<=2. if state=='heel' else max(map(abs,sole[1:]))<=2. if state=='toe' else max(map(abs,sole))<=2.)
    if support_kind=='seated':
        thigh=[joints[m[s+'_shin']]-joints[m[s+'_thigh']] for s in ('l','r')]
        feet=all(any(s+'_'+p in touching for p in ('heel','bigtoe','smalltoe')) for s in ('l','r'))
        ok=vertical>.5 and any(abs(v[1])/max(np.linalg.norm(v),1e-6)<.6 for v in thigh) and feet
        if required.get('flatFeet'):
            ok=ok and all(s+'_'+p in touching for s in ('l','r') for p in ('heel','bigtoe','smalltoe'))
            ok=ok and all(joints[m[s+'_shin']][1]-joints[m[s+'_foot']][1]>.5*np.linalg.norm(joints[m[s+'_shin']]-joints[m[s+'_foot']]) for s in ('l','r'))
        # An implied seat is metadata, not invented scene furniture.
        pose['bodyContacts']['impliedSeatHeightCm']=float(joints[m['hip']][1]-8*radius)
    if not ok:raise ValueError('This snapshot cannot satisfy the requested '+support_kind+' support within 2 cm. Another snapshot is needed.')
    pose['bodyContacts']['floorContacts']=sorted(touching)
    pose['bodyContacts']['residualCm']=max((abs(points[n]) for n in touching),default=0.)
