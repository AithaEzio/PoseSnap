"""Anatomical observations and final-target image agreement (centimetres)."""
import copy, hashlib, json
import numpy as np
from retarget import fk, source_map
from studio import semantics, rest_frame
from wholebody import BODY, HAND

AXES=np.array([1.,-1.,-1.])
MHR={**dict(zip(BODY.values(),[5,6,7,8,62,41,9,10,11,12,13,14])),
     **dict(zip(('l_bigtoe','l_smalltoe','l_heel','r_bigtoe','r_smalltoe','r_heel'),range(15,21)))}
for side,start in (('r',21),('l',42)):
    for finger in ('thumb','index','middle','ring','pinky'):
        offset=('thumb','index','middle','ring','pinky').index(finger)*4
        # MHR lists tip, DIP, PIP, MCP; COCO whole-body lists MCP, PIP, DIP, tip.
        for part,delta in (('tip',0),(1,3),(2,2),(3,1)):MHR[f'{side}_{finger}{part}']=start+offset+delta

def canonical(source):
    if source.get('measurements') is not None:return copy.deepcopy(source['measurements'])
    return [dict(name=BODY[p['coco']],region='body',xy=p['xy'],weight=p['weight'],known=True,provenance='rtmo',personId=source['personId'])
            for p in source.get('evidence',[]) if p.get('coco') in BODY]

def overrides(groups,corrections,size):
    groups=copy.deepcopy(groups)
    if not isinstance(corrections,list) or len(corrections)>300:raise ValueError('Too many landmark corrections.')
    for correction in corrections:
        if correction.get('name') not in MHR:raise ValueError('Unsupported correction landmark.')
        group=next((g for g in groups if g and g[0]['personId']==correction.get('personId')),None)
        if group is None:raise ValueError('Correction belongs to another person.')
        name=correction['name'];region='body' if name in BODY.values() else name[0]+('_foot' if name.endswith(('heel','bigtoe','smalltoe')) else '_hand')
        xy=np.asarray(correction.get('xy',[0,0]),dtype=float)
        if xy.shape!=(2,) or not np.isfinite(xy).all() or np.any(xy<0) or np.any(xy>size):raise ValueError('Place corrected landmarks inside the photograph.')
        item=dict(name=name,personId=correction['personId'],xy=xy.tolist(),known=not correction.get('unknown',False),weight=1.,region=region,provenance='user')
        group[:]=[p for p in group if p['name']!=name]+[item]
    return groups

def target_points(pose,include_frames=False,rest=None):
    """Fixed anatomical attachments. Never stretch bones or mannequin geometry."""
    rig=pose['rig']; mapping=semantics(rig);nodes={n['id']:n for n in rig['nodes']}
    # G8 twist centres lie along the limb (often near its midpoint). The
    # anatomical joint centre belongs to the bend node; G9 uses one node.
    for side in ('l','r'):
        for part,suffix in (('upperarm','ShldrBend'),('forearm','ForearmBend'),('thigh','ThighBend')):
            if side+suffix in nodes:mapping[side+'_'+part]=side+suffix
    channels=dict(pose['rotations']);root=next(n['id'] for n in rig['nodes'] if not n['parent']);channels[root]=pose.get('rootRotation',[0,0,0])
    world,positions=fk(rig,channels,pose.get('translation',[0,0,0]),rest=rest);points={};dependencies={}
    def attach(name,key,local=None):
        node=mapping.get(key)
        if node:
            points[name]=positions[node].copy()+(world[node]@local if local is not None else 0);dependencies[name]=node
    for side in ('l','r'):
        for part,key in (('shoulder','upperarm'),('elbow','forearm'),('wrist','hand'),('hip','thigh'),('knee','shin'),('ankle','foot')):
            attach(side+'_'+part,side+'_'+key)
        hand=side+'_hand'
        for finger in ('thumb','index','middle','ring','pinky'):
            mapped='mid' if finger=='middle' else finger
            for part in (1,2,3):attach(f'{side}_{finger}{part}',f'{side}_{mapped}{part}')
            tip=mapping.get(f'{side}_{mapped}3')
            if tip:attach(f'{side}_{finger}tip',f'{side}_{mapped}3',np.asarray(nodes[tip]['end'])-nodes[tip]['center'])
        palm=mapping.get(hand);middle=mapping.get(side+'_mid1')
        if palm and middle:attach(side+'_palm',hand,(np.asarray(nodes[middle]['center'])-nodes[palm]['center'])*.65)
        elbow=mapping.get(side+'_forearm')
        if elbow and palm:attach(side+'_forearm',side+'_forearm',(np.asarray(nodes[palm]['center'])-nodes[elbow]['center'])*.5)
        foot=mapping.get(side+'_foot');toes=mapping.get(side+'_toes')
        if foot:
            origin=np.asarray(nodes[foot]['center'],dtype=float);front=np.asarray(nodes[toes]['end'] if toes else nodes[foot]['end'],dtype=float);delta=front-origin
            length=max(8.,np.linalg.norm(delta));horizontal=delta.copy();horizontal[1]=0
            if np.linalg.norm(horizontal)<1e-5:horizontal=np.array([0.,0.,1.])
            horizontal/=np.linalg.norm(horizontal);width=np.cross([0.,1.,0.],horizontal)*length*.17
            # Heel and toe sole points retain ankle height, with one rigid sole offset.
            sole=np.array([0.,-max(3.,origin[1]-min(origin[1],front[1])),0.])
            attach(side+'_heel',side+'_foot',sole-horizontal*length*.23)
            for name,sign in (('bigtoe',1),('smalltoe',-1)):
                local=sole+horizontal*length+width*sign*(1 if side=='l' else -1)
                # Toe evidence must respond to toe driving channels as well as the ankle.
                if toes:attach(side+'_'+name,side+'_toes',origin+local-np.asarray(nodes[toes]['center']))
                else:attach(side+'_'+name,side+'_foot',local)
    hip=mapping.get('hip');chest=mapping.get('spine4') or mapping.get('spine3')
    if hip and chest:
        points['torso']=(positions[hip]+positions[chest])/2;dependencies['torso']=chest
    if include_frames:return points,dependencies,(world,positions)
    return points,dependencies

def project_target(points,camera):
    points=(np.asarray(points)+np.asarray(camera['originCm']))*AXES
    k=np.asarray(camera['intrinsics']);depth=np.maximum(points[...,2],1.)
    return points[...,:2]/depth[...,None]*[k[0,0],k[1,1]]+[k[0,2],k[1,2]]

def quality(source,pose,camera):
    measured=canonical(source);actual,_=target_points(pose);height=max(24.,source.get('personBox',[0,0,0,source['imageSize'][1]])[3]-source.get('personBox',[0,0,0,0])[1])
    regions={};markers=[]
    for region,expected in (('body',12),('l_hand',21),('r_hand',21),('l_foot',3),('r_foot',3)):
        items=[p for p in measured if p['region']==region and p.get('known',True) and p['name'] in actual]
        if region=='body':tolerance=max(2.,height*.02)
        else:
            xy=np.array([p['xy'] for p in items]);tolerance=max(2.,float(np.linalg.norm(np.ptp(xy,axis=0)))*.05) if len(xy)>1 else 2.
        errors=[]
        for item in items:
            predicted=project_target(actual[item['name']],camera);error=float(np.linalg.norm(predicted-item['xy']));errors.append(error)
            markers.append(dict(name=item['name'],region=region,personId=pose['personId'],xy=item['xy'],predicted=predicted.tolist(),errorPx=error,provenance=item.get('provenance','rtmo')))
        regions[region]=dict(matched=float(np.mean(np.asarray(errors)<=tolerance)) if errors else None,count=len(errors),expected=expected,tolerancePx=tolerance,meanErrorPx=float(np.mean(errors)) if errors else None)
    all_errors=[p for p in markers];matched=[r['matched']*r['count'] for r in regions.values() if r['count']]
    count=sum(r['count'] for r in regions.values())
    return dict(version=2,detection=source.get('quality',{}).get('detection',0),stage='target',regions=regions,
                visible=dict(matched=sum(matched)/count if count else None,count=count,threshold=.02,meanError=None),markers=markers,
                coverage=dict(observed=count,expected=60),depth='Single-image depth remains uncertain',handAcceptance=source.get('handAcceptance'),prompts=source.get('quality',{}).get('prompts',0))

def reference_camera(source,origin):
    return dict(version=1,intrinsics=source['camera'],imageSize=source['imageSize'],originCm=np.asarray(origin).tolist())

def stamp(value):return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False).encode()).hexdigest()[:24]
