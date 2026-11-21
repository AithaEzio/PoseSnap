"""Coupled text contacts using rigid palm attachments and conservative capsules."""
import copy
import re
import numpy as np
from scipy.optimize import least_squares
from scipy.sparse import lil_matrix
from studio import semantics
from measurements import target_points
from interaction import closest, segment_distance
from coupled import fitting_rig
from textpose import aim, root_rotation
from textconstraints import contact_owners
from contact_geometry import radii as proxy_radii,torso,attachment,palm_normal,measure


def interaction(poses, kind, progress, prompt='', hand_shapes=True):
    if len(poses) != 2: raise ValueError('Interaction fitting needs two actors.')
    result = copy.deepcopy(poses)
    full_rigs=[p['rig'] for p in result]
    for pose in result:pose['rig']=fitting_rig(pose['rig'])
    radii=proxy_radii(poses)
    mappings=[semantics(p['rig']) for p in result]
    widths=[]
    for pose,mapping in zip(result,mappings):
        nodes={n['id']:n for n in pose['rig']['nodes']}
        widths.append(np.linalg.norm(np.asarray(nodes[mapping['l_upperarm']]['center'])-nodes[mapping['r_upperarm']]['center']))
    lateral=1.35*sum(widths)/2 if kind=='handhold' else sum(radii)+5
    # A pinned partner anchors the scene, not just its own initializer. Resetting
    # the unpinned actor here can discard an already feasible accepted layout.
    warm=any(p.get('pins') for p in result) or all(p.get('textContacts',{}).get('kind')==kind for p in result)
    if not warm and kind in ('front_hug','shoulder'):
        for i,p in enumerate(result):
            if not p.get('pins'):
                p['translation'][0]=0.;p['translation'][2]=(i-.5)*sum(radii)*1.9;root_rotation(p,[p['rootRotation'][0],180.*i,p['rootRotation'][2]])
    elif not warm:
        for i,p in enumerate(result):
            if not p.get('pins'):
                p['translation'][0]=(i-.5)*lateral;p['translation'][2]=0.;root_rotation(p,[p['rootRotation'][0],0.,p['rootRotation'][2]])
    leader=0;hand='l';shoulder='r'
    owners=contact_owners(prompt);subject=owners[0] if owners else None
    if subject:
        leader=next(i for i,p in enumerate(result) if p['personId']==int(subject[1]))
        if subject[2]:hand=subject[2][0].lower()
    target=re.search(r"\bon\s+(?:the\s+)?(?:(?:person|actor) [12](?:['’]s)?\s+)?(left|right) shoulder\b",prompt,re.I)
    if target:shoulder=target[1][0].lower()
    partner=1-leader
    contacts=[(0,'l_palm',1,'r_palm')] if kind=='handhold' else [(leader,hand+'_palm',partner,shoulder+'_shoulder')] if kind=='shoulder' else [(0,'l_palm',1,'back'),(1,'l_palm',0,'back')]
    if kind=='side_hug':contacts=[(leader,hand+'_palm',partner,'back')]
    bindings=[dict(actor=result[a]['personId'],part=h,partner=result[b]['personId'],target=p) for a,h,b,p in contacts]
    warm_arms=all(p.get('textContacts',{}).get('kind')==kind and p['textContacts'].get('attachments')==bindings for p in result)
    from hand_design import apply as shape_hand
    grip_hands={(i,p[0]) for i,p,_,_ in contacts}
    if kind=='handhold':grip_hands.add((1,'r'))
    for actor,side in grip_hands:
        if hand_shapes and not any(g['part'].startswith(side+'_') for g in result[actor].get('handGoals',[])):
            shape_hand(result[actor],dict(part=side+'_hand',movement='cupped' if kind=='handhold' else 'relaxed',amount=1.))
    if not warm_arms and kind=='handhold':
        for actor,side in grip_hands:
            sign=1 if side=='l' else -1
            aim(result[actor],side+'_upperarm',[sign*.35,-1.,.1]);aim(result[actor],side+'_forearm',[sign*.1,-1.,.1])
    elif not warm_arms:
        for actor,hand,_,_ in contacts:
            sign=1 if actor==0 else -1
            aim(result[actor],hand[0]+'_upperarm',[sign*.5,-.4,sign*.8]);aim(result[actor],hand[0]+'_forearm',[sign*.1,.5,sign*.8])
    variables,lower,upper,initial=[],[],[],[]
    involved={(i,part[0]) for i,part,_,_ in contacts}
    if kind=='handhold':involved.add((1,'r'))
    for actor,pose in enumerate(result):
        for axis in (0,2):variables.append((actor,None,axis));initial.append(pose['translation'][axis]);lower.append(initial[-1]-30);upper.append(initial[-1]+30)
        for node in pose['rig']['nodes']:
            name=node['id'];side='l' if name.startswith('l') else 'r' if name.startswith('r') else ''
            if name not in pose['rotations'] or (actor,side) not in involved or not any(s in name.lower() for s in ('shldr','upperarm','forearm','collar','shoulder','hand')):continue
            for axis,key in enumerate('xyz'):
                limit=node['limits'].get(key,{})
                if limit.get('locked') or key in node.get('driven',[]):continue
                lo=limit.get('min',-180) if limit.get('clamped') else -180;hi=limit.get('max',180) if limit.get('clamped') else 180
                if hi-lo<1e-5:continue
                variables.append((actor,name,axis));initial.append(float(np.clip(pose['rotations'][name][axis],lo,hi)));lower.append(lo);upper.append(hi)
    initial=np.asarray(initial)
    frames=[]
    def candidate(values):
        nonlocal frames
        for (actor,name,axis),value in zip(variables,values):(result[actor]['translation'] if name is None else result[actor]['rotations'][name])[axis]=float(value)
        state=[target_points(p,include_frames=True) for p in result];frames=[s[2][0] for s in state]
        return [s[0] for s in state]
    def goal(points,part,person):
        return attachment(points,part,frames[person],mappings[person],radii[person])
    normal=palm_normal
    def residual(values):
        points=candidate(values);errors=[]
        for actor,hand,partner,part in contacts:
            target=goal(points[partner],part,partner);errors.extend((points[actor][hand]-target)/.5)
            direction=-normal(points[partner],part) if part.endswith('palm') else points[partner]['torso']-target
            cosine=normal(points[actor],hand)@direction/max(np.linalg.norm(direction),1e-9);errors.append((1-cosine)*3)
        hip0,chest0=torso(points[0]);hip1,chest1=torso(points[1]);errors.append(max(0.,sum(radii)*.9-segment_distance(hip0,chest0,hip1,chest1))*2)
        if kind=='side_hug':
            # Fit the same beside-the-partner bounds checked below, including
            # anchored scenes. Pins cannot make an unmeasured layout acceptable.
            errors.extend([max(0.,abs(hip1[2]-hip0[2])-3.5)*4.,max(0.,np.linalg.norm((hip1-hip0)[[0,2]])-lateral*1.25)*4.])
        if kind in ('handhold','side_hug') and not any(p.get('pins') for p in result):
            errors.extend([(hip1[2]-hip0[2])/1.5,((hip1[0]-hip0[0])-lateral)/3.])
            if kind=='handhold':
                scale=sum(radii)/22.;target=(hip0+hip1)/2+np.array([0.,-8.,7.])*scale
                errors.extend(((points[0]['l_palm']+points[1]['r_palm'])/2-target)/2.)
        # Intended palms may touch the partner. Other forearms must stay outside
        # the conservative torso proxy; no custom DAZ mesh is assumed here.
        for actor,side in sorted(involved):
            other=1-actor;other_hip,other_chest=torso(points[other]);p=points[actor]
            for part in ('elbow','wrist'):
                point=p[side+'_'+part];errors.append(max(0.,radii[other]*.75-np.linalg.norm(point-closest(point,other_hip,other_chest))))
            for start,end in (('shoulder','elbow'),('elbow','wrist')):
                errors.append(max(0.,radii[other]*.65-segment_distance(p[side+'_'+start],p[side+'_'+end],other_hip,other_chest)))
        from textpose import frame
        from scipy.spatial.transform import Rotation
        for pose in result:
            if not pose.get('pins'):continue
            frames,joints=frame(pose)
            for name,pin in pose['pins'].items():
                if 'position' in pin:errors.extend((joints[name]-pin['position'])/.025)
                if 'rotation' in pin:errors.extend(Rotation.from_matrix(frames[name]@Rotation.from_quat(pin['rotation']).as_matrix().T).as_rotvec()/np.deg2rad(.05))
        errors.extend((values-initial)/80*.2)
        return np.asarray(errors)
    progress('Fitting partner contacts and palm direction',80)
    # Contact/penetration rows couple the pair; priors are diagonal. Supplying
    # this pattern avoids treating every prior as dependent on every joint.
    count=len(residual(initial));pattern=lil_matrix((count,len(initial)),dtype=int);core=count-len(initial);pattern[:core,:]=1
    for i in range(len(initial)):pattern[core+i,i]=1
    calls=0
    def checked(values):
        nonlocal calls
        calls+=1
        if calls%20==0:progress('Fitting partner contacts and palm direction',85)
        return residual(values)
    fit=least_squares(checked,initial,bounds=(lower,upper),jac_sparsity=pattern.tocsr(),max_nfev=100,ftol=1e-5)
    points=candidate(fit.x)
    gaps=[float(np.linalg.norm(points[i][hand]-goal(points[j],part,j))) for i,hand,j,part in contacts]
    hip0,chest0=torso(points[0]);hip1,chest1=torso(points[1]);penetration=max(0.,sum(radii)*.9-segment_distance(hip0,chest0,hip1,chest1))
    if max(gaps)>2 or penetration>2:raise ValueError('This interaction could not satisfy contact and torso clearance within 2 cm. The accepted result is kept. Try another posture or adjust it in Pose Studio.')
    for actor,side in sorted(involved):
        other_hip,other_chest=torso(points[1-actor]);p=points[actor]
        if any(radii[1-actor]*.65-segment_distance(p[side+'_'+start],p[side+'_'+end],other_hip,other_chest)>2. for start,end in (('shoulder','elbow'),('elbow','wrist'))):raise ValueError('An arm crosses the partner’s torso proxy. Another composition is needed; the accepted result is kept.')
    if kind=='handhold':
        if normal(points[0],'l_palm')@normal(points[1],'r_palm')>-.75:raise ValueError('The clasped palms cannot face each other within the captured rig limits. The accepted result is kept.')
        if not any(p.get('pins') for p in result) and abs(hip1[2]-hip0[2])>5.:raise ValueError('This handholding composition could not keep the partners beside each other. The accepted result is kept.')
    if kind=='side_hug' and (np.linalg.norm((hip1-hip0)[[0,2]])>lateral*1.4 or abs(hip1[2]-hip0[2])>5.):raise ValueError('This side-hug proposal leaves the partners too far apart. Another composition is needed; the accepted result is kept.')
    for i,pose in enumerate(result):
        pose['rig']=full_rigs[i]
    final=measure(result,contacts)
    if max(final['gapsCm'])>2. or final['torsoPenetrationCm']>2.:
        raise ValueError('The final captured rigs do not satisfy the contact proxies within 2 cm. Your accepted scene is kept.')
    for i,pose in enumerate(result):
        from textpose import protected
        protected(poses[i],pose,[])
        pose['textContacts']=dict(final,kind=kind,attachments=[dict(actor=result[a]['personId'],part=h,partner=result[b]['personId'],target=p) for a,h,b,p in contacts])
        pose['warnings'].append('Partner contacts use rigid palm attachments and conservative torso proxies. Custom character surfaces may need adjustment in Pose Studio.')
    return result
