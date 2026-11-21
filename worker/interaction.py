"""Bounded shared-camera coordination using target skeletons, never Genesis meshes.

Capsules are conservative pose proxies, not the surface of a morphed DAZ figure.
No interaction prior/model is downloaded. Each source must already be extracted.
"""
import copy, hashlib, json
import numpy as np
from scipy.optimize import least_squares
from retarget import fk, retarget, source_map
from rigs import profile
from instances import cached_source
from storage import image_dir, read_json, atomic_json, bind_people

AXES=np.array([1.,-1.,-1.])
TARGET={5:('lShldrBend','l_upperarm'),6:('rShldrBend','r_upperarm'),7:('lForearmBend','l_forearm'),8:('rForearmBend','r_forearm'),9:('lHand','l_hand'),10:('rHand','r_hand'),11:('lThighBend','l_thigh'),12:('rThighBend','r_thigh'),13:('lShin','l_shin'),14:('rShin','r_shin'),15:('lFoot','l_foot'),16:('rFoot','r_foot')}

def target_id(pose,coco):
    ids={n['id'] for n in pose['rig']['nodes']}
    return next((n for n in TARGET.get(coco,()) if n in ids),None)

def camera_translation(value):
    value=np.asarray(value,dtype=float)
    if value.shape!=(3,) or not np.isfinite(value).all() or value[2]<=0:raise ValueError('Invalid shared camera translation. Extract the participants again.')
    return value*AXES*100

def projected(points,focal,size):
    camera=np.asarray(points)*AXES
    depth=np.maximum(camera[...,2],1.)
    return camera[...,:2]/depth[...,None]*focal+np.asarray(size)/2

def closest(point,a,b):
    delta=b-a
    return a+delta*np.clip(np.dot(point-a,delta)/max(np.dot(delta,delta),1e-9),0,1)

def segment_distance(a,b,c,d):
    """Closest distance of finite capsules' axes, including parallel segments."""
    u=b-a;v=d-c;w=a-c
    aa=u@u;bb=u@v;cc=v@v;dd=u@w;ee=v@w;den=aa*cc-bb*bb
    s=np.clip((bb*ee-cc*dd)/den,0,1) if den>1e-9 else 0.
    t=np.clip((bb*s+ee)/max(cc,1e-9),0,1)
    s=np.clip((bb*t-dd)/max(aa,1e-9),0,1)
    t=np.clip((bb*s+ee)/max(cc,1e-9),0,1)
    return float(np.linalg.norm((a+s*u)-(c+t*v)))


def segment_distances(a,b,c,d):
    """Broadcast the same finite-segment calculation for fitting proxy pairs."""
    u=b-a;v=d-c;w=a-c
    dot=lambda x,y:np.sum(x*y,axis=-1)
    aa=dot(u,u);bb=dot(u,v);cc=dot(v,v);dd=dot(u,w);ee=dot(v,w);den=aa*cc-bb*bb
    s=np.clip(np.divide(bb*ee-cc*dd,den,out=np.zeros_like(den),where=den>1e-9),0,1)
    t=np.clip((bb*s+ee)/np.maximum(cc,1e-9),0,1)
    s=np.clip((bb*t-dd)/np.maximum(aa,1e-9),0,1)
    t=np.clip((bb*s+ee)/np.maximum(cc,1e-9),0,1)
    return np.linalg.norm((a+s[...,None]*u)-(c+t[...,None]*v),axis=-1)

def geometry(pose,frames=None,include_dependencies=False):
    channels=dict(pose['rotations']);root=next(n['id'] for n in pose['rig']['nodes'] if not n['parent']);channels[root]=pose.get('rootRotation',[0,0,0])
    world,positions=frames if frames is not None else fk(pose['rig'],channels);ids=set(positions)
    lower=next((n for n in ('hip','pelvis') if n in ids),None)
    upper=next((n for n in ('chestUpper','spine4','chestLower','spine3') if n in ids),None)
    if not lower or not upper:raise ValueError('This rig lacks supported torso geometry. Refresh its connection.')
    rest=np.array([n['center'] for n in pose['rig']['nodes'] if n['type']=='bone'])
    height=max(100.,float(np.ptp(rest[:,1])))
    radius=height*.065
    capsules=[(positions[lower],positions[upper],radius,'torso')];dependencies=[(lower,upper)]
    for start,end,r,label in ((5,7,.024,'arm'),(6,8,.024,'arm'),(7,9,.021,'arm'),(8,10,.021,'arm'),(11,13,.038,'leg'),(12,14,.038,'leg'),(13,15,.028,'leg'),(14,16,.028,'leg')):
        a,b=target_id(pose,start),target_id(pose,end)
        if a and b:
            capsules.append((positions[a],positions[b],height*r,label));dependencies.append((a,b))
    from cropped import visible_capsules
    visible=visible_capsules(pose,positions,capsules)
    if include_dependencies:
        kept={id(c) for c in visible}
        return positions,visible,height,[d for c,d in zip(capsules,dependencies) if id(c) in kept]
    return positions,visible,height

def source_contacts(sources,poses,positions):
    contacts=[]
    for i,source in enumerate(sources):
        observed={p['coco']:p for p in source.get('contactEvidence',source['evidence'])}
        ownmap=source_map(source['names']);ownpoints=np.asarray(source['positions'])+np.asarray(source['cameraTranslation'])*AXES
        h=max(24.,np.ptp(np.array([p['xy'] for p in source['evidence']])[:,1]))
        for wrist,semantic in ((9,'lHand'),(10,'rHand')):
            if wrist not in observed or semantic not in ownmap:continue
            own=ownpoints[ownmap[semantic]]
            for j,other in enumerate(sources):
                if i==j:continue
                othermap=source_map(other['names']);otherpoints=np.asarray(other['positions'])+np.asarray(other['cameraTranslation'])*AXES
                if 'hip' not in othermap or 'chestUpper' not in othermap:continue
                a,b=otherpoints[othermap['hip']],otherpoints[othermap['chestUpper']]
                distance=float(np.linalg.norm(own-closest(own,a,b)))
                # 2D proximity alone does not establish contact across depths.
                other2d={p['coco']:p['xy'] for p in other.get('contactEvidence',other['evidence'])}
                if not all(k in other2d for k in (5,6,11,12)):continue
                bottom=np.mean([other2d[11],other2d[12]],axis=0);top=np.mean([other2d[5],other2d[6]],axis=0)
                image_distance=np.linalg.norm(np.array(observed[wrist]['xy'])-closest(np.array(observed[wrist]['xy']),bottom,top))
                width=np.linalg.norm(np.array(other2d[5])-other2d[6])
                if distance<=.25 and image_distance<=max(width*.6,h*.045):
                    node=target_id(poses[i],wrist)
                    if node:
                        # A wrist absent from the visible mask is only a weak
                        # contact cue, even when its detector score is high.
                        visible=any(p['coco']==wrist for p in source['evidence'])
                        contacts.append(dict(person=i,other=j,wrist=wrist,node=node,weight=observed[wrist]['weight']*(1 if visible else .3)))
    return contacts

def coordinate(sources,poses,fit_arms=True):
    if not 2<=len(sources)<=4 or len(poses)!=len(sources):raise ValueError('Choose between two and four distinct people.')
    required=('camera','cameraTranslation','imageSize','focalLength','evidence','positions','restPositions','names','personKey')
    if any(any(key not in s for key in required) for s in sources):raise ValueError('These extractions lack shared-camera metadata. Extract the participants again.')
    first=sources[0]
    if any(s['imageId']!=first['imageId'] or s['imageSize']!=first['imageSize'] or not np.allclose(s['camera'],first['camera'],atol=.001) for s in sources):raise ValueError('Participants must use the same reference camera. Extract them again.')
    poses=copy.deepcopy(poses);info=[geometry(p) for p in poses]
    source_heights=[np.ptp(np.asarray(s['restPositions'])[:,1])*100 for s in sources]
    scale=float(np.median([item[2]/max(60.,height) for item,height in zip(info,source_heights)]))
    initial=[]
    for source,pose,(positions,capsules,height) in zip(sources,poses,info):
        mapping=source_map(source['names']);target_hip='hip' if 'hip' in positions else 'pelvis'
        source_hip=np.asarray(source['positions'][mapping['hip']])*100*scale
        initial.append(camera_translation(source['cameraTranslation'])*scale+source_hip-positions[target_hip])
    initial=np.array(initial);contacts=source_contacts(sources,poses,[v[0] for v in info])
    observations=[]
    for i,(source,pose) in enumerate(zip(sources,poses)):
        for evidence in source['evidence']:
            node=target_id(pose,evidence['coco'])
            if node:observations.append((i,node,evidence))
    if any(sum(o[0]==i for o in observations)<4 for i in range(len(sources))):raise ValueError('Interaction needs at least four reliable visible body joints per person. Try a clearer reference.')
    def penetration(translations):
        values=[]
        for i in range(len(poses)):
            for j in range(i+1,len(poses)):
                for a,b,r,label in info[i][1]:
                    for c,d,q,otherlabel in info[j][1]:
                        # Slight proxy intersection is allowed for soft tissue contact.
                        values.append(max(0.,(r+q)*.82-segment_distance(a+translations[i],b+translations[i],c+translations[j],d+translations[j])))
        return values
    def residual(values):
        shifts=values.reshape(-1,3);translations=initial+shifts;result=[]
        for i,node,evidence in observations:
            predicted=projected(info[i][0][node]+translations[i],sources[i]['focalLength'],sources[i]['imageSize'])
            height=max(24.,np.ptp(np.array([p['xy'] for p in sources[i]['evidence']])[:,1]))
            result.extend((predicted-evidence['xy'])/height*12*np.sqrt(evidence['weight']))
        result.extend((shifts/40*.55).ravel())
        for contact in contacts:
            i,j=contact['person'],contact['other'];wrist=info[i][0][contact['node']]+translations[i]
            a,b,r,_=info[j][1][0];distance=np.linalg.norm(wrist-closest(wrist,a+translations[j],b+translations[j]))
            result.append((distance-(r+info[i][2]*.019))/15*contact['weight'])
        result.extend(np.array(penetration(translations))/4)
        return np.asarray(result)
    before=float(np.linalg.norm(residual(np.zeros(len(poses)*3))));initial_overlap=float(max(penetration(initial),default=0.))
    fit=least_squares(residual,np.zeros(len(poses)*3),bounds=(-35,35),max_nfev=45,ftol=1e-5,xtol=1e-5,gtol=1e-5)
    translations=initial+fit.x.reshape(-1,3)
    # Bounded arm IK preserves probable wrist contact across different target sizes.
    adjustments=0
    for contact in contacts if fit_arms else []:
        i,j=contact['person'],contact['other'];pose=poses[i];wrist=contact['wrist']
        a,b,r,_=info[j][1][0];own=info[i][0][contact['node']]+translations[i]
        surface=closest(own,a+translations[j],b+translations[j]);normal=own-surface
        if np.linalg.norm(normal)<1e-6:continue
        goal=surface+normal/np.linalg.norm(normal)*(r+info[i][2]*.019)
        variables=[];lo=[];hi=[];base=[]
        nodes={n['id']:n for n in pose['rig']['nodes']}
        for coco in ((5,7) if wrist==9 else (6,8)):
            node=target_id(pose,coco)
            if not node:continue
            for axis in range(3):
                limit=nodes[node]['limits'].get('xyz'[axis],{})
                if limit.get('locked') or 'xyz'[axis] in nodes[node].get('driven',[]):continue
                value=pose['rotations'].get(node,[0,0,0])[axis]
                lower=max(value-12,limit.get('min',-360) if limit.get('clamped') else -360)
                upper=min(value+12,limit.get('max',360) if limit.get('clamped') else 360)
                if upper-lower<1e-5:continue
                variables.append((node,axis));base.append(value);lo.append(lower);hi.append(upper)
        if not variables:continue
        def candidate(values):
            channels={k:list(v) for k,v in pose['rotations'].items()}
            for (node,axis),value in zip(variables,values):channels[node][axis]=float(value)
            return channels,fk(pose['rig'],channels)[1]
        def arm_residual(values):
            channels,positions=candidate(values);result=list((positions[contact['node']]+translations[i]-goal)/8)
            for k,node,evidence in observations:
                if k!=i or evidence['coco'] not in ((5,7,9) if wrist==9 else (6,8,10)):continue
                predicted=projected(positions[node]+translations[i],sources[i]['focalLength'],sources[i]['imageSize'])
                result.extend((predicted-evidence['xy'])/max(24.,sources[i]['imageSize'][1]) * 35)
            result.extend((np.asarray(values)-base)/12*.6)
            return result
        arm=least_squares(arm_residual,base,bounds=(lo,hi),max_nfev=20,ftol=1e-4)
        channels,positions=candidate(arm.x)
        # No accepted arm correction may worsen an observed landmark by >4% body height.
        acceptable=True
        for k,node,evidence in observations:
            if k!=i:continue
            old=projected(info[i][0][node]+translations[i],sources[i]['focalLength'],sources[i]['imageSize'])
            new=projected(positions[node]+translations[i],sources[i]['focalLength'],sources[i]['imageSize'])
            height=max(24.,np.ptp(np.array([p['xy'] for p in sources[i]['evidence']])[:,1]))
            if np.linalg.norm(new-evidence['xy'])>np.linalg.norm(old-evidence['xy'])+height*.04:acceptable=False
        if acceptable and np.linalg.norm(positions[contact['node']]+translations[i]-goal)<np.linalg.norm(own-goal):
            pose['rotations']=channels;info[i]=geometry(pose);adjustments+=1
    remaining=penetration(translations)
    center=np.mean(translations[:,[0,2]],axis=0)
    minimum=min(min((p+translations[i])[1] for p in item[0].values()) for i,item in enumerate(info))
    # Include visible foot endpoints for the common group floor.
    for i,pose in enumerate(poses):
        world,positions=fk(pose['rig'],pose['rotations'])
        for node in pose['rig']['nodes']:
            if node['id'].lower() in ('lfoot','rfoot','ltoe','rtoe','l_foot','r_foot','l_toes','r_toes'):
                end=positions[node['id']]+world[node['id']]@(np.asarray(node['end'])-node['center'])+translations[i]
                minimum=min(minimum,end[1])
    digest=hashlib.sha256(json.dumps([(s['personKey'],p['rigId']) for s,p in zip(sources,poses)]).encode()).hexdigest()[:24]
    warnings=['Reference layout estimates shared depth and uses skeleton collision proxies. Inspect contacts; custom Genesis morphs can change surface spacing.']
    maximum=float(max(remaining,default=0.))
    if maximum>4:warnings.append(f'Residual proxy overlap is {maximum:.1f} cm. The reference has uncertain depth or occluded anatomy; inspect the side view before applying.')
    from measurements import reference_camera
    origin=np.array([center[0],minimum,center[1]])
    camera=reference_camera(first,origin)
    for i,pose in enumerate(poses):
        pose['translation']=(translations[i]-[center[0],minimum,center[1]]).tolist()
        pose['referenceCamera']=camera
        pose['layout']=dict(version=1,id=digest,personIds=[s['personId'] for s in sources],reference=True)
        pose['warnings']=list(dict.fromkeys(pose['warnings']+warnings))
    return dict(version=1,id=digest,imageId=first['imageId'],poses=poses,warnings=warnings,referenceCamera=camera,
        diagnostics=dict(contacts=len(contacts),armAdjustments=adjustments,initialProxyOverlapCm=initial_overlap,maximumProxyOverlapCm=maximum,initialObjective=before,finalObjective=float(np.linalg.norm(fit.fun))))

def assemble(root,payload,progress):
    from time import perf_counter
    from cropped import prepare, enabled as crop_enabled, SIGNATURE as CROP_SIGNATURE
    started=perf_counter()
    from extraction import selected, result_path
    choice=selected(root,payload,interaction=True)
    members=payload.get('members',[])
    if not 2<=len(members)<=4 or len({m.get('personId') for m in members})!=len(members):raise ValueError('Choose two to four distinct participants.')
    folder=image_dir(root,payload['imageId']);people=read_json(folder/'people.json',[]);sources=[];poses=[];baseline_sources=[]
    from reference_guidance import AUTOMATIC_CUES_QUALIFIED, baseline_evidence, options as image_guidance_options
    image_guidance=image_guidance_options(root,payload)
    for member in members:
        person=next((p for p in people if p['id']==member['personId']),None)
        source=cached_source(folder,person,choice,context=member.get('sourceGuidance')) if person else None
        if not source:raise ValueError('Extract every chosen participant with the current model pipeline first.')
        if 'contactEvidence' not in source:
            from evidence import landmarks
            source=dict(source,contactEvidence=landmarks(person,[p for p in people if p['id']!=person['id']]))
        if image_guidance['imageGuidance']=='auto' and not AUTOMATIC_CUES_QUALIFIED and not source.get('referenceEvidence'):
            source=dict(source,referenceEvidence=baseline_evidence(image_guidance))
        baseline_sources.append(copy.deepcopy(source))
        source=prepare(root,source,payload,person)
        sources.append(source);poses.append(retarget(source,profile(root,member['rigId'])))
    progress('Coordinating the target figures and probable contacts',60)
    from cropped import adjust_accepted
    adjusted=adjust_accepted(root,folder,baseline_sources,sources,payload)
    if adjusted:
        from posture import persist_baseline
        persist_baseline(folder,baseline_sources,adjusted['poses'])
        atomic_json(result_path(folder,'interaction',choice),bind_people(adjusted,baseline_sources))
        progress('Cropped joints neutralized; visible interaction kept',100)
        return adjusted
    if choice=='pure':
        # Keep each SAM-retargeted limb exactly; only solve shared placement.
        result=coordinate(sources,poses,fit_arms=False)
        result['extractionMethod']=choice
        from posture import persist_baseline
        persist_baseline(folder,baseline_sources,result['poses'])
        progress('Saving Pure interaction placement',98)
        atomic_json(result_path(folder,'interaction',choice),bind_people(result,baseline_sources))
        return result
    from coupled import fit_targets, contact_graph
    from refinement import refine_sources
    from wholebody import resolve_ownership
    from measurements import canonical
    groups=resolve_ownership([canonical(s) for s in sources])
    sources=[dict(s,measurements=g) for s,g in zip(sources,groups)]
    from refinement import accepted_result
    previous=accepted_result(root,folder,sources=baseline_sources)
    if previous and any(p.get('cropPolicy',{}).get('enabled',False)!=crop_enabled(root,payload,sources[0]) or (p.get('cropPolicy',{}).get('enabled') and p['cropPolicy'].get('signature')!=CROP_SIGNATURE) for p in previous['poses']):previous=None
    if previous and set(s['personId'] for s in sources)==set(s['personId'] for s in previous['refinementSources']):
        saved={s['personId']:s for s in previous['refinementSources']}
        sources=[dict(saved[s['personId']],referenceEvidence=s.get('referenceEvidence')) for s in sources];poses=[retarget(s,profile(root,m['rigId'])) for s,m in zip(sources,members)]
        payload=dict(payload,contacts=payload.get('contacts',previous.get('contacts',[])),support=payload.get('support',previous.get('supportOverrides',[])))
    graph=contact_graph(sources,poses,payload.get('contacts',[]))
    refinement_started=perf_counter()
    if all(s.get('mhr') for s in sources):
        sources=refine_sources(root,sources,graph,progress,start=61,end=70)
        poses=[retarget(s,profile(root,m['rigId'])) for s,m in zip(sources,members)]
    source_seconds=perf_counter()-refinement_started
    target_started=perf_counter()
    result=fit_targets(sources,poses,payload.get('contacts',[]),payload.get('support',[]),progress,preserve=True)
    result['executionTimings']=dict(sourceRefinementSeconds=source_seconds,targetFitSeconds=perf_counter()-target_started,totalSeconds=perf_counter()-started)
    result['supportOverrides']=payload.get('support',[])
    from posture import persist_baseline
    persist_baseline(folder,baseline_sources,result['poses'])
    progress('Saving the coordinated target poses',98);atomic_json(folder/'interaction.json',bind_people(result,baseline_sources))
    progress('Interaction ready for inspection',100)
    return result
