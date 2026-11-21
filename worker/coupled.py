"""Shared-camera target fit with contact, support and bounded driving channels."""
import copy
import re
from time import perf_counter
import numpy as np
from scipy.optimize import least_squares
from scipy.sparse import lil_matrix
from measurements import canonical, target_points, project_target, reference_camera, quality, stamp
from retarget import source_map,rest_transforms
TARGET_FIT_VERSION=5

def regional_observations(observations,owner,region):
    parts=('shoulder','elbow','wrist') if region.endswith('arm') else ('hip','knee','ankle') if region.endswith('leg') else ()
    names={region[0]+'_'+part for part in parts}
    # Whole-body and specialist hand evidence both contain a wrist. The arm
    # check uses body observations once, rather than counting the hand wrist too.
    points=[p for i,p,_ in observations if i==owner and (p['region']=='body' and p['name'] in names if parts else p['region']==region)]
    # A lone shoulder/hip is a torso anchor, not evidence of its missing limb.
    # Torso/body guards still apply; accepted refinements also check each anchor.
    if parts and not any(p['name'] in {region[0]+'_'+part for part in parts[1:]} for p in points):return []
    return points

def bounded_fallback(base,proposal,placement,check,objective,refit):
    """Reduce failing chains, never the proposal's camera-space alignment.

    Every trial is checked as a complete FK pose. A single constrained refit
    can recover interacting chains; rejected trials never become new anchors.
    """
    failure=check(proposal)
    if failure is None:return proposal,None,'full'
    if not np.isfinite(proposal).all():return base,failure,'retained'
    columns=set(failure['columns'])-set(placement)
    if not columns:return base,failure,'retained'
    candidates=[]
    for fraction in (.75,.5,.25,.1,0.):
        trial=proposal.copy()
        selected=list(columns);trial[selected]=base[selected]+(proposal[selected]-base[selected])*fraction
        if check(trial) is None:candidates.append(trial)
    if not candidates and columns:
        trial=refit(columns)
        if trial is not None and check(trial) is None:candidates.append(trial)
    if not candidates:return base,failure,'retained'
    return min(candidates,key=objective),failure,'partial'

def fitting_rig(rig,extra=()):
    """Exclude facial nodes from repeated FK, retain every ERC dependency."""
    from studio import semantics
    nodes={n['id']:n for n in rig['nodes']};needed=set(semantics(rig).values())|set(extra)
    if not needed.issubset(nodes):raise ValueError('A pinned joint is missing from the target rig.')
    changed=True
    while changed:
        before=set(needed)
        for name in list(needed):
            parent=nodes[name]['parent']
            if parent in nodes:needed.add(parent)
        for formula in rig.get('formulas',[]):
            output=re.search(r'#([^?]+)',formula['output'])
            if output and output[1] in needed:
                for op in formula['operations']:
                    dependency=re.search(r'#([^?]+)',op.get('url',''))
                    if dependency and dependency[1] in nodes:needed.add(dependency[1])
        changed=before!=needed
    return dict(rig,nodes=[n for n in rig['nodes'] if n['id'] in needed],formulas=[f for f in rig.get('formulas',[]) if (re.search(r'#([^?]+)',f['output']) or [None,None])[1] in needed])

def dependency_chain(rig,node):
    """FK dependencies include ERC drivers outside the anatomical parent chain."""
    nodes={n['id']:n for n in rig['nodes']};needed=set();pending=[node]
    dependencies={}
    for formula in rig.get('formulas',[]):
        output=re.search(r'#([^?]+)',formula['output'])
        if output:
            dependencies.setdefault(output[1],set()).update(match[1] for op in formula['operations'] if (match:=re.search(r'#([^?]+)',op.get('url',''))))
    while pending:
        name=pending.pop()
        if name not in nodes or name in needed:continue
        needed.add(name);pending.append(nodes[name]['parent']);pending.extend(dependencies.get(name,()))
    return needed

def contact_graph(sources,poses,overrides=()):
    contacts=[];groups=[canonical(s) for s in sources]
    def observed(group,name):return next((p for p in group if p['name']==name and p.get('known',True)),None)
    for i,group in enumerate(groups):
        for side in ('l','r'):
            wrist=observed(group,side+'_wrist')
            if not wrist:continue
            palm=[p for p in group if p['region']==side+'_hand' and p.get('known',True) and p['name'].endswith('1')]
            xy=np.mean([p['xy'] for p in palm],axis=0) if palm else np.asarray(wrist['xy'])
            for j,other in enumerate(groups):
                if i==j:continue
                shoulders=[observed(other,s+'_shoulder') for s in ('l','r')];hips=[observed(other,s+'_hip') for s in ('l','r')]
                if any(p is None for p in shoulders+hips):continue
                top=np.mean([p['xy'] for p in shoulders],axis=0);bottom=np.mean([p['xy'] for p in hips],axis=0);axis=top-bottom
                t=float(np.clip((xy-bottom)@axis/max(axis@axis,1),0,1));on=bottom+axis*t
                width=max(np.linalg.norm(np.asarray(shoulders[0]['xy'])-shoulders[1]['xy']),np.linalg.norm(np.asarray(hips[0]['xy'])-hips[1]['xy']))
                distance=min(np.linalg.norm(xy-on),np.linalg.norm(np.asarray(wrist['xy'])-on),*(np.linalg.norm(xy-p['xy']) for p in shoulders))
                body_height=max(24.,sources[j].get('personBox',[0,0,0,sources[j]['imageSize'][1]])[3]-sources[j].get('personBox',[0,0,0,0])[1])
                if distance<max(width*.9,body_height*.085):
                    region='shoulder' if t>.78 else 'waist' if t<.32 else 'torso'
                    import cv2
                    polygon=cv2.convexHull(np.array([p['xy'] for p in shoulders+hips],np.float32))
                    in_partner=cv2.pointPolygonTest(polygon,tuple(map(float,wrist['xy'])),False)>0
                    target_side=('l','r')[int(np.argmin([np.linalg.norm(xy-p['xy']) for p in shoulders]))]
                    contacts.append(dict(id=f"{poses[i]['personId']}:{side}_palm:{poses[j]['personId']}:{region}",personId=poses[i]['personId'],otherId=poses[j]['personId'],part=side+'_palm',region=region,imagePoint=xy.tolist(),targetSide=target_side if region=='shoulder' else None,confidence=float(wrist['weight'])*(.8 if palm else .45),confirmed=False,enabled=True,occlusion='front' if in_partner and wrist.get('visibleInMask') else 'unknown'))
                    elbow=observed(group,side+'_elbow')
                    if elbow and np.linalg.norm(np.asarray(elbow['xy'])-on)<max(width,body_height*.1):
                        contacts.append(dict(id=f"{poses[i]['personId']}:{side}_forearm:{poses[j]['personId']}:torso",personId=poses[i]['personId'],otherId=poses[j]['personId'],part=side+'_forearm',region='torso',imagePoint=((np.asarray(wrist['xy'])+elbow['xy'])/2).tolist(),confidence=float(wrist['weight'])*.3,confirmed=False,enabled=True))
                for other_side in ('l','r'):
                    hand=observed(other,other_side+'_wrist')
                    if hand and np.linalg.norm(xy-hand['xy'])<max(10.,np.linalg.norm(axis)*.06):
                        contacts.append(dict(id=f"{poses[i]['personId']}:{side}_palm:{poses[j]['personId']}:{other_side}_palm",personId=poses[i]['personId'],otherId=poses[j]['personId'],part=side+'_palm',region=other_side+'_palm',confidence=float(min(wrist['weight'],hand['weight']))*.75,confirmed=False,enabled=True))
    # Torso overlap is weak evidence, only combined with a visible limb contact.
    import cv2
    for i in range(len(groups)):
        for j in range(i):
            if not any({c['personId'],c['otherId']}=={poses[i]['personId'],poses[j]['personId']} for c in contacts):continue
            bodies=[[observed(groups[k],side+'_'+part) for side in ('l','r') for part in ('shoulder','hip')] for k in (i,j)]
            if any(any(p is None for p in body) for body in bodies):continue
            polygons=[cv2.convexHull(np.array([p['xy'] for p in body],np.float32)) for body in bodies]
            areas=[cv2.contourArea(p) for p in polygons];intersection,_=cv2.intersectConvexConvex(*polygons)
            if min(areas)>1 and intersection/min(areas)>.35:
                contacts.append(dict(id=f"{poses[i]['personId']}:torso:{poses[j]['personId']}:torso",personId=poses[i]['personId'],otherId=poses[j]['personId'],part='torso',region='torso',confidence=.2,confirmed=False,enabled=True))
    ids={p['personId'] for p in poses}
    if not isinstance(overrides,(list,tuple)) or len(overrides)>64:raise ValueError('Too many contact corrections.')
    for item in overrides:
        if item.get('personId') not in ids or item.get('otherId') not in ids or item['personId']==item['otherId'] or item.get('part') not in ('l_palm','r_palm','l_forearm','r_forearm','torso') or item.get('region') not in ('torso','shoulder','back','waist','l_palm','r_palm'):
            raise ValueError('Invalid interaction contact. Choose a hand and another participant’s body region.')
        if item.get('targetSide') not in ('l','r',None):raise ValueError('Choose the partner’s left or right shoulder.')
        ident=item.get('id') or f"{item['personId']}:{item['part']}:{item['otherId']}:{item['region']}"
        contacts=[p for p in contacts if p['id']!=ident]
        confirmed=item.get('confirmed',False) is True
        confidence=1. if confirmed else float(np.clip(item.get('confidence',.4),0,1))
        if not np.isfinite(confidence):raise ValueError('Contact confidence must be finite.')
        contacts.append(dict(item,id=ident,confidence=confidence,confirmed=confirmed,enabled=item.get('enabled',True)))
    return contacts

def fit_targets(sources,poses,contacts=(),support=(),progress=lambda *_:None,warm_start=False,anchors=None,guidance=(),preserve=False):
    """Use canonical solver ordering; return actors in the caller's order."""
    if len(sources)!=len(poses) or not 1<=len(poses)<=4:raise ValueError('Select one to four extracted people.')
    ids=[p['personId'] for p in poses]
    if len(set(ids))!=len(ids) or any(s['personId']!=p['personId'] for s,p in zip(sources,poses)):raise ValueError('The fitting sources and target participants do not match.')
    order=sorted(range(len(ids)),key=lambda i:ids[i])
    if anchors is not None and len(anchors)!=len(poses):raise ValueError('The posture anchors do not match the participants.')
    result=_fit_targets([sources[i] for i in order],[poses[i] for i in order],contacts,support,progress,warm_start,[anchors[i] for i in order] if anchors is not None else None,guidance,preserve)
    by_id={p['personId']:p for p in result['poses']};result['poses']=[by_id[i] for i in ids]
    return result


def _fit_targets(sources,poses,contacts=(),support=(),progress=lambda *_:None,warm_start=False,anchors=None,guidance=(),preserve=False):
    from interaction import geometry, camera_translation, closest, segment_distance, segment_distances
    from posture import core_frame,drift,infer_support,guidance_options,context_key,POLICY_VERSION
    from studio import semantics
    from scipy.spatial.transform import Rotation
    if not 1<=len(sources)<=4 or len(sources)!=len(poses):raise ValueError('Select one to four extracted people.')
    if any(s['imageId']!=sources[0]['imageId'] or not np.allclose(s['camera'],sources[0]['camera'],atol=.001) for s in sources):raise ValueError('Use participants from the same reference camera.')
    poses=copy.deepcopy(poses)
    from cropped import annotate,zero_nodes
    for source,pose in zip(sources,poses):
        if source.get('cropPolicy') is not None:
            effective=copy.deepcopy(source)
            protected=set().union(*(dependency_chain(pose['rig'],node) for node in pose.get('pins',{})))
            effective['cropPolicy']['zeroSemantics']=[key for key in effective['cropPolicy'].get('zeroSemantics',[]) if not zero_nodes(dict(cropPolicy=dict(enabled=True,zeroSemantics=[key])),pose['rig'])&protected]
            annotate(effective,pose,zero_nodes(effective,pose['rig']))
            if effective['cropPolicy']['zeroSemantics']!=source['cropPolicy'].get('zeroSemantics',[]):pose['warnings'].append('Pinned joints and their parent chains were kept; conflicting cropped channels remain editable.')
    originals=copy.deepcopy(poses);anchors=copy.deepcopy(anchors if anchors is not None else poses)
    # First alignment adapts the Genesis proportions to the reference. Later
    # refinement protects an already accepted placement and limb pose.
    initial_alignment=preserve and not warm_start
    preferences=guidance_options(list(guidance),poses)
    original_rigs=[p['rig'] for p in poses]
    poses=[dict(copy.deepcopy(p),rig=fitting_rig(p['rig'],p.get('pins',{}))) for p in poses];info=[geometry(p) for p in poses];initial=[]
    scale=float(np.median([g[2]/max(60.,np.ptp(np.asarray(s['restPositions'])[:,1])*100) for s,g in zip(sources,info)]))
    for source,pose,g in zip(sources,poses,info):
        root=np.asarray(source['positions'][source_map(source['names'])['hip']])*100*scale
        if warm_start:
            saved=pose.get('referenceCamera')
            if not saved or saved['imageSize']!=source['imageSize'] or not np.allclose(saved['intrinsics'],source['camera'],atol=.001):raise ValueError('The previous layout uses another reference camera. Extract again before refining.')
            position=np.asarray(pose['translation'])+np.asarray(saved['originCm'])
            if position.shape!=(3,) or not np.isfinite(position).all():raise ValueError('Invalid saved target placement.')
            initial.append(position)
        else:initial.append(camera_translation(source['cameraTranslation'])*scale+root-g[0]['hip' if 'hip' in g[0] else 'pelvis'])
    initial=np.array(initial);camera=reference_camera(sources[0],[0,0,0])
    graph=contact_graph(sources,poses,contacts) if len(poses)>1 else []
    index={p['personId']:i for i,p in enumerate(poses)};supports={}
    for item in support:
        if item.get('personId') not in index or item.get('side') not in ('l','r') or item.get('state') not in ('heel','toe','flat','air'):raise ValueError('Invalid foot support.')
        supports[item['personId'],item['side']]=item['state']
    inferred={}
    # A lifted foot is not a raised heel. Infer support before any floor fit.
    for source,pose in zip(sources,poses):
        detected=infer_support(source,originals[index[pose['personId']]],warm_start)
        for side in ('l','r'):
            key=(pose['personId'],side);inferred[key]=detected[side]
            if side+'_foot' in source.get('cropPolicy',{}).get('zeroSemantics',[]):
                inferred[key]=dict(state='unknown',reason='Foot is cropped out of the original image; no automatic floor support.')
                detected[side]=inferred[key]
            supports.setdefault(key,detected[side]['state'])
    variables=[];base=[];lower=[];upper=[];observations=[];chains=[]
    for i,(source,pose) in enumerate(zip(sources,poses)):
        pose['translation']=initial[i].tolist();pose.setdefault('rootRotation',[0.,0.,0.]);actual,deps=target_points(pose)
        chains.append({name:dependency_chain(pose['rig'],node) for name,node in deps.items()})
        for point in canonical(source):
            if point.get('known',True) and point['name'] in actual:
                height=max(24.,source.get('personBox',[0,0,0,source['imageSize'][1]])[3]-source.get('personBox',[0,0,0,0])[1])
                region_points=[p['xy'] for p in canonical(source) if p['region']==point['region'] and p.get('known',True)]
                size=height if point['region']=='body' else max(30.,np.linalg.norm(np.ptp(region_points,axis=0))) if len(region_points)>1 else 30.
                region_count=len(region_points)
                balance=1.5 if point['region']=='body' else np.sqrt(12/max(3,region_count))
                observations.append((i,dict(point,fitWeight=float(point['weight'])*balance**2),max(2.,size*(.02 if point['region']=='body' else .05))))
        hint=preferences.get(pose['personId'],dict(preset='keep',strength=.35));guided=hint['preset']!='keep'
        for axis in range(3):
            radius=(8 if len(poses)>1 else 2) if preserve and not initial_alignment else 45
            # No vertical floor placement for airborne or uncertain support.
            if preserve and not initial_alignment and axis==1 and all(supports[pose['personId'],s] in ('air','unknown') for s in ('l','r')):continue
            anchor_value=anchors[i]['translation'][axis]+anchors[i].get('referenceCamera',{}).get('originCm',[0,0,0])[axis] if preserve and warm_start else initial[i,axis]
            lo,hi=anchor_value-radius,anchor_value+radius
            if not lo<=initial[i,axis]<=hi:continue
            variables.append((i,'translation',axis));base.append(initial[i,axis]);lower.append(lo);upper.append(hi)
        for axis in range(3):
            if preserve and (axis!=1 or len(poses)==1):continue
            value=pose['rootRotation'][axis]
            radius=1.5 if preserve else 30
            anchor_value=anchors[i].get('rootRotation',[0,0,0])[axis] if preserve else value
            lo,hi=anchor_value-radius,anchor_value+radius
            if not lo<=value<=hi:continue
            variables.append((i,'rootRotation',axis));base.append(value);lower.append(lo);upper.append(hi)
        nodes={n['id']:n for n in pose['rig']['nodes']};active=set()
        # Only chains supporting observed joints or contact constraints are editable.
        incoming={c['region'] if c['region'].endswith('palm') else c.get('targetSide','l')+'_shoulder' if c['region']=='shoulder' and c.get('targetSide') else 'torso' for c in graph if c['otherId']==pose['personId'] and c.get('enabled',True)}
        if any(c['otherId']==pose['personId'] and c['region']=='shoulder' and not c.get('targetSide') for c in graph):incoming.update(('l_shoulder','r_shoulder'))
        for name in set(p['name'] for k,p,_ in observations if k==i)|{c['part'] for c in graph if c['personId']==pose['personId'] and c.get('enabled',True)}|incoming:
            active.update(chains[i].get(name,set()))
        for node in pose.get('pins',{}):active.update(dependency_chain(pose['rig'],node))
        core=semantics(pose['rig']);protected=set().union(*(dependency_chain(pose['rig'],core[k]) for k in ('hip','pelvis','spine1','spine2','spine3','spine4') if k in core))
        from cropped import zero_nodes
        cropped_nodes=zero_nodes(dict(cropPolicy=pose.get('cropPolicy',{})),pose['rig'])
        spine={core[k] for k in ('spine1','spine2','spine3','spine4') if k in core}
        for node in pose['rig']['nodes']:
            if node['id'] not in active or node['type']!='bone':continue
            # Exclude neutralized channels; later Studio edits keep their accepted
            # values rather than being re-zeroed by image refinement.
            if node['id'] in cropped_nodes:continue
            if preserve and node['id'] in protected and not (guided and node['id'] in spine):continue
            for axis in range(3):
                limit=node.get('limits',{}).get('xyz'[axis],{})
                if limit.get('locked') or 'xyz'[axis] in node.get('driven',[]):continue
                value=pose['rotations'].get(node['id'],[0,0,0])[axis]
                detail=any(s in node['id'].lower() for s in ('hand','thumb','index','mid','ring','pinky','foot','toe'))
                radius=(30. if detail else 12. if graph or guided else 6.) if preserve and not initial_alignment else (35. if detail else 18.)
                anchor_value=anchors[i]['rotations'].get(node['id'],[0,0,0])[axis] if preserve else value
                lo=max(anchor_value-radius,limit.get('min',-180) if limit.get('clamped') else -180);hi=min(anchor_value+radius,limit.get('max',180) if limit.get('clamped') else 180)
                # Deliberate Studio edits are valid starting intent, not a new
                # unconstrained optimizer anchor. Hold edits outside this budget.
                if not lo<=value<=hi:continue
                if hi-lo<1e-5:continue
                variables.append((i,node['id'],axis));base.append(float(np.clip(value,lo,hi)));lower.append(lo);upper.append(hi)
    if not observations:raise ValueError('No reliable image measurements are available for this fit.')
    base=np.array(base);active_contacts=[c for c in graph if c.get('enabled',True)]
    start_frames=[core_frame(p) for p in poses];anchor_frames=[core_frame(p) for p in anchors]
    target_tilts={}
    for i,p in enumerate(poses):
        hint=preferences.get(p['personId'],dict(preset='keep',strength=.35))
        tilt=anchor_frames[i]['tilt'];goal=0. if hint['preset']=='upright' else 15. if hint['preset']=='forward' else -15.
        # Keep the target anchored to the extraction, never to the last pass.
        if hint['preset']!='keep':target_tilts[i]=tilt+(goal-tilt)*hint['strength']
    rest=[rest_transforms(p['rig']) for p in poses]
    capsule_chains=[[{*dependency_chain(p['rig'],a),*dependency_chain(p['rig'],b)} for a,b in geometry(p,include_dependencies=True)[3]] for p in poses]
    def candidate(values,include_frames=False):
        result=[dict(p,rotations={k:list(v) for k,v in p['rotations'].items()},translation=list(p['translation']),rootRotation=list(p.get('rootRotation',[0,0,0]))) for p in poses]
        for (i,node,axis),v in zip(variables,values):
            if node in ('translation','rootRotation'):result[i][node][axis]=float(v)
            else:result[i]['rotations'].setdefault(node,[0.,0.,0.])[axis]=float(v)
        state=[target_points(p,include_frames=include_frames,rest=r) for p,r in zip(result,rest)]
        return (result,[s[0] for s in state],[s[2] for s in state]) if include_frames else (result,[s[0] for s in state])
    def contact_distance(c,points,geometries):
        i,j=index[c['personId']],index[c['otherId']];part=c['part'];own=points[i].get(part,points[i].get(part[0]+'_wrist'))
        if own is None:return 0.
        if c['part']=='torso':
            a,b,r,_=geometries[i][1][0];d,e,q,_=geometries[j][1][0]
            return segment_distance(a+geometries[i][3],b+geometries[i][3],d+geometries[j][3],e+geometries[j][3])-r-q
        if c['region'] in ('l_palm','r_palm'):
            other=points[j].get(c['region'],points[j].get(c['region'][0]+'_wrist'));return float(np.linalg.norm(own-other)) if other is not None else 0.
        g=geometries[j];a,b,r,_=g[1][0];a=a+geometries[j][3];b=b+geometries[j][3]
        if c['region']=='shoulder':
            choices=[points[j][name] for name in ((c['targetSide']+'_shoulder',) if c.get('targetSide') else ('l_shoulder','r_shoulder')) if name in points[j]]
            if choices:return min(float(np.linalg.norm(own-p)) for p in choices)-g[2]*.032
        elif c['region']=='waist':b=a+(b-a)*.35
        return float(np.linalg.norm(own-closest(own,a,b))-r)
    from reference_guidance import ordinal_pairs,normal_error
    image_pairs=[(i,a,b) for i,s in enumerate(sources) for a,b in ordinal_pairs(canonical(s))]
    normal_goals=[(i,goal) for i,s in enumerate(sources) for goal in s.get('guidanceNormals',[]) if goal['a'] in chains[i] and goal['b'] in chains[i]]
    def residual(values,with_meta=False):
        members,points,frames=candidate(values,True)
        # The same FK state supplies image points, contact proxies and posture.
        # Previously each residual traversed the rig three times per actor.
        geometries=[(*geometry(p,frames=(f[0],{k:v-np.asarray(p['translation']) for k,v in f[1].items()})),np.asarray(p['translation'])) for p,f in zip(members,frames)];result=[];owners=[]
        def ancestors(i,name):
            return chains[i].get(name,set())
        def add(values,who,scope=None,columns=None):
            values=np.atleast_1d(values);result.extend(values)
            if with_meta:owners.extend([dict(who=who,scope=scope,columns=columns)]*len(values))
        for i,item,tolerance in observations:
            add((project_target(points[i][item['name']],camera)-item['xy'])/tolerance*np.sqrt(item['fitWeight']),{i},{i:ancestors(i,item['name'])})
        for i,a,b in image_pairs:
            if a in points[i] and b in points[i]:
                # Genesis Y-up/Z-toward camera: larger Z is nearer.
                add(max(0.,points[i][b][2]-points[i][a][2]-15.)/20*.2,{i},{i:ancestors(i,a)|ancestors(i,b)})
        for i,goal in normal_goals:
            if goal['a'] in points[i] and goal['b'] in points[i]:add(normal_error(points[i],goal),{i},{i:ancestors(i,goal['a'])|ancestors(i,goal['b'])})
        for i,member in enumerate(members):
            for node,pin in member.get('pins',{}).items():
                scope={i:dependency_chain(member['rig'],node)}
                if 'position' in pin:
                    target=np.asarray(pin['position'])+np.asarray(originals[i].get('referenceCamera',{}).get('originCm',[0,0,0]))
                    add((frames[i][1][node]-target)*4,{i},scope)
                if 'rotation' in pin:add(Rotation.from_matrix(frames[i][0][node]@Rotation.from_quat(pin['rotation']).as_matrix().T).as_rotvec()*40,{i},scope)
        for c in active_contacts:
            i,j=index[c['personId']],index[c['otherId']]
            partner=c['region'] if c['region'].endswith('palm') else 'l_shoulder'
            add(contact_distance(c,points,geometries)/2*(1.8 if c.get('confirmed') else c['confidence']),{i,j},{i:ancestors(i,c['part']),j:ancestors(j,partner)|ancestors(j,'r_shoulder')})
            if c['part'].endswith('palm'):
                side=c['part'][0];keys=[side+'_wrist',side+'_index1',side+'_pinky1']
                if all(k in points[i] for k in keys):
                    wrist,first,last=[points[i][k] for k in keys];normal=np.cross(first-wrist,last-wrist);direction=points[j]['torso']-points[i][c['part']]
                    cosine=abs(normal@direction/max(np.linalg.norm(normal)*np.linalg.norm(direction),1e-9))
                    add((1-cosine)*.6,{i,j},{i:set().union(*(ancestors(i,k) for k in keys)),j:ancestors(j,'torso')})
                # A clearly segmented foreground palm must stay in front of the partner.
                if c.get('occlusion')=='front':add(max(0.,points[j]['torso'][2]-points[i][c['part']][2])/5*.3,{i,j},{i:ancestors(i,c['part']),j:ancestors(j,'torso')})
        for i in range(len(members)):
            for j in range(i):
                own,other=geometries[i][1],geometries[j][1]
                a,b=np.moveaxis(np.asarray([c[:2] for c in own]),1,0)+members[i]['translation']
                c,d=np.moveaxis(np.asarray([c[:2] for c in other]),1,0)+members[j]['translation']
                distances=segment_distances(a[:,None,:],b[:,None,:],c[None,:,:],d[None,:,:])
                radii=np.asarray([c[2] for c in own])[:,None]+np.asarray([c[2] for c in other])[None,:]
                arms=np.asarray([c[3]=='arm' for c in own])[:,None]|np.asarray([c[3]=='arm' for c in other])[None,:]
                gaps=np.maximum(0.,radii*np.where(arms,.55,.78)-distances)
                for ni,row in enumerate(gaps):
                    for nj,gap in enumerate(row):
                        # Conservative proxies: soften arm contact, never push partners apart indiscriminately.
                        add(gap/3,{i,j},{i:capsule_chains[i][ni],j:capsule_chains[j][nj]})
        sole=[]
        for i,p in enumerate(members):
            for side in ('l','r'):
                state=supports[p['personId'],side]
                keys=[side+'_heel'] if state=='heel' else [side+'_bigtoe',side+'_smalltoe'] if state=='toe' else [side+'_heel',side+'_bigtoe',side+'_smalltoe'] if state=='flat' else []
                sole.extend((i,points[i][k][1],k) for k in keys if k in points[i])
        # Pairwise support heights define a common plane, without setting airborne feet to it.
        if sole and warm_start:
            retained=originals[0]['referenceCamera']['originCm'][1]
            for i,y,name in sole:add((y-retained)/3,{i},{i:ancestors(i,name)})
        elif sole:
            anchor_i,anchor,anchor_name=sole[0]
            for i,y,name in sole[1:]:
                scope={i:ancestors(i,name),anchor_i:ancestors(anchor_i,anchor_name)}
                if i==anchor_i:scope[i]=ancestors(i,name)|ancestors(i,anchor_name)
                add((y-anchor)/3,{i,anchor_i},scope)
        if preserve:
            for i,p in enumerate(members):
                frame=core_frame(p,frames[i]);original=start_frames[i];guided=i in target_tilts
                # World-frame constraints also catch ERC/root compensation.
                for key,rotation in original['rotations'].items():
                    current=frame['rotations'][key]
                    delta=np.degrees(Rotation.from_matrix(current@rotation.T).as_rotvec())
                    add(delta/(12. if guided and key.startswith('spine') else 1.),{i})
                for key,z in original['depth'].items():add((frame['depth'][key]-z)/(frame['height']*(.08 if guided else .01)),{i})
                if guided:add((frame['tilt']-target_tilts[i])/.8,{i})
        # Root-depth prior discourages arbitrary separation while allowing real contact depth.
        for k,(i,node,axis) in enumerate(variables):add((values[k]-base[k])/(35 if node=='translation' else 40)*.3,{i},columns={k})
        return (np.array(result),owners) if with_meta else np.array(result)
    before,owners=residual(base,True);sparsity=lil_matrix((len(before),len(variables)),dtype=int)
    for row,owner in enumerate(owners):
        for col,(i,node,_) in enumerate(variables):
            if owner['columns'] is not None:
                if col in owner['columns']:sparsity[row,col]=1
            elif i in owner['who'] and (owner['scope'] is None or node in ('translation','rootRotation') or node in owner['scope'].get(i,set())):sparsity[row,col]=1
    stage_timings={};stage_calls={};last_progress=0.
    def solve_stage(label,start,percent,**options):
        nonlocal last_progress
        started=perf_counter();calls=0;progress(label,percent)
        def checked(values):
            nonlocal calls,last_progress
            calls+=1;now=perf_counter()
            if now-last_progress>=1.:
                progress(f'{label} · {now-started:.0f}s',percent);last_progress=now
            return residual(values)
        result=least_squares(checked,start,bounds=(lower,upper),jac_sparsity=sparsity.tocsr(),loss='soft_l1',f_scale=2.,ftol=1e-4,xtol=1e-4,gtol=1e-4,**options)
        stage_timings[label]=perf_counter()-started;stage_calls[label]=calls
        return result
    fit=solve_stage('Fitting visible joints and contacts',base,75,max_nfev=50)
    # A bounded restart can finish a difficult fit that exhausted its first budget.
    # Keep the same rig/pose bounds and original prior; do not expand angles each pass.
    attempts=1
    if fit.status==0 and np.isfinite(fit.x).all():
        extra=solve_stage('Refining visible details · second pass',fit.x,90,max_nfev=50)
        attempts=2
        def body_error(points,i):
            measured=[item for owner,item,_ in observations if owner==i and item['region']=='body']
            return np.mean([np.linalg.norm(project_target(points[i][p['name']],camera)-p['xy']) for p in measured]) if measured else 0.
        first_points=candidate(fit.x)[1];extra_points=candidate(extra.x)[1]
        if np.isfinite(extra.x).all() and np.linalg.norm(extra.fun)<np.linalg.norm(fit.fun) and all(body_error(extra_points,i)<=body_error(first_points,i)*1.05+2 for i in range(len(poses))):fit=extra
    initial_points=candidate(base)[1]
    def failure(message,owner=None,names=None):
        scope=set().union(*(chains[owner].get(name,set()) for name in names)) if names and owner is not None else None
        columns={k for k,(i,node,_) in enumerate(variables) if (owner is None or i==owner) and (scope is None or node=='rootRotation' or node in scope)}
        return dict(message=message,columns=columns)
    def validate(values):
        if not np.isfinite(values).all() or np.linalg.norm(residual(values))>np.linalg.norm(before)+1e-8:return failure('The bounded objective did not improve.')
        members,points=candidate(values)
        for i in range(len(poses)):
            evidence=[item for k,item,_ in observations if k==i and item['region']=='body']
            old=np.mean([np.linalg.norm(project_target(initial_points[i][p['name']],camera)-p['xy']) for p in evidence]) if evidence else 0.
            new=np.mean([np.linalg.norm(project_target(points[i][p['name']],camera)-p['xy']) for p in evidence]) if evidence else 0.
            if new>old*1.05+2:return failure('Visible body agreement would worsen.',i)
            if preserve:
                # An initial camera/placement alignment can trade proximal 2D
                # errors when Genesis proportions differ from the source. The
                # hip/torso world frame stays protected in both stages.
                if not initial_alignment:
                    for item in evidence:
                        if not item['name'].endswith(('hip','shoulder')):continue
                        old_point=np.linalg.norm(project_target(initial_points[i][item['name']],camera)-item['xy']);new_point=np.linalg.norm(project_target(points[i][item['name']],camera)-item['xy'])
                        if new_point>old_point+max(2.,sources[i]['imageSize'][1]*.004):return failure('A visible torso landmark would move away from the reference.',i,{item['name']})
                changes=drift(members[i],poses[i]);guided=i in target_tilts
                if changes['coreRotationDegrees']>(20. if guided else 2.)+.001 or changes['coreDepthCm']>start_frames[i]['height']*(.12 if guided else .02)+.001 or not guided and abs(changes['torsoTiltDegrees']-start_frames[i]['tilt'])>2.:return failure('The fit would change the accepted side posture beyond its safe budget.',i)
                # Protect whole limb chains as well as distal details. Mean body
                # error alone can hide one collapsed arm or lifted leg.
                for region in ('l_arm','r_arm','l_leg','r_leg','l_hand','r_hand','l_foot','r_foot'):
                    parts=('shoulder','elbow','wrist') if region.endswith('arm') else ('hip','knee','ankle') if region.endswith('leg') else ()
                    visible=regional_observations(observations,i,region)
                    if not visible:continue
                    old_region=np.mean([np.linalg.norm(project_target(initial_points[i][p['name']],camera)-p['xy']) for p in visible]);new_region=np.mean([np.linalg.norm(project_target(points[i][p['name']],camera)-p['xy']) for p in visible])
                    names={p['name'] for p in visible}
                    budget=max(t for k,p,t in observations if k==i and p['name'] in names) if initial_alignment and parts else 2.
                    if new_region>old_region*1.05+budget:return failure('A visible limb would lose image agreement: '+region+'.',i,names)
        return None
    placement={k for k,(_,node,_) in enumerate(variables) if node=='translation'}
    recovery_attempts=0;recovery_seconds=0.
    def refit(columns):
        nonlocal recovery_attempts,recovery_seconds
        free=[k for k in range(len(base)) if k not in placement]
        if not free:return None
        recovery_attempts+=1;progress('Checking a bounded regional correction',93)
        lo=np.asarray(lower).copy();hi=np.asarray(upper).copy();selected=list(columns)
        lo[selected]=base[selected]+(lo[selected]-base[selected])*.5
        hi[selected]=base[selected]+(hi[selected]-base[selected])*.5
        def expand(values):
            trial=fit.x.copy();trial[free]=values;return trial
        started=perf_counter()
        local=least_squares(lambda values:residual(expand(values)),np.clip(fit.x[free],lo[free],hi[free]),bounds=(lo[free],hi[free]),jac_sparsity=sparsity.tocsr()[:,free],max_nfev=30,loss='soft_l1',f_scale=2.,ftol=1e-4,xtol=1e-4,gtol=1e-4)
        recovery_seconds+=perf_counter()-started
        return expand(local.x) if np.isfinite(local.x).all() else None
    if preserve:values,rejected,outcome=bounded_fallback(base,fit.x,placement,validate,lambda v:np.linalg.norm(residual(v)),refit)
    else:
        rejected=validate(fit.x);outcome='retained' if rejected else 'full';values=base if rejected else fit.x
    accepted=outcome!='retained';proposal_rejection=rejected['message'] if rejected else None
    rejection=proposal_rejection if not accepted else None
    members,points=candidate(values)
    final_objective=float(np.linalg.norm(residual(values)))
    # Score every stage against exactly the same observations and camera.
    initial_members,_=candidate(base);proposal_members,_=candidate(fit.x if np.isfinite(fit.x).all() else base)
    initial_quality=[quality(s,p,camera) for s,p in zip(sources,initial_members)]
    proposal_quality=[quality(s,p,camera) if np.isfinite(fit.x).all() else None for s,p in zip(sources,proposal_members)]
    regional_changes=[]
    for i in range(len(poses)):
        for region in ('l_arm','r_arm','l_leg','r_leg','l_hand','r_hand','l_foot','r_foot'):
            measured=regional_observations(observations,i,region)
            if not measured:continue
            error=lambda target:float(np.mean([np.linalg.norm(project_target(target[p['name']],camera)-p['xy']) for p in measured]))
            old,new=error(initial_points[i]),error(points[i])
            regional_changes.append(dict(personId=poses[i]['personId'],region=region,beforeErrorPx=old,afterErrorPx=new,worsened=new>old*1.05+2))
    soles=[]
    for p,point in zip(members,points):
        for side in ('l','r'):
            state=supports[p['personId'],side]
            parts=('heel',) if state=='heel' else ('bigtoe','smalltoe') if state=='toe' else ('heel','bigtoe','smalltoe') if state=='flat' else ()
            soles.extend(point[side+'_'+part][1] for part in parts if side+'_'+part in point)
    retained_floor=originals[0].get('referenceCamera',{}).get('originCm',[0,0,0])[1] if warm_start else min(p['translation'][1] for p in members)
    # Warm fitting retains its floor and camera exactly, including all-air poses.
    floor=retained_floor if warm_start else min(soles,default=retained_floor)
    center=np.mean([p['translation'] for p in members],axis=0);origin=np.asarray(originals[0]['referenceCamera']['originCm']) if warm_start else np.array([center[0],floor,center[2]])
    camera=reference_camera(sources[0],origin);digest=stamp([(s['personKey'],p['rigId'],stamp(p['rig'])) for s,p in zip(sources,members)]+[graph,list(support),[s.get('refinementSignature') for s in sources],POLICY_VERSION if preserve else None,TARGET_FIT_VERSION,context_key(anchors),context_key(originals),preferences])
    gaps=[];g=[(*geometry(p),np.asarray(p['translation'])) for p in members]
    for c in active_contacts:gaps.append(dict(id=c['id'],gapCm=abs(contact_distance(c,points,g))))
    for source,p,original_rig in zip(sources,members,original_rigs):
        p['rig']=original_rig;p['targetFitVersion']=TARGET_FIT_VERSION
        p['translation']=(np.asarray(p['translation'])-origin).tolist();p['referenceCamera']=camera;p['quality']=quality(source,p,camera)
        i=index[p['personId']]
        p['quality']['fit']=dict(version=TARGET_FIT_VERSION,outcome=outcome,stage='initial-alignment' if initial_alignment else 'accepted-pose-refinement' if preserve else 'legacy-alignment',reason=proposal_rejection,initialMatched=initial_quality[i]['visible']['matched'],proposalMatched=proposal_quality[i]['visible']['matched'] if proposal_quality[i] else None,placementPreserved=accepted,regionalChanges=[c for c in regional_changes if c['personId']==p['personId']])
        p['layout']=dict(version=3 if preserve else 2,id=digest,personIds=[s['personId'] for s in sources],reference=True,camera=camera) if len(members)>1 else None
        p['footSupport']=[dict(side=side,state=supports[p['personId'],side]) for side in ('l','r')]
        if not accepted:p['warnings']=list(dict.fromkeys(p['warnings']+['The proposed refinement was rejected; the previous bounded pose was retained.']))
        elif outcome=='partial':p['warnings']=list(dict.fromkeys(p['warnings']+['A regional correction was limited to protect the accepted pose. Placement alignment was retained; inspect image agreement and side views.']))
    diagnostics=dict(targetStage='initial-alignment' if initial_alignment else 'accepted-pose-refinement' if preserve else 'legacy-alignment',proposalRejection=proposal_rejection,contacts=len(active_contacts),armAdjustments=int(accepted),maximumProxyOverlapCm=0.,accepted=accepted,initialObjective=float(np.linalg.norm(before)),finalObjective=final_objective,contactGaps=gaps,depthUncertain=True,
                     support=[dict(personId=k[0],side=k[1],state=v,reason='User override' if any(vv.get('personId')==k[0] and vv.get('side')==k[1] for vv in support) else inferred[k]['reason']) for k,v in supports.items()],fitAttempts=attempts,recoveryAttempts=recovery_attempts,solverConverged=fit.status>0,outcome=outcome,regionalChanges=regional_changes)
    diagnostics['timings']=dict(stagesSeconds=stage_timings,residualCalls=stage_calls,regionalRecoverySeconds=recovery_seconds)
    diagnostics['pins']=[]
    for i,p in enumerate(members):
        state=target_points(p,include_frames=True)[2]
        for node,pin in p.get('pins',{}).items():
            gap=float(np.linalg.norm(state[1][node]-pin['position'])) if 'position' in pin else None
            angle=float(np.degrees(Rotation.from_matrix(state[0][node]@Rotation.from_quat(pin['rotation']).as_matrix().T).magnitude())) if 'rotation' in pin else None
            diagnostics['pins'].append(dict(personId=p['personId'],joint=node,positionGapCm=gap,rotationGapDegrees=angle))
            if gap is not None and gap>.5 or angle is not None and angle>1:p['warnings'].append('A soft joint pin could not be reached within the retained pose and rig limits. Inspect the pinned joint in Pose Studio.')
    if warm_start:
        diagnostics['maximumSupportPlaneGapCm']=max((abs(points[i][side+'_'+part][1]-retained_floor) for i,p in enumerate(members) for side in ('l','r') for part in (('heel',) if supports[p['personId'],side]=='heel' else ('bigtoe','smalltoe') if supports[p['personId'],side]=='toe' else ('heel','bigtoe','smalltoe') if supports[p['personId'],side]=='flat' else ()) if side+'_'+part in points[i]),default=0.)
        if diagnostics['maximumSupportPlaneGapCm']>2:
            for p in members:p['warnings'].append('Requested foot support remains above or below the retained floor. The fit kept its bounded placement; inspect the feet and floor in Pose Studio.')
    if preserve:
        diagnostics['posture']=dict(version=POLICY_VERSION,preserved=accepted,rejection=rejection,frame='workspace',gravityVerified=False,tiltFrame='pelvis-spine',acceptedFraction=1. if outcome=='full' else 0. if not accepted else None,sourceStage='unchanged-fused-parameters',people=[dict(personId=p['personId'],**drift(p,o),baselineDrift=drift(p,a),preset=preferences.get(p['personId'],{}).get('preset','keep'),targetTiltDegrees=target_tilts.get(i),limitedGuidance=i in target_tilts and (outcome!='full' or abs(core_frame(p)['tilt']-target_tilts[i])>2.)) for i,(p,o,a) in enumerate(zip(members,originals,anchors))])
    # Report actual proxy penetration rather than treating a fitted objective as proof.
    final_geometries=[geometry(p) for p in members]
    overlap=[]
    for i in range(len(members)):
        for j in range(i):
            for a,b,r,label in final_geometries[i][1]:
                for c,d,q,other in final_geometries[j][1]:overlap.append(max(0.,(r+q)*(.55 if label=='arm' or other=='arm' else .78)-segment_distance(a+members[i]['translation'],b+members[i]['translation'],c+members[j]['translation'],d+members[j]['translation'])))
    diagnostics['maximumProxyOverlapCm']=float(max(overlap,default=0.))
    warnings=['Single-image depth is uncertain. Contact uses fixed skeleton proxies; inspect side views and custom morphs.'] if len(members)>1 else []
    if any(c['gapCm']>2 for c in gaps):warnings.append('Some proposed contacts remain more than 2 cm apart. Confirm their ownership and region in Refine match, then inspect Side view.')
    if diagnostics['maximumProxyOverlapCm']>2:warnings.append('Some skeleton proxies still overlap. Refine visible contacts or adjust the accepted pose in Pose studio.')
    for p in members:p['warnings']=list(dict.fromkeys(p['warnings']+warnings))
    return dict(version=3 if preserve else 2,id=digest,imageId=sources[0]['imageId'],poses=members,warnings=warnings,contacts=graph,referenceCamera=camera,diagnostics=diagnostics)

