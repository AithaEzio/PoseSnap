"""Conservative original-frame crop policy; never changes cached SAM predictions."""
import copy
import hashlib
from pathlib import Path
import numpy as np
from storage import read_json, image_dir

VERSION = 1
SIGNATURE = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:24]


def enabled(root, payload, source):
    value = payload.get('zeroCroppedJoints', read_json(root/'data/settings.json', {}).get('zeroCroppedJoints', True))
    if type(value) is not bool:
        raise ValueError('Invalid zero cropped joints preference')
    return value and source.get('extractionMethod', 'smart') == 'smart'


def definitions():
    """Each rotation controls its outgoing segment, not its joint-centre pixel."""
    result = {}
    for side in ('l', 'r'):
        fingers = [side+'_'+finger+str(part) for finger in ('thumb','index','middle','ring','pinky') for part in (1,2,3)]
        tips = [side+'_'+finger+'tip' for finger in ('thumb','index','middle','ring','pinky')]
        hand = fingers+tips
        feet = [side+'_'+part for part in ('bigtoe','smalltoe','heel')]
        result[side+'_upperarm'] = [side+'_elbow',side+'_wrist',*hand]
        result[side+'_forearm'] = [side+'_wrist',*hand]
        result[side+'_hand'] = hand
        result[side+'_thigh'] = [side+'_knee',side+'_ankle',*feet]
        result[side+'_shin'] = [side+'_ankle',*feet]
        result[side+'_foot'] = feet
        result[side+'_toes'] = feet[:2]
        for finger in ('thumb','index','middle','ring','pinky'):
            for part in (1,2,3):
                key=side+'_'+('mid' if finger=='middle' else finger)+str(part)
                result[key]=[side+'_'+finger+str(p) for p in range(part+1,4)]+[side+'_'+finger+'tip']
    return result


def classify(source, person):
    """Confidence is not visibility. Require a frame exit or boundary evidence."""
    from measurements import MHR
    from wholebody import BODY
    if person.get('id',source['personId'])!=source['personId']:
        raise ValueError('Crop evidence belongs to another person')
    width,height=source.get('imageSize',[0,0])
    if min(width,height)<=0:
        return {}
    size=np.array([width,height],dtype=float)
    band=max(2.,min(20.,min(size)*.02))
    box=np.asarray(source.get('personBox',person.get('box',[0,0,width,height])),dtype=float)
    touches=[box[0]<=band,box[1]<=band,box[2]>=width-band,box[3]>=height-band]
    raw=person.get('keypoints',source.get('detectorKeypoints',[]))
    detector={name:raw[i] for i,name in BODY.items() if len(raw)>i}
    measurements={}
    for point in source.get('measurements',[]):
        if point.get('personId',source['personId'])==source['personId']:
            measurements.setdefault(point['name'],[]).append(point)
    def finite(xy):
        return np.asarray(xy).shape==(2,) and np.isfinite(xy).all()
    def inside(xy):
        return finite(xy) and bool(np.all(np.asarray(xy)>=0) and np.all(np.asarray(xy)<size))
    def exit_edges(xy,near=False):
        if not finite(xy):return []
        x,y=xy;gap=band if near else 0.
        return [i for i,flag in enumerate((x<gap,y<gap,x>=width-gap,y>=height-gap)) if flag]
    observed={}
    for name in MHR:
        anchor=detector.get(name)
        # A confident RTMW body guess must not overrule an absent RTMO anchor.
        if anchor is not None:
            observed[name]=len(anchor)==3 and anchor[2]>=.7 and inside(anchor[:2])
        else:
            observed[name]=any(p.get('known',True) and p.get('weight',0)>=.7 and inside(p['xy']) and not exit_edges(p['xy'],True) for p in measurements.get(name,[]))
    for side in ('l','r'):
        wrist=side+'_wrist'
        hand_names=[name for name in MHR if name.startswith(side+'_') and any(f in name for f in ('thumb','index','middle','ring','pinky'))]
        # A partially cropped elbow can make RTMO miss an otherwise visible
        # wrist. Corroborated, owned hand detail must protect that entire chain.
        hand_visible=sum(observed.get(name,False) for name in hand_names)>=8
        owned_wrist=any(p.get('known',True) and p.get('weight',0)>=.7 and inside(p['xy']) and not exit_edges(p['xy'],True) for p in measurements.get(wrist,[]))
        if hand_visible and owned_wrist:observed[wrist]=True
        feet=[side+'_'+part for part in ('bigtoe','smalltoe','heel')]
        if not observed.get(side+'_ankle',False) and sum(observed.get(name,False) for name in feet)<2:
            for name in feet:observed[name]=False
        if not observed.get(side+'_wrist',False):
            for name in observed:
                if name.startswith(side+'_') and any(f in name for f in ('thumb','index','middle','ring','pinky')):
                    observed[name]=False
    projected=source.get('projectedKeypoints',[])
    result={}
    for name,index in MHR.items():
        if observed.get(name):
            result[name]=dict(state='visible',reason='Reliable owned landmark inside the original image')
            continue
        guesses=[p['xy'] for p in measurements.get(name,[])]
        if index<len(projected):guesses.append(projected[index])
        # A missing [0,0,0] detection has no spatial meaning. Confidence alone
        # never makes an in-frame occlusion evidence of an image boundary.
        if name in detector and len(detector[name])==3 and detector[name][2]>0 and finite(detector[name][:2]):guesses.append(detector[name][:2])
        outside={edge for xy in guesses for edge in exit_edges(xy)}
        near={edge for xy in guesses for edge in exit_edges(xy,True)}
        if any(touches[edge] for edge in outside):
            result[name]=dict(state='cropped',reason='Unobserved segment projects beyond an original-image edge reached by this person')
        elif any(touches[edge] for edge in near):
            result[name]=dict(state='cropped',reason='Unobserved segment ends at a clipped original-image boundary')
        else:
            result[name]=dict(state='uncertain',reason='No reliable visible landmark; image cropping is not established')
    return result


def prepare(root, source, payload, person=None):
    """Derive a fitting input. The original source and its measurements stay intact."""
    result=copy.deepcopy(source)
    if not enabled(root,payload,source):
        result['cropPolicy']=dict(version=VERSION,signature=SIGNATURE,enabled=False,zeroSemantics=[],landmarks={})
        return result
    if person is None:
        people=read_json(image_dir(root,source['imageId'])/'people.json',[])
        person=next((p for p in people if p['id']==source['personId']),{})
    states=classify(source,person)
    zero=[]
    for key,names in definitions().items():
        values=[states.get(name,{}).get('state','uncertain') for name in names]
        if 'visible' not in values and 'cropped' in values:zero.append(key)
    # A cropped wrist/ankle carries its unobserved downstream chain with it.
    for side,part in ((s,p) for s in ('l','r') for p in ('hand','foot')):
        anchor=side+('_wrist' if part=='hand' else '_ankle')
        if states.get(anchor,{}).get('state')=='cropped':
            for key,names in definitions().items():
                belongs=(part=='hand' and (key==side+'_hand' or any(key.startswith(side+'_'+f) for f in ('thumb','index','mid','ring','pinky')))) or (part=='foot' and key in (side+'_foot',side+'_toes'))
                if belongs and not any(states.get(n,{}).get('state')=='visible' for n in names):zero.append(key)
    protected=[]
    for contact in payload.get('contacts',[]):
        if not contact.get('enabled',True) or not contact.get('confirmed'):continue
        if contact.get('personId')==source['personId']:protected.append(contact.get('part',''))
        if contact.get('otherId')==source['personId']:protected.append(contact.get('region',''))
    for part in protected:
        side=part[:1]
        if side in ('l','r'):
            zero=[key for key in zero if not (key.startswith(side+'_') and any(token in key for token in ('upperarm','forearm','hand','thumb','index','mid','ring','pinky')))]
    result['cropPolicy']=dict(version=VERSION,signature=SIGNATURE,enabled=True,zeroSemantics=sorted(set(zero)),landmarks=states,
                              protectedContacts=protected,personId=source['personId'],personKey=source.get('personKey'),imageSize=source.get('imageSize'))
    # A neutralized chain cannot fit its unobserved distal guesses. A lone foot
    # detail can remain uncertain even when its cropped ankle establishes that
    # the chain is outside the photo; do not let it pull the visible body away.
    excluded={name for key in zero for name in definitions()[key] if states.get(name,{}).get('state')!='visible'}
    # Exclude clipped guesses from image losses, support and automatic contacts.
    for point in result.get('measurements',[]):
        if point['name'] in excluded or states.get(point['name'],{}).get('state')=='cropped':
            point.update(known=False,reason='Outside the original image · neutral crop policy')
    if result.get('evidence'):
        from wholebody import BODY
        result['evidence']=[p for p in result['evidence'] if BODY.get(p.get('coco')) not in excluded and states.get(BODY.get(p.get('coco')),{}).get('state')!='cropped']
        result['contactEvidence']=[p for p in result.get('contactEvidence',[]) if BODY.get(p.get('coco')) not in excluded and states.get(BODY.get(p.get('coco')),{}).get('state')!='cropped']
    return result


def zero_nodes(source, rig):
    policy=source.get('cropPolicy',{})
    if not policy.get('enabled'):return set()
    from studio import semantics
    mapping=semantics(rig);ids={n['id'] for n in rig['nodes']};result=set()
    for key in policy.get('zeroSemantics',[]):
        if key in mapping:result.add(mapping[key])
        side=key[:1];part=key[2:]
        for suffix in {'upperarm':('ShldrBend','ShldrTwist'),'forearm':('ForearmBend','ForearmTwist'),'thigh':('ThighBend','ThighTwist')}.get(part,()):
            if side+suffix in ids:result.add(side+suffix)
    return result


def neutral(node, values):
    values=list(values)
    for axis,key in enumerate('xyz'):
        limit=node.get('limits',{}).get(key,{})
        if limit.get('locked') or key in node.get('driven',[]):continue
        values[axis]=float(np.clip(0.,limit.get('min',-360) if limit.get('clamped') else -360,limit.get('max',360) if limit.get('clamped') else 360))
    return values


def annotate(source, pose, nodes):
    policy=source.get('cropPolicy')
    if policy is None:return pose
    pose['cropPolicy']=dict(version=VERSION,signature=SIGNATURE,enabled=policy['enabled'],joints=sorted(nodes),
        zeroSemantics=policy.get('zeroSemantics',[]),personId=source['personId'],personKey=source.get('personKey'),
        landmarks=copy.deepcopy(policy.get('landmarks',{})))
    if nodes:
        labels={n['id']:n.get('name',n['id']) for n in pose['rig']['nodes']}
        pose['warnings']=list(dict.fromkeys([*pose['warnings'],'Cropped joints started at neutral within rig limits: '+', '.join(labels[n] for n in sorted(nodes))+'. Visible chains are kept; these joints remain editable in Pose Studio.']))
    if policy.get('protectedContacts'):
        pose['warnings']=list(dict.fromkeys([*pose['warnings'],'Confirmed partner contacts are protected from crop zeroing. Inspect any cropped contact chain in Pose Studio.']))
    if policy.get('enabled') and any(p['state']=='uncertain' for p in policy.get('landmarks',{}).values()):
        pose['warnings']=list(dict.fromkeys([*pose['warnings'],'Some unseen anatomy could not be confirmed outside the photo. Occluded or uncertain joints retain their estimated pose.']))
    return pose


def visible_capsules(pose, positions, capsules):
    """Unseen neutral limbs must not push the visible actors apart."""
    nodes=zero_nodes(dict(cropPolicy=pose.get('cropPolicy',{})),pose['rig'])
    if not nodes:return capsules
    hidden=[positions[node] for node in nodes if node in positions]
    return [item for item in capsules if item[3]=='torso' or not any(np.linalg.norm(item[0]-point)<1e-6 for point in hidden)]


def adjust_accepted(root, folder, sources, derived, payload):
    """Change only cropped channels of a compatible accepted result, without refit."""
    from time import perf_counter
    started=perf_counter()
    current=payload.get('currentPoses',[])
    if not isinstance(current,list) or len(current)!=len(sources) or not current:return None
    if any(not s.get('cropPolicy',{}).get('enabled') for s in derived):return None
    if any(p.get('cropPolicy',{}).get('enabled') or not p.get('postureBaseline') for p in current):return None
    if {p.get('personId') for p in current}!={s['personId'] for s in sources}:return None
    if any(p.get('imageId')!=sources[0]['imageId'] for p in current):return None
    source_context={s['personId']:(s.get('sourceGuidance') or {}).get('id','original') for s in sources}
    if any((p.get('sourceGuidance') or {}).get('id','original')!=source_context[p['personId']] for p in current):return None
    if len(current)==1 and len((current[0].get('layout') or {}).get('personIds',[]))>1:return None
    expected={m['personId']:m['rigId'] for m in payload.get('members',[])}
    if payload.get('rigId') and len(sources)==1:expected[sources[0]['personId']]=payload['rigId']
    if any(p['personId'] in expected and p.get('rigId')!=expected[p['personId']] for p in current):return None
    by_id={p['personId']:p for p in current}
    current=[copy.deepcopy(by_id[s['personId']]) for s in sources]
    from editor import checked_poses
    from posture import load_baselines,context_key
    try:
        checked_poses(root,sources[0]['imageId'],current)
        load_baselines(folder,sources,current)
    except (ValueError,KeyError,OSError):return None
    from measurements import quality,stamp
    camera=current[0].get('referenceCamera')
    if not camera or any(p.get('referenceCamera')!=camera for p in current):return None
    for source,pose in zip(derived,current):
        candidates=zero_nodes(source,pose['rig']);nodes={n['id']:n for n in pose['rig']['nodes']};protected=set()
        for pinned in pose.get('pins',{}):
            while pinned in nodes and pinned not in protected:
                protected.add(pinned);pinned=nodes[pinned]['parent']
        for name in candidates-protected:
            pose['rotations'][name]=neutral(nodes[name],pose['rotations'].get(name,[0.,0.,0.]))
        annotate(source,pose,candidates-protected)
        if candidates&protected:pose['warnings'].append('Pinned joints and their parent chains were kept; conflicting cropped channels were not zeroed.')
        pose['quality']=quality(source,pose,camera)
        evidence=source.get('referenceEvidence')
        if evidence:
            pose['referenceEvidence']=copy.deepcopy(evidence)
            pose['warnings']=list(dict.fromkeys([*pose['warnings'],*evidence.get('notes',[])]))
        else:
            old=pose.pop('referenceEvidence',{})
            pose['warnings']=[note for note in pose['warnings'] if note not in old.get('notes',[])]
    # Local rotations outside the cropped set, root orientation, placement, pins,
    # rig geometry and the shared camera are copied exactly from the accepted pose.
    from interaction import geometry,segment_distance
    shapes=[geometry(p) for p in current];overlap=[]
    for i,shape in enumerate(shapes):
        for j,other in enumerate(shapes[:i]):
            for a,b,r,label in shape[1]:
                for c,d,q,otherlabel in other[1]:
                    overlap.append(max(0.,(r+q)*(.55 if label=='arm' or otherlabel=='arm' else .78)-segment_distance(a+current[i]['translation'],b+current[i]['translation'],c+current[j]['translation'],d+current[j]['translation'])))
    return dict(version=3,id=stamp([VERSION,context_key(current)]),imageId=sources[0]['imageId'],poses=current,
        referenceCamera=camera,warnings=[],contacts=copy.deepcopy(payload.get('contacts',[])),
        diagnostics=dict(contacts=len(payload.get('contacts',[])),armAdjustments=0,maximumProxyOverlapCm=max(overlap,default=0.),accepted=True,targetStage='crop-adjustment',visiblePosePreserved=True),
        executionTimings=dict(cropAdjustmentSeconds=perf_counter()-started))
