"""Expression-only channels, independent of pose retargeting and CUDA."""
import hashlib, json, math, re, time, uuid, subprocess
from pathlib import Path
from urllib.parse import quote
from storage import atomic_json, read_json, image_dir, identifier, signature
from rigs import RIG_LABELS

ENGINE='mediapipe-1.1.0-face-v1'
REGIONS=('brows','eyes','mouth','cheeks','gaze')
EXTRAS=('tongueOut',)
ACTIONS=('browDownLeft','browDownRight','browInnerUp','browOuterUpLeft','browOuterUpRight','cheekPuff','cheekSquintLeft','cheekSquintRight','eyeBlinkLeft','eyeBlinkRight','eyeLookDownLeft','eyeLookDownRight','eyeLookInLeft','eyeLookInRight','eyeLookOutLeft','eyeLookOutRight','eyeLookUpLeft','eyeLookUpRight','eyeSquintLeft','eyeSquintRight','eyeWideLeft','eyeWideRight','jawForward','jawLeft','jawOpen','jawRight','mouthClose','mouthDimpleLeft','mouthDimpleRight','mouthFrownLeft','mouthFrownRight','mouthFunnel','mouthLeft','mouthLowerDownLeft','mouthLowerDownRight','mouthPressLeft','mouthPressRight','mouthPucker','mouthRight','mouthRollLower','mouthRollUpper','mouthShrugLower','mouthShrugUpper','mouthSmileLeft','mouthSmileRight','mouthStretchLeft','mouthStretchRight','mouthUpperUpLeft','mouthUpperUpRight','noseSneerLeft','noseSneerRight')

def region(action):
    return 'brows' if action.startswith('brow') else 'gaze' if action.startswith('eyeLook') else 'eyes' if action.startswith('eye') else 'cheeks' if action.startswith(('cheek','nose')) else 'mouth'

def finite(value,lo,hi,label):
    if type(value) not in (int,float) or not math.isfinite(value) or not lo<=value<=hi:raise ValueError('Invalid '+label)
    return float(value)

def source(root,value):
    if isinstance(value,dict) and value.get('version')==2 and value.get('kind')=='text':
        if value.get('engine')!='text-intent-v1' or not re.fullmatch(r'text-[a-f0-9]{32}',str(value.get('sceneId',''))):raise ValueError('Invalid text expression source')
        face=value.get('face',{});actions=face.get('actions',{});extras=face.get('extras',{})
        if type(face.get('id')) is not int or not 1<=face['id']<=2 or set(actions)!=set(ACTIONS) or set(extras)-set(EXTRAS):raise ValueError('Invalid text facial actions')
        if face.get('landmarks') or face.get('box') or face.get('matrix') or value.get('imageId'):raise ValueError('Text expressions cannot claim detected image evidence')
        unknown=value.get('unknown',[])
        if not isinstance(unknown,list) or any(r not in REGIONS for r in unknown):raise ValueError('Unknown text facial region')
        return dict(version=2,kind='text',engine='text-intent-v1',sceneId=value['sceneId'],face=dict(id=face['id'],actions={k:finite(v,0,1.5,'text facial action') for k,v in actions.items()},extras={k:finite(v,0,1.5,'text supplemental action') for k,v in extras.items()},landmarks=[],box=[],matrix=[]),unknown=list(dict.fromkeys(unknown)),warnings=['Text-authored expression. No image landmarks or detection confidence.'])
    if not isinstance(value,dict) or value.get('version')!=1 or value.get('engine')!=ENGINE:raise ValueError('Unsupported facial extraction cache. Extract again.')
    folder=image_dir(root,value['imageId']);meta=read_json(folder/'image.json')
    if not meta or not (folder/'source.png').is_file():raise ValueError('The original reference is unavailable. Import it again.')
    face=value.get('face',{});w,h=meta['width'],meta['height']
    if type(face.get('id')) is not int or not 1<=face['id']<=32:raise ValueError('Invalid selected face')
    box=face.get('box',[])
    if len(box)!=4:raise ValueError('Invalid face crop')
    box=[finite(v,0,w if i%2==0 else h,'face crop') for i,v in enumerate(box)]
    if box[2]-box[0]<24 or box[3]-box[1]<24:raise ValueError('The face crop is too small')
    points=face.get('landmarks',[])
    if len(points)!=478 or any(not isinstance(p,list) or len(p)!=3 for p in points):raise ValueError('Expected 478 facial landmarks')
    points=[[finite(v,-2*max(w,h),3*max(w,h),'facial landmark') for v in p] for p in points]
    actions=face.get('actions',{})
    if set(actions)!=set(ACTIONS):raise ValueError('Incomplete or unknown facial actions')
    actions={k:finite(v,0,1,'facial action') for k,v in actions.items()}
    matrix=face.get('matrix',[])
    if len(matrix)!=16:raise ValueError('Missing head orientation evidence')
    matrix=[finite(v,-10000,10000,'face matrix') for v in matrix]
    unknown=value.get('unknown',[])
    if not isinstance(unknown,list) or any(r not in REGIONS for r in unknown):raise ValueError('Unknown facial region')
    warnings=value.get('warnings',[])
    if not isinstance(warnings,list) or len(warnings)>12 or any(not isinstance(s,str) or len(s)>500 for s in warnings):raise ValueError('Invalid facial diagnostics')
    evidence=face.get('evidence');clean_face=dict(id=face['id'],box=box,actions=actions,landmarks=points,matrix=matrix)
    if 'selectionBox' in face:
        selection=face['selectionBox']
        if not isinstance(selection,list) or len(selection)!=4:raise ValueError('Invalid selected face region')
        selection=[finite(v,0,w if i%2==0 else h,'selected face region') for i,v in enumerate(selection)]
        if selection[2]<=selection[0] or selection[3]<=selection[1]:raise ValueError('Invalid selected face region')
        clean_face['selectionBox']=selection
    if 'observationId' in face:
        expected=observation_id(value['imageId'],clean_face)
        if face['observationId']!=expected:raise ValueError('The saved face observation changed.')
        clean_face['observationId']=expected
    if 'roll' in face:clean_face['roll']=finite(face['roll'],-math.pi,math.pi,'face roll')
    if 'rawActions' in face:
        if not isinstance(face['rawActions'],dict) or set(face['rawActions'])!=set(ACTIONS):raise ValueError('Invalid original facial measurements')
        clean_face['rawActions']={k:finite(v,0,1,'original facial action') for k,v in face['rawActions'].items()}
    if 'extras' in face:
        if not isinstance(face['extras'],dict) or set(face['extras'])-set(EXTRAS):raise ValueError('Unknown supplemental facial action')
        clean_face['extras']={k:finite(v,0,1,'supplemental facial action') for k,v in face['extras'].items()}
    if evidence is not None:
        if not isinstance(evidence,dict) or evidence.get('passes') not in (2,4) or not isinstance(evidence.get('consistency'),dict) or set(evidence['consistency'])-set(REGIONS):raise ValueError('Invalid facial evidence')
        clean_face['evidence']=dict(passes=evidence['passes'],consistency={r:finite(v,0,1,'consistency diagnostic') for r,v in evidence['consistency'].items()})
        if 'supplemental' in evidence:
            extra=evidence['supplemental']
            if not isinstance(extra,dict) or set(extra)-{'cheekPuff','tongueOut'}:raise ValueError('Invalid supplemental evidence')
            for k,v in extra.items():
                if not isinstance(v,dict) or v.get('method') not in ('geometry-v1','mouth-rgb-v1'):raise ValueError('Invalid supplemental method')
                if 'accepted' in v and type(v['accepted']) is not bool:raise ValueError('Invalid supplemental acceptance')
            clean_face['evidence']['supplemental']={k:dict(value=finite(v.get('value'),0,1,'supplemental evidence'),agreement=finite(v.get('agreement'),0,1,'supplemental agreement'),method=v['method']) for k,v in extra.items()}
            for k,v in extra.items():
                if 'accepted' in v:clean_face['evidence']['supplemental'][k]['accepted']=v['accepted']
        if 'features' in evidence:
            features=evidence['features'];names=('mouthGap','cheekFullness','lowerFaceRatio','tongueCoverage')
            if not isinstance(features,dict) or set(features)-set(names+tuple('mirrored'+n[0].upper()+n[1:] for n in names)):raise ValueError('Unknown facial measurement')
            clean_face['evidence']['features']={k:finite(v,0,10,'facial measurement') for k,v in features.items()}
    return dict(version=1,engine=ENGINE,imageId=value['imageId'],face=clean_face,unknown=list(dict.fromkeys(unknown)),warnings=warnings)

def options(value):
    value=value or {};strength=finite(value.get('strength',1),0,1.5,'expression strength');groups=value.get('regions',{})
    if set(groups)!=set(REGIONS) or any(type(v) is not bool for v in groups.values()):raise ValueError('Invalid facial region settings')
    neutral=value.get('neutralRegions',[])
    if not isinstance(neutral,list) or len(neutral)>len(REGIONS) or any(r not in REGIONS for r in neutral):raise ValueError('Invalid neutral regions')
    adjustments=value.get('adjustments',{})
    if not isinstance(adjustments,dict) or set(adjustments)-set((*ACTIONS,*EXTRAS)):raise ValueError('Unknown expression adjustment')
    settings=dict(strength=strength,regions=groups,neutralRegions=list(dict.fromkeys(neutral)))
    if adjustments:settings['adjustments']={k:finite(v,0,1,'expression adjustment') for k,v in adjustments.items()}
    return settings

# Base control identifiers and signed directions audited against local metadata.
# Multiple controls may implement one action; never add the combined emotion dial
# as well as its primitives. Missing primitives stay explicitly unsupported.
G8={'browInnerUp':[('eCTRLBrowInnerUp-DownL',1),('eCTRLBrowInnerUp-DownR',1)],
    'jawOpen':[('eCTRLMouthOpen',1)],'jawForward':[('eCTRLJawOut-In',1)],
    'jawLeft':[('eCTRLJawSide-Side',-1)],'jawRight':[('eCTRLJawSide-Side',1)],
    'mouthClose':[('eCTRLMouthClosed',1)],'mouthPucker':[('eCTRLLipsPucker-Pressed',1)],
    'mouthLeft':[('eCTRLMouthSide-Side',-1)],'mouthRight':[('eCTRLMouthSide-Side',1)],
    'mouthRollLower':[('eCTRLLipBottomOut-InL',-1),('eCTRLLipBottomOut-InR',-1)],
    'mouthRollUpper':[('eCTRLLipTopOut-InL',-1),('eCTRLLipTopOut-InR',-1)],
    # Genesis 8's right signed dial is reversed. Positive R means suck in.
    'cheekPuff':[('eCTRLCheeksBalloon-SuckInL',1),('eCTRLCheeksBalloon-SuckInR',-1)]}
# Negative In-Out extends the G8 tongue. Confirmed on both base generations
# using tongue04 world transforms; the positive side retracts it.
G8['tongueOut']=[('eCTRLTongueIn-Out',-1)]
for side,short in [('Left','L'),('Right','R')]:
    for action,identifier,sign in [
        ('browOuterUp','eCTRLBrowOuterUp-Down',1),
        ('eyeBlink','eCTRLEyesClosed',1),('eyeSquint','eCTRLEyesSquint-Widen',1),('eyeWide','eCTRLEyesSquint-Widen',-1),
        ('mouthSmile','eCTRLMouthSmileSimple',1),('mouthFrown','eCTRLMouthCornerUp-Down',-1),
        ('mouthUpperUp','eCTRLLipTopUp-Down',1),('mouthLowerDown','eCTRLLipBottomUp-Down',-1),
        ('mouthStretch','eCTRLMouthWide-Narrow',1),('cheekSquint','eCTRLCheekEyeFlex',1)]:
        G8[action+side]=[(identifier+short,sign)]
    G8['browDown'+side]=[('eCTRLBrowInnerUp-Down'+short,-1),('eCTRLBrowOuterUp-Down'+short,-1)]
    # G8 has no independent ARKit-style eye morphs. Audited anatomical node
    # rotations drive each eye separately in degrees, within connected limits.
    # Native skinned iris measurements: +Y moves toward -X, +X moves up.
    # Bone quaternion signs alone do not describe the visible skinned eye.
    node='lEye' if side=='Left' else 'rEye';sign=-1 if side=='Left' else 1
    G8['eyeLookOut'+side]=[(node+'.YRotate',16*sign)]
    G8['eyeLookIn'+side]=[(node+'.YRotate',-16*sign)]
    G8['eyeLookUp'+side]=[(node+'.XRotate',12)]
    G8['eyeLookDown'+side]=[(node+'.XRotate',-12)]
G9={a:[('facs_bs_'+a[0].upper()+a[1:],1)] for a in ACTIONS}
G9['tongueOut']=[('facs_bs_TongueOut',1)]
G9.update({
    'browInnerUp':[('facs_bs_BrowInnerUpLeft',1),('facs_bs_BrowInnerUpRight',1)],
    'cheekPuff':[('facs_bs_CheekPuffLeft',1),('facs_bs_CheekPuffRight',1)],
    'mouthPucker':[('facs_bs_MouthPurse'+vertical+side,1) for vertical in ('Upper','Lower') for side in ('Left','Right')],
    'mouthFunnel':[('facs_bs_MouthFunnel'+vertical+side,1) for vertical in ('Upper','Lower') for side in ('Left','Right')],
    'mouthClose':[('facs_bs_MouthClose'+vertical+side,1) for vertical in ('Upper','Lower') for side in ('Left','Right')],
    'mouthRollUpper':[('facs_bs_MouthRollUpper'+side,1) for side in ('Left','Right')],
    'mouthRollLower':[('facs_bs_MouthRollLower'+side,1) for side in ('Left','Right')],
    'mouthShrugUpper':[('facs_bs_MouthShrugUpper'+side,1) for side in ('Left','Right')],
    'mouthShrugLower':[('facs_bs_MouthShrugLower'+side,1) for side in ('Left','Right')],
})
for side in ('Left','Right'):
    G9['eyeWide'+side]=[('facs_bs_EyelidOpenUpper'+side,1)]
    G9['mouthPress'+side]=[('facs_bs_MouthPress'+vertical+side,1) for vertical in ('Upper','Lower')]
    # G9 eye-look controls are outputs of the eye rotations, not inputs to
    # eyeball motion. Native skinned iris measurements share G8's axis signs.
    node='l_eye' if side=='Left' else 'r_eye';sign=-1 if side=='Left' else 1
    G9['eyeLookOut'+side]=[(node+'.YRotate',16*sign)]
    G9['eyeLookIn'+side]=[(node+'.YRotate',-16*sign)]
    G9['eyeLookUp'+side]=[(node+'.XRotate',12)]
    G9['eyeLookDown'+side]=[(node+'.XRotate',-12)]

def aliases(action,rig_id):
    return [name for name,_ in (G9 if rig_id=='g9' else G8).get(action,[])]

def cache_profile(root,raw,rig_id):
    if rig_id not in RIG_LABELS or raw.get('version')!=1 or raw.get('rigId')!=rig_id:raise ValueError('Invalid facial profile generation')
    drivers=raw.get('drivers',[])
    if not isinstance(drivers,list) or len(drivers)>2000:raise ValueError('Invalid facial controls')
    ids=set();clean=[]
    for d in drivers:
        if not isinstance(d,dict):raise ValueError('Invalid facial driver')
        key=d.get('id');owner=d.get('owner');prop=d.get('property')
        if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_. -]{1,180}',key) or key in ids:raise ValueError('Invalid or duplicate facial control')
        if not isinstance(owner,str) or not (owner=='figure' or re.fullmatch(r'(?:modifier|node):[A-Za-z0-9_. -]{1,180}',owner)):raise ValueError('Unsupported facial control owner')
        if not isinstance(prop,str) or not re.fullmatch(r'[A-Za-z0-9_. -]{1,180}',prop):raise ValueError('Unsupported facial property')
        lo=finite(d.get('min'),-100000,100000,'control bound');hi=finite(d.get('max'),lo,100000,'control bound');default=finite(d.get('default'),lo,hi,'control default')
        dependencies=d.get('dependencies',[])
        if not isinstance(dependencies,list) or any(not isinstance(v,str) or len(v)>200 for v in dependencies):raise ValueError('Invalid facial dependencies')
        ids.add(key)
        # Property URLs use the owning modifier id, not its internal Value property.
        url='name://@selection'+('/'+quote(owner[5:],safe='')+'#'+quote(prop,safe='')+':' if owner.startswith('node:') else '#'+quote(owner[9:] if owner.startswith('modifier:') else key,safe='')+':')+'?value/value'
        clean.append(dict(id=key,owner=owner,property=prop,label=str(d.get('label',key))[:180],min=lo,max=hi,default=default,locked=bool(d.get('locked')),dependencies=sorted(set(dependencies)),url=url))
    by_id={d['id'].lower():d for d in clean};mappings=[]
    anatomy=raw.get('anatomy')
    if anatomy is not None and (not isinstance(anatomy,dict) or set(anatomy)!={'eyes','tongue'} or any(type(v) is not bool for v in anatomy.values())):raise ValueError('Invalid facial anatomy metadata')
    for action in (*ACTIONS,*EXTRAS):
        if action=='tongueOut' and rig_id=='g9' and anatomy is not None and not anatomy['tongue']:continue
        for name,weight in (G9 if rig_id=='g9' else G8).get(action,[]):
            driver=by_id.get(name.lower())
            if not driver or driver['locked']:continue
            if name.startswith(('lEye.','rEye.','l_eye.','r_eye.')) and (driver['owner']!='node:'+name.split('.')[0] or driver['property'].lower()!=name.split('.')[1].lower()):continue
            if weight<0 and driver['min']>=driver['default'] or weight>0 and driver['max']<=driver['default']:continue
            mappings.append(dict(action=action,driver=driver['id'],weight=weight,region=region(action)))
    paired_axes=[]
    if rig_id!='g9':
        # Older connections read paired pose controls but not eye joints.
        # Whole-axis fallback only: never apply two drivers to the same eye.
        for axis,prop,rotation,gain,signs in (
            ('horizontal','eCTRLEyesSideSide','YRotate',16/20,{'OutLeft':-1,'InLeft':1,'OutRight':1,'InRight':-1}),
            ('vertical','eCTRLEyesUpDown','XRotate',12/16,{'UpLeft':1,'DownLeft':-1,'UpRight':1,'DownRight':-1})):
            if any(m['driver'].lower() in ('leye.'+rotation.lower(),'reye.'+rotation.lower()) for m in mappings):continue
            driver=by_id.get(prop.lower())
            if not driver or driver['locked'] or not driver['min']<driver['default']<driver['max']:continue
            paired_axes.append(axis)
            for suffix,sign in signs.items():mappings.append(dict(action='eyeLook'+suffix,driver=driver['id'],weight=sign*gain/2,region='gaze'))
    if not mappings:raise ValueError('No supported facial driving controls were found. Select a base Genesis figure with its facial controls loaded; Genesis 8.1 is a separate rig and is not supported.')
    # A partial transfer is explicit; no invented rotations for missing controls.
    profile=dict(version=1,mappingVersion=9,rigId=rig_id,label=RIG_LABELS[rig_id],drivers=clean,mappings=mappings,unsupported=[a for a in (*ACTIONS,*EXTRAS) if not any(m['action']==a for m in mappings)],pairedGazeAxes=paired_axes)
    if anatomy is not None:profile['anatomy']=anatomy
    profile['signature']=hashlib.sha256(json.dumps(profile,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    atomic_json(root/'data/face-profiles'/f'{rig_id}.json',profile)
    return profile

def profile(root,rig_id):
    if rig_id not in RIG_LABELS:raise ValueError('Unsupported Genesis generation')
    result=read_json(root/'data/face-profiles'/f'{rig_id}.json')
    if result and result.get('version')==1 and result.get('mappingVersion') in (3,4,5,6,7,8):
        raw=dict(version=1,rigId=rig_id,drivers=result['drivers'])
        if 'anatomy' in result:raw['anatomy']=result['anatomy']
        result=cache_profile(root,raw,rig_id)
    if not result or result.get('version')!=1 or result.get('mappingVersion')!=9:raise ValueError('Connect or refresh the selected '+RIG_LABELS[rig_id]+' face first. Body rig connections are separate.')
    return result

def retarget(root,payload):
    canonical=source(root,payload['source']);settings=options(payload['options']);target=profile(root,payload['rigId'])
    observed={**canonical['face']['actions'],**canonical['face'].get('extras',{}),**settings.get('adjustments',{})}
    drivers={d['id']:d for d in target['drivers']};contributions={};supported=[]
    for mapping in target['mappings']:
        r=mapping['region']
        if (r in canonical['unknown'] and r not in settings['neutralRegions'] and mapping['action'] not in settings.get('adjustments',{})) or not settings['regions'][r]:continue
        if mapping['action'] not in observed:continue
        d=drivers[mapping['driver']];value=0 if r in settings['neutralRegions'] else observed[mapping['action']]*settings['strength']*mapping['weight']
        span=min(1,(d['max']-d['default']) if value>=0 else (d['default']-d['min']))
        contributions[d['id']]=contributions.get(d['id'],0)+value*span;supported.append(mapping['action'])
    channels={key:max(drivers[key]['min'],min(drivers[key]['max'],drivers[key]['default']+v)) for key,v in contributions.items()}
    if not channels:raise ValueError('No enabled, observed regions have supported target controls. Enable a supported region or use a clearer face.')
    enabled=[a for a in observed if settings['regions'][region(a)] and (region(a) not in canonical['unknown'] or region(a) in settings['neutralRegions'] or a in settings.get('adjustments',{}))]
    warnings=canonical['warnings'][:]
    missing=[a for a in enabled if a not in supported and observed[a]>.15]
    if missing:warnings.append('Not transferred on this connected figure: '+', '.join(missing))
    if observed.get('tongueOut',0)>.2 and payload['rigId']!='g9':warnings.append('Genesis 8’s base tongue extension is limited. Its supported In-Out control may keep the tip inside the lips; the preview cannot guarantee the same protrusion.')
    if any(a.startswith('eyeLook') for a in missing):warnings.append('Refresh face to read independent eye rotation controls. Head orientation remains unchanged.')
    if settings['regions']['gaze'] and target.get('pairedGazeAxes'):warnings.append('Paired eye direction uses the average of both eyes on '+', '.join(target['pairedGazeAxes'])+' axes. Refresh face for independent eye rotations.')
    if payload['rigId']=='g9':
        anatomy=target.get('anatomy',{})
        if observed.get('tongueOut',0)>.2 and not anatomy.get('tongue'):warnings.append('Genesis 9 uses a separate Mouth attachment. Load it on this figure and Refresh face to verify visible tongue support.')
        if settings['regions']['gaze'] and not anatomy.get('eyes'):warnings.append('Genesis 9 uses a separate Eyes attachment. Load it on this figure and Refresh face to verify visible eye direction.')
    warnings.append('Semantic facial transfer. The mannequin is an approximation; custom Genesis facial shape is preserved.')
    preview={}
    for m in target['mappings']:
        if m['driver'] not in channels or m['action'] not in supported:continue
        d=drivers[m['driver']];delta=channels[d['id']]-d['default'];span=min(1,d['max']-d['default'] if m['weight']>0 else d['default']-d['min'])
        amount=max(0,min(1.5,delta/(m['weight']*span))) if span>0 else 0
        intended=0 if m['region'] in settings['neutralRegions'] else observed[m['action']]*settings['strength']
        # Shared signed controls may cancel actions; they must not invent a
        # movement that was never observed, or amplify another action's dial.
        preview[m['action']]=min(preview.get(m['action'],1.5),amount,intended)
    # A paired control has one achieved direction for both eyes. Inverting
    # each half-contribution independently would double its preview movement.
    for axis,prop,gain,positive,negative in (
        ('horizontal','eCTRLEyesSideSide',-16/20,('OutLeft','InRight'),('InLeft','OutRight')),
        ('vertical','eCTRLEyesUpDown',12/16,('UpLeft','UpRight'),('DownLeft','DownRight'))):
        if axis not in target.get('pairedGazeAxes',[]):continue
        driver=next(d for d in target['drivers'] if d['id'].lower()==prop.lower())
        if driver['id'] not in channels:continue
        net=(channels[driver['id']]-driver['default'])/gain
        for suffix in positive:preview['eyeLook'+suffix]=max(0,min(1.5,net))
        for suffix in negative:preview['eyeLook'+suffix]=max(0,min(1.5,-net))
    return dict(version=1,kind='expression',rigId=payload['rigId'],profileSignature=target['signature'],source=canonical,options=settings,channels=channels,previewActions=preview,supported=len(set(supported)),total=len(enabled),warnings=warnings)

def validated_target(root,payload):
    value=payload['expression'];target=retarget(root,value)
    if value.get('profileSignature')!=target['profileSignature']:raise ValueError('The facial connection changed. Reconnect or select this generation again before exporting.')
    channels=value.get('channels')
    if not isinstance(channels,dict) or set(channels)!=set(target['channels']) or any(type(v) not in (float,int) or not math.isfinite(v) or not math.isclose(v,target['channels'][k],rel_tol=1e-10,abs_tol=1e-12) for k,v in channels.items()):raise ValueError('Expression channels changed after target fitting. Refit before exporting.')
    return target

def observation_id(image,face):
    # Subpixel precision keeps the same evidence address across JSON runtimes.
    box=[round(value*1000) for value in face.get('selectionBox',face['box'])]
    points=[[round(value*1000) for value in point] for point in face['landmarks']]
    return signature(['photo-face-v1',image,box,points])[:32]


def save(root,payload):
    canonical=source(root,payload['source']);settings=options(payload['options'])
    if payload.get('rigId') not in RIG_LABELS:raise ValueError('Unsupported Genesis generation')
    face=canonical['face']
    if canonical.get('kind')=='text':
        folder=root/'data/expressions'/canonical['sceneId']
        key=f"face-{face['id']}"
    else:
        folder=image_dir(root,canonical['imageId'])
        face['observationId']=observation_id(canonical['imageId'],face)
        key='observation-'+face['observationId']
    atomic_json(folder/(key+'-expression.json'),dict(version=1,source=canonical,options=settings,rigId=payload['rigId'],created=time.time()))
    return True


def history(root):
    import base64
    rows=[]
    for folder in (root/'data/expressions').glob('text-*'):
        if not re.fullmatch(r'text-[a-f0-9]{32}',folder.name):continue
        for path in folder.glob('face-*-expression.json'):
            record=read_json(path,{})
            if record.get('source',{}).get('kind')=='text':rows.append(dict(id=folder.name,name='Text expression · '+record['rigId'].upper(),faceId=record['source']['face']['id'],created=record['created'],solved=True,kind='expression',thumbnail='/logo.svg'))
    for folder in (root/'data/history').glob('[a-f0-9]'*24):
        files=sorted([*folder.glob('face-*-expression.json'),*folder.glob('observation-*-expression.json')])
        if not files:continue
        try:
            meta=read_json(folder/'image.json')
            thumbnail='data:image/jpeg;base64,'+base64.b64encode((folder/'thumb.jpg').read_bytes()).decode('ascii')
        except (ValueError,OSError):continue
        for file in files:
            try:
                record=read_json(file)
                face=record['source']['face'];fid=face['id']
                key=face.get('observationId')
                if key is not None and not re.fullmatch(r'[a-f0-9]{32}',key):continue
                expected=f'observation-{key}-expression.json' if key else f'face-{fid}-expression.json'
                if file.name!=expected:continue
                row=dict(id=folder.name,name=meta['name']+' · Face '+str(fid),faceId=fid,created=record['created'],solved=True,kind='expression',thumbnail=thumbnail)
                if key:row['observationId']=key
                rows.append(row)
            except (ValueError,OSError,TypeError,KeyError):continue
    return rows


def expression_record(root,payload):
    image=payload['imageId']
    fid=payload.get('faceId')
    key=payload.get('observationId')
    text=re.fullmatch(r'text-[a-f0-9]{32}',str(image)) is not None
    folder=root/'data/expressions'/image if text else image_dir(root,image)
    if key is not None:
        if text or not isinstance(key,str) or not re.fullmatch(r'[a-f0-9]{32}',key):raise ValueError('Invalid face observation identifier')
        return folder/f'observation-{key}-expression.json',text
    if type(fid) is not int or not 1<=fid<=32:raise ValueError('Invalid face identifier')
    return folder/f'face-{fid}-expression.json',text


def read(root,payload):
    path,text=expression_record(root,payload)
    record=read_json(path)
    if not record:raise ValueError('The saved expression is unavailable')
    canonical=source(root,record['source'])
    if payload.get('observationId') and canonical['face'].get('observationId')!=payload['observationId']:
        raise ValueError('The saved face observation changed.')
    from PIL import Image
    from storage import data_url
    folder=path.parent
    if text:
        photo=None
    else:
        with Image.open(folder/'source.png') as image:
            photo=dict(read_json(folder/'image.json'),url=data_url(image),people=[])
    return dict(photo=photo,source=canonical,options=options(record['options']),rigId=record['rigId'])


def remove(root,payload):
    path,_=expression_record(root,payload)
    path.unlink(missing_ok=True)
    return True


def duf(root,payload):
    expression=validated_target(root,payload);metadata=profile(root,expression['rigId']);drivers={d['id']:d for d in metadata['drivers']}
    return dict(file_version='0.6.0.0',asset_info=dict(id='/PoseSnap/Expression.duf',type='preset_pose',contributor=dict(author='Aitha'),revision='1.0'),scene=dict(animations=[dict(url=drivers[key]['url'],keys=[[0,value]]) for key,value in expression['channels'].items()]))

def export(root,payload):
    destination=Path(payload['path'])
    if destination.suffix.lower()!='.duf':destination=destination.with_suffix('.duf')
    atomic_json(destination,duf(root,payload));return dict(path=str(destination))

def handoff(root,payload,progress,connect=False,zero=False):
    executable=Path(payload['executable'])
    if not executable.is_file() or executable.name.lower()!='dazstudio.exe':raise ValueError('Choose DAZ Studio 6’s DAZStudio.exe in Settings → DAZ Studio.')
    rig_id=payload['rigId'] if connect or zero else validated_target(root,payload)['rigId']
    if rig_id not in RIG_LABELS:raise ValueError('Unsupported Genesis generation')
    job_id=uuid.uuid4().hex;folder=root/'temp/daz'/job_id;folder.mkdir(parents=True)
    active=payload.get('_jobId',job_id)
    if not isinstance(active,str) or not re.fullmatch(r'[A-Za-z0-9-]{1,79}',active):raise ValueError('Invalid expression job')
    cancel=root/'temp/jobs'/(active+'.cancel');cancel.parent.mkdir(parents=True,exist_ok=True)
    ack=folder/'ack.json';status=folder/'status.json';config=dict(version=1,rigId=rig_id,label=RIG_LABELS[rig_id],jobId=job_id,ack=str(ack).replace('\\','/'),status=str(status).replace('\\','/'),cancel=str(cancel).replace('\\','/'),connect=connect,zero=zero)
    if not connect and not zero:config.update(expression=validated_target(root,payload),profile=profile(root,rig_id))
    script=folder/('connect-expression.dsa' if connect else 'zero-expression.dsa' if zero else 'apply-expression.dsa')
    script.write_text(Path(__file__).with_name('expression_figure.dsa').read_text(encoding='utf-8').replace('__POSESNAP_CONFIG__',json.dumps(config,ensure_ascii=True,allow_nan=False)),encoding='utf-8')
    progress('Reading selected facial controls' if connect else 'Waiting for DAZ to zero PoseSnap controls' if zero else 'Waiting for DAZ to apply expression',25)
    from daz_handoff import daz_running, wait_for_ack
    was_running=daz_running(executable) is True
    launch=subprocess.Popen([str(executable),str(script)],cwd=executable.parent)
    result=wait_for_ack(ack,cancel,status,job_id,executable,launch,progress,was_running)
    if connect:result['profile']=cache_profile(root,result['profile'],rig_id)
    progress('Face connected' if connect else 'Applied controls zeroed and verified' if zero else 'Expression applied and verified',100);return result
