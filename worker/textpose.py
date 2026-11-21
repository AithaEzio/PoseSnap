"""Checked Kimodo body goals, bounded fitting and accepted-history storage.

Only body and explicitly enabled finger channels are generated. No scale or identity writes.
"""
import copy
import hashlib
import json
import math
import re
import time
import uuid
from pathlib import Path
from storage import atomic_json, read_json

VERSION = 9
from hand_design import PARTS as FINGER_PARTS, MOVES as HAND_MOVES
RECIPES = ('standing', 'relaxed', 'confident', 'happy', 'sad', 'defensive', 'seated', 'crouch', 'kneel', 'lying', 'walking', 'running', 'dance', 'jump')
PARTS = ('torso', 'head', 'l_arm', 'r_arm', 'l_forearm', 'r_forearm', 'l_hand', 'r_hand', 'l_leg', 'r_leg', 'l_knee', 'r_knee', 'l_foot', 'r_foot', *FINGER_PARTS)
MOVES = tuple(dict.fromkeys(('raise', 'lower', 'forward', 'back', 'bend', 'straighten', *HAND_MOVES, 'turn_left', 'turn_right', 'lean_forward', 'lean_back', 'upright')))
INTERACTIONS = ('none', 'front_hug', 'side_hug', 'handhold', 'shoulder')
REGIONS = ('body', 'hips', 'torso', 'head', 'arms', 'hands', 'legs', 'feet', 'fingerShapes', *PARTS)


def environment(root, actors):
    from rigs import profile
    from hand_design import signature as hand_signature
    from kimodo_runtime import pack_signature
    from qualification import generation_signature
    return dict(version=2, profiles=[dict(id=a['id'],rigId=a['rigId'],body=signature(profile(root,a['rigId']))) for a in actors],
                handLibrary=hand_signature(),bodyPack=pack_signature(),implementation=generation_signature(),actionCatalogue=VERSION)


def signature(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def task(payload):
    from kimodo_runtime import provider
    from body_profiles import PROFILES
    provider(payload)
    if payload.get('output','pose')!='pose' or any(k in payload for k in ('reference','useAi')):
        raise ValueError('Text to Pose now creates body poses with Kimodo. Image references, facial output and prompt-engine options are no longer supported.')
    mode=payload.get('mode','create');actors=payload.get('actors',[]);prompt=payload.get('prompt','')
    if mode != 'create' or 'baselines' in payload:raise ValueError('Text to Pose creates new body poses. Open an accepted pose in Pose Studio to edit its joints.')
    if not isinstance(actors,list) or not 1<=len(actors)<=2:raise ValueError('Choose one or two numbered actors.')
    if any(not isinstance(a,dict) or a.get('id')!=i+1 or a.get('rigId') not in ('g8f','g8m','g9') for i,a in enumerate(actors)):raise ValueError('Actor identities or Genesis generations are invalid.')
    if not isinstance(prompt,str) or not prompt.strip() or len(prompt)>2000:raise ValueError('Describe your pose using 1–2,000 characters.')
    if payload.get('style','natural') not in PROFILES:raise ValueError('Choose a supported Pose character profile.')
    if type(payload.get('handShapes',False)) is not bool:raise ValueError('Invalid approximate hand shapes option.')
    if type(payload.get('candidateCount',1)) is not int or payload.get('candidateCount',1) not in (1,3):raise ValueError('Request one preview or three choices.')
    if type(payload.get('variationSeed',0)) is not int or not 0<=payload.get('variationSeed',0)<2**32:raise ValueError('Invalid pose variation seed.')
    return 'pose',mode,actors,prompt.strip()


def capability(root,payload):
    from rigs import profile
    output,mode,actors,prompt=task(payload)
    return dict(version=VERSION,output=output,mode=mode,actors=[dict(id=a['id'],rigId=a['rigId'],rigSignature=signature(profile(root,a['rigId']))) for a in actors],
                environment=environment(root,actors),generation=dict(style=payload.get('style','natural'),handShapes=payload.get('handShapes',False),seed=payload.get('variationSeed',0),count=payload.get('candidateCount',1),creative=bool(payload.get('creative'))))


def validate_intent(value, payload):
    import expression
    output, mode, actors, _ = task(payload)
    if not isinstance(value, dict) or value.get('status') not in ('plan', 'clarify', 'unsupported'):
        raise ValueError('The interpretation was incomplete. Try a shorter instruction or a supported example.')
    if value['status'] != 'plan':
        question = value.get('message', '')
        if not isinstance(question, str) or not 1 <= len(question) <= 500:
            raise ValueError('The interpreter returned an invalid clarification.')
        return dict(status=value['status'], message=question)
    if set(value) - {'status', 'actors', 'interaction', 'summary', 'assumptions','observations'}:
        raise ValueError('The interpreter returned unsupported operations.')
    rows = value.get('actors', [])
    if not isinstance(rows, list) or len(rows) != len(actors):
        raise ValueError('The interpretation changed the number of selected actors.')
    clean = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict) or row.get('id') != actors[i]['id'] or set(row) - {'id', 'recipe', 'changes', 'preserve', 'expression', 'support','gaze','design','bodyDescription'}:
            raise ValueError('The interpretation contains an unknown actor or operation.')
        recipe = row.get('recipe', 'standing')
        from kimodo_runtime import provider
        kimodo = provider(payload) == 'kimodo'
        if recipe not in RECIPES and not (recipe == 'kimodo' and kimodo):
            raise ValueError('That body posture is not supported.')
        description = row.get('bodyDescription')
        if description is not None and (not kimodo or not isinstance(description,str) or not 1 <= len(description) <= 2000):
            raise ValueError('Invalid Kimodo body description.')
        if recipe == 'kimodo' and description != payload['prompt'].strip():
            raise ValueError('Kimodo must receive the user direction without a silent rewrite.')
        changes = row.get('changes', []); preserve = row.get('preserve', [])
        if not isinstance(changes, list) or len(changes) > 24 or not isinstance(preserve, list) or len(preserve) > 20 or any(p not in REGIONS for p in preserve):
            raise ValueError('Invalid body changes or preservation constraints.')
        for c in changes:
            if not isinstance(c, dict) or set(c) != {'part', 'movement', 'amount'} or c['part'] not in PARTS or c['movement'] not in MOVES:
                raise ValueError('An unsupported body movement was requested.')
            expression.finite(c['amount'], 0, 1, 'movement intensity')
            from hand_design import allowed as hand_allowed
            allowed=hand_allowed(c['part']) if c['part'] in FINGER_PARTS else ('upright','lean_forward','lean_back','turn_left','turn_right') if c['part'] in ('torso','head') else (*hand_allowed(c['part']),'raise','lower','forward','back','bend','straighten') if c['part'].endswith('hand') else ('raise','lower','forward','back','bend','straighten')
            if not payload.get('handShapes',False) and (c['part'] in FINGER_PARTS or c['movement'] in hand_allowed(c['part'])):raise ValueError('Enable Approximate hand shapes before changing finger gestures.')
            if c['movement'] not in allowed:raise ValueError('That movement does not apply to '+c['part']+'. Try a supported example.')
        from textconstraints import positional_part
        changes=[dict(c,part=positional_part(c['part'],c['movement'])) for c in changes]
        by_part={}
        for change in changes:
            key=change['part'];operation=change['movement']
            if key in by_part and by_part[key]!=operation:raise ValueError('Conflicting movements were requested for '+key+'. Choose one final state.')
            by_part[key]=operation
        changes=list({(c['part'],c['movement']):c for c in changes}.values())
        changes=[c for c in changes if c['amount']>0]
        facial = row.get('expression', {})
        if not isinstance(facial, dict) or set(facial) - set((*expression.ACTIONS, *expression.EXTRAS)):
            raise ValueError('An unsupported facial movement was requested.')
        facial = {k: expression.finite(v, 0, 1, 'facial intensity') for k, v in facial.items()}
        support = row.get('support', {})
        if not isinstance(support, dict) or set(support) - {'l', 'r'} or any(s not in ('flat', 'heel', 'toe', 'air') for s in support.values()):
            raise ValueError('Unknown foot support instruction.')
        if output == 'expression' and (changes or support or preserve):
            raise ValueError('Expression-only instructions cannot change the body.')
        if facial:
            raise ValueError('Text to Pose cannot generate facial expressions.')
        gaze=row.get('gaze','keep')
        if gaze not in ('keep','partner','camera','forward') or output=='pose' and gaze!='keep':raise ValueError('Text to Pose cannot generate eye directions.')
        from pose_design import validate as validate_design
        design=validate_design(row.get('design'))
        if design and (mode!='create' or output=='expression'):
            raise ValueError('Creative body design is only available when creating a body pose.')
        item=dict(id=row['id'], recipe=recipe, changes=changes, preserve=list(dict.fromkeys(preserve)), expression=facial, support=support,gaze=gaze)
        if description is not None:item['bodyDescription']=description
        if design:item['design']=design
        clean.append(item)
    interaction = value.get('interaction', 'none')
    if interaction not in INTERACTIONS or interaction != 'none' and (len(actors) != 2 or output == 'expression'):
        raise ValueError('This interaction needs two selected body actors.')
    summary = value.get('summary', ''); assumptions = value.get('assumptions', [])
    if not isinstance(summary, str) or len(summary) > 500 or not isinstance(assumptions, list) or len(assumptions) > 6 or any(not isinstance(s, str) or len(s) > 250 for s in assumptions):
        raise ValueError('Invalid interpretation notes.')
    observations=value.get('observations',[])
    if not isinstance(observations,list) or len(observations)>12:raise ValueError('Invalid visible-pose observations.')
    for observation in observations:
        if not isinstance(observation,dict) or set(observation)!={'actor','part','state'} or type(observation['actor']) is not int or observation['actor'] not in [a['id'] for a in actors] or observation['part'] not in ('l_arm','r_arm','l_leg','r_leg','torso','head') or observation['state'] not in ('raised','lowered','bent','upright','leaning','unknown'):
            raise ValueError('Unsupported visible-pose observation.')
    result=dict(status='plan', actors=clean, interaction=interaction, summary=summary, assumptions=assumptions)
    if observations:result['observations']=copy.deepcopy(observations)
    return result


def basic_intent(payload):
    """Literal body goals; free-form creation still reaches Kimodo."""
    _,mode,actors,prompt=task(payload)
    from textconstraints import actor_text,limbs,interaction_request
    from hand_design import phrases
    from instructions import positive_text
    text=prompt.lower()
    if re.search(r'\b(?:wink|blink|squint|eyelids?|eyes?|mouth|smil\w*|cheeks?|tongue|eyebrows?)\b',positive_text(text)):
        return dict(status='unsupported',message='Kimodo creates body poses. Facial expressions are not generated here; use Expression studio for expressions.')
    if len(actors)==2 and re.search(r'\b(she|he|her|his|they)\b',text) and 'both' not in text and not re.search(r'\b(?:person|actor) [12]\b',text):
        return dict(status='clarify',message='Name Person 1, Person 2, or both so each body direction has an owner.')
    interaction=interaction_request(text)
    if interaction!='none' and len(actors)!=2:return dict(status='clarify',message='Choose two characters for this interaction.')
    rows=[]
    for actor in actors:
        clause=actor_text(text,actor['id'],len(actors));hands=phrases(clause)
        if re.search(r'\b(?:fingers?|thumbs?|peace sign|fist|pinch|clench|cupped)\b',positive_text(clause)) and not hands and not re.search(r'\b(?:keep|preserve)\b',clause):
            return dict(status='clarify',message='Name the left hand, right hand or both hands and one supported gesture or finger movement. Your accepted pose is kept.')
        if hands and not payload.get('handShapes',False):return dict(status='clarify',message='Enable Approximate hand shapes to request finger gestures, or remove the hand-shape instruction. Your accepted pose is kept.')
        preserve=[]
        for keep in re.finditer(r'\b(?:keep|preserve)\s+([^.;,]+)',clause):
            scope=re.split(r'\band\s+(?:raise|lower|bend|open|close|straighten|lean|turn)\b',keep[1])[0]
            preserve.extend(name for name in ('body','hips','feet','legs','torso','head','hands','arms') if re.search(r'\b'+name+r'\b',scope))
        row=dict(id=actor['id'],recipe='kimodo',bodyDescription=prompt,changes=[*limbs(clause),*hands],preserve=list(dict.fromkeys(preserve)),expression={},support={})
        rows.append(row)
    return validate_intent(dict(status='plan',actors=rows,interaction=interaction,summary=prompt,assumptions=[]),payload)


def frame(pose):
    from retarget import fk
    root = next(n['id'] for n in pose['rig']['nodes'] if not n['parent'])
    return fk(pose['rig'], dict(pose['rotations'], **{root: pose.get('rootRotation',[0.,0.,0.])}), pose['translation'])


def bounded_rotation(pose, node, desired):
    """Fit free channels around the current locked/driven raw values."""
    from retarget import constrained_rotation
    local=copy.deepcopy(node);current=pose['rotations'].get(node['id'],[0.,0.,0.])
    for i,axis in enumerate('xyz'):
        limit=local['limits'].get(axis,{})
        if limit.get('locked') or axis in node.get('driven',[]):
            local['limits'][axis]=dict(limit,locked=False,clamped=True,min=current[i],max=current[i])
    values,limited=constrained_rotation(local,desired)
    if limited and any(v.get('locked') for v in node['limits'].values()):
        warning='Some movements are limited by locked joints. Existing locked values are retained.'
        if warning not in pose['warnings']:pose['warnings'].append(warning)
    return values


def root_rotation(pose, target):
    node=next(n for n in pose['rig']['nodes'] if not n['parent'])
    values=list(pose['rootRotation'])
    for i,axis in enumerate('xyz'):
        limit=node['limits'].get(axis,{})
        if limit.get('locked') or axis in node.get('driven',[]):
            if abs(target[i]-values[i])>.1:raise ValueError('That change conflicts with a locked figure orientation. The accepted result is kept.')
        else:values[i]=max(limit['min'],min(limit['max'],target[i])) if limit.get('clamped') else target[i]
    pose['rootRotation']=values


def aim(pose, semantic, direction):
    import numpy as np
    from studio import semantics
    from retarget import align, rotation
    mapping = semantics(pose['rig']); name = mapping.get(semantic)
    if not name: raise ValueError('This rig does not support '+semantic)
    # Bend nodes drive anatomical swing on Genesis 8; twist remains separate.
    suffix = {'upperarm': 'ShldrBend', 'forearm': 'ForearmBend', 'thigh': 'ThighBend'}.get(semantic[2:])
    nodes = {n['id']: n for n in pose['rig']['nodes']}
    if suffix and semantic[0]+suffix in nodes: name = semantic[0]+suffix
    node = nodes[name]; world, _ = frame(pose)
    axis = np.asarray(node['end'])-node['center']
    desired = align(world[name]@axis, np.asarray(direction))@world[name]
    orient = rotation(node['orientation']); parent = world.get(node['parent'], np.eye(3))
    pose['rotations'][name] = bounded_rotation(pose,node,orient.T@parent.T@desired@orient)


def turn_head(pose, degrees):
    import numpy as np
    from scipy.spatial.transform import Rotation
    from retarget import rotation
    from studio import semantics
    name=semantics(pose['rig'])['head'];node=next(n for n in pose['rig']['nodes'] if n['id']==name)
    frames,_=frame(pose);orient=rotation(node['orientation']);parent=frames.get(node['parent'],np.eye(3))
    desired=Rotation.from_euler('y',degrees,degrees=True).as_matrix()@frames[name]
    pose['rotations'][name]=bounded_rotation(pose,node,orient.T@parent.T@desired@orient)


def neutral(root, rig_id, image_id, actor):
    from rigs import profile, pose_bone
    rig = profile(root, rig_id)
    return dict(version=1, rigId=rig_id, label='Text pose', imageId=image_id, personId=actor, sourceId=rig['sourceId'], rig=rig, origin='editor', studio=True, edited=True,
                rotations={n['id']: [0., 0., 0.] for n in rig['nodes'] if pose_bone(n)}, translation=[0., 0., 0.], rootRotation=[0., 0., 0.], warnings=[], handRefinement=False)


def recipe(pose, name):
    for side, sign in [('l', 1), ('r', -1)]:
        aim(pose, side+'_upperarm', [sign*.15, -1, 0]); aim(pose, side+'_forearm', [sign*.1, -1, .1])
        if name in ('happy', 'jump', 'dance'): aim(pose, side+'_upperarm', [sign*.5, 1, .1]); aim(pose, side+'_forearm', [sign*.25, 1, .2])
        if name in ('seated', 'crouch', 'running', 'jump'):
            aim(pose, side+'_thigh', [sign*.1, -.25 if name != 'jump' else .2, 1])
            aim(pose, side+'_shin', [0, -1, -.8 if name in ('crouch', 'kneel', 'jump') else .1])
        if name == 'kneel':
            aim(pose,side+'_thigh',[sign*.08,-1,0]);aim(pose,side+'_shin',[0,-.1,-1]);aim(pose,side+'_foot',[0,-.5,-1])
        elif name in ('seated','crouch','walking','running'):
            aim(pose,side+'_foot',[0,0,1])
        if name == 'defensive': aim(pose, side+'_upperarm', [sign*.15, -.5, 1]); aim(pose, side+'_forearm', [0, 1, .5])
        if name == 'confident': aim(pose, side+'_upperarm', [sign*.6, -1, 0]); aim(pose, side+'_forearm', [-sign*.5, .3, .1])
        if name in ('walking', 'running'):
            aim(pose, side+'_thigh', [sign*.05, -1, sign*.65]); aim(pose, side+'_upperarm', [sign*.1, -.7, -sign*.8])
    if name == 'lying': root_rotation(pose,[-90.,pose['rootRotation'][1],pose['rootRotation'][2]])
    if name == 'sad': aim(pose, 'head', [0, .8, .4])


def changed(pose, change):
    import numpy as np
    from studio import semantics
    part, movement, amount = change['part'], change['movement'], change['amount']
    if part in ('torso', 'head'):
        if movement not in ('upright', 'lean_forward', 'lean_back', 'turn_left', 'turn_right'):
            raise ValueError('Use upright, lean forward/back, or turn left/right for torso/head changes.')
        if movement.startswith('turn_'):
            if part == 'torso': root_rotation(pose,[pose['rootRotation'][0],pose['rootRotation'][1]+(1 if movement=='turn_left' else -1)*45*amount,pose['rootRotation'][2]])
            else: turn_head(pose,(1 if movement=='turn_left' else -1)*45*amount)
        else: aim(pose, 'spine1' if part == 'torso' else 'head', [0, 1, (0 if movement == 'upright' else 1 if movement == 'lean_forward' else -1)*.6*amount])
        return
    side, region = part.split('_', 1); sign = 1 if side == 'l' else -1
    from hand_design import allowed as hand_allowed, apply as apply_hand
    if movement in hand_allowed(part):
        apply_hand(pose, change)
        return
    semantic = side+'_'+{'arm': 'upperarm', 'leg': 'thigh', 'knee': 'shin', 'forearm': 'forearm', 'foot': 'foot', 'hand': 'hand'}[region]
    directions = {'raise': [sign*.15, 1, .1], 'lower': [sign*.1, -1, 0], 'forward': [0, -.2, 1], 'back': [0, -.2, -1], 'bend': [0, .4, 1], 'straighten': [0, -1, 0]}
    if movement not in directions: raise ValueError('Unsupported movement for '+part+'. Use a supported example or describe a different goal.')
    nodes = {n['id']: n for n in pose['rig']['nodes']}; mapping = semantics(pose['rig']); node = nodes[mapping[semantic]]
    worlds, _ = frame(pose)
    target = worlds[mapping['hip']]@np.asarray(directions[movement], dtype=float)
    current = worlds[node['id']]@(np.asarray(node['end'])-node['center']); current /= np.linalg.norm(current)
    aim(pose, semantic, current*(1-amount)+target/np.linalg.norm(target)*amount)
    if region == 'arm' and movement in ('raise','lower','forward','back'):
        # Finish the chain: rotating only the shoulder can leave a bent wrist up.
        worlds,_=frame(pose);forearm=nodes[mapping[side+'_forearm']]
        current=worlds[forearm['id']]@(np.asarray(forearm['end'])-forearm['center']);current/=np.linalg.norm(current)
        aim(pose,side+'_forearm',current*(1-amount)+target/np.linalg.norm(target)*amount)
        if amount>=.9:fit_arm_direction(pose,side,target/np.linalg.norm(target))


def fit_arm_direction(pose, side, direction):
    """Bounded collar/bend/twist solve; torso and local wrist/finger dials stay fixed."""
    import numpy as np
    from scipy.optimize import least_squares
    from studio import semantics
    mapping=semantics(pose['rig']);nodes={n['id']:n for n in pose['rig']['nodes']};_,positions=frame(pose)
    upper=side+'ShldrBend' if side+'ShldrBend' in nodes else mapping[side+'_upperarm']
    elbow=side+'ForearmBend' if side+'ForearmBend' in nodes else mapping[side+'_forearm'];hand=mapping[side+'_hand']
    shoulder=positions[upper];arm_length=np.linalg.norm(positions[elbow]-shoulder);reach=arm_length+np.linalg.norm(positions[hand]-positions[elbow])
    if np.dot(positions[hand]-shoulder,direction)>.94*reach:return
    variables=[];initial=[];lower=[];higher=[]
    chain=[mapping[side+'_shoulder'],upper,mapping[side+'_upperarm'],elbow]
    for name in dict.fromkeys(chain):
        node=nodes[name]
        for axis,channel in enumerate('xyz'):
            limit=node['limits'].get(channel,{})
            if limit.get('locked') or channel in node.get('driven',[]):continue
            lo=limit.get('min',-180) if limit.get('clamped') else -180;hi=limit.get('max',180) if limit.get('clamped') else 180
            if hi-lo<1e-6:continue
            variables.append((name,axis));initial.append(pose['rotations'][name][axis]);lower.append(lo);higher.append(hi)
    if not variables:return
    initial=np.clip(initial,lower,higher)
    def install(values):
        for (name,axis),value in zip(variables,values):pose['rotations'][name][axis]=float(value)
    def residual(values):
        install(values);_,points=frame(pose)
        return np.concatenate(((points[hand]-(shoulder+direction*reach))/reach*8.,(points[elbow]-(shoulder+direction*arm_length))/arm_length*2.,(values-initial)/180*.05))
    # An elevated collar can put the first aim at a joint-limit boundary. One
    # neutral seed escapes that local solution; no unbounded retry/inference.
    start_cost=np.linalg.norm(residual(initial));best=initial.copy();best_cost=start_cost
    for seed in (initial,np.clip(np.zeros(len(initial)),lower,higher)):
        fit=least_squares(residual,seed,bounds=(lower,higher),max_nfev=60)
        cost=np.linalg.norm(fit.fun)
        if cost<best_cost:best=fit.x.copy();best_cost=cost
    install(best)


def verify_directions(pose, changes):
    """Check the fitted wrist, rather than trusting the language summary."""
    import numpy as np
    from studio import semantics
    mapping=semantics(pose['rig']);worlds,positions=frame(pose)
    for change in changes:
        if change['part'] not in ('l_arm','r_arm') or change['movement'] not in ('raise','lower','forward','back') or change['amount']<.9:continue
        side=change['part'][0]
        shoulder=positions.get(side+'ShldrBend',positions[mapping[side+'_upperarm']])
        elbow=positions.get(side+'ForearmBend',positions[mapping[side+'_forearm']]);wrist=positions[mapping[side+'_hand']]
        reach=np.linalg.norm(elbow-shoulder)+np.linalg.norm(wrist-elbow)
        delta=worlds[mapping['hip']].T@(wrist-shoulder)
        vertical=change['movement'] in ('raise','lower')
        direction=1 if change['movement'] in ('raise','forward') else -1
        projection=direction*delta[1 if vertical else 2]
        if projection<(.5 if vertical else .25)*reach or vertical and projection<.85*np.linalg.norm(delta):
            label={'raise':'raised','lower':'lowered','forward':'forward','back':'backward'}[change['movement']]
            raise ValueError('The '+('left' if side=='l' else 'right')+' arm could not reach the requested '+label+' position within its joint limits. Your accepted result is kept.')


def protected(before, after, regions):
    import numpy as np
    from scipy.spatial.transform import Rotation
    from studio import semantics
    old_frames, old = frame(before); new_frames, new = frame(after); mapping = semantics(before['rig'])
    groups = {'body': list(mapping), 'hips':['hip','pelvis'], 'torso': ['hip', 'pelvis', 'spine1', 'spine2', 'spine3', 'spine4'], 'head': ['head'], 'arms': ['l_upperarm', 'r_upperarm', 'l_forearm', 'r_forearm'], 'hands': ['l_hand', 'r_hand'], 'legs': ['l_thigh', 'r_thigh', 'l_shin', 'r_shin'], 'feet': ['l_foot', 'r_foot', 'l_toes', 'r_toes']}
    aliases = {'arm': 'upperarm', 'leg': 'thigh', 'knee': 'shin'}
    names = set()
    if 'fingerShapes' in regions:
        fingers={mapping[k] for k in mapping if re.search(r'(?:thumb|index|mid|ring|pinky)[123]$',k)}
        if any(np.max(np.abs(np.asarray(before['rotations'][n])-after['rotations'][n]))>.1 for n in fingers):
            raise ValueError('That change would alter preserved finger shapes. Your accepted result is kept.')
    for region in regions:
        keys = [] if region=='fingerShapes' else groups.get(region, [region[:2]+aliases.get(region[2:], region[2:])])
        names.update(mapping[k] for k in keys if k in mapping)
    # A protected wrist alone does not protect its articulated finger descendants.
    for side in ('l', 'r'):
        if 'body' in regions or 'hands' in regions or side+'_hand' in regions:
            names.update(mapping[k] for k in mapping if k.startswith(side+'_') and any(k[len(side)+1:].startswith(f) for f in ('thumb','index','mid','ring','pinky')))
    for part in regions:
        if part in FINGER_PARTS:
            names.update(mapping[part+str(i)] for i in (1,2,3) if part+str(i) in mapping)
    for name in names:
        if np.linalg.norm(old[name]-new[name]) > .05 or Rotation.from_matrix(new_frames[name]@old_frames[name].T).magnitude() > math.radians(.1):
            raise ValueError('That change would move a preserved region. Adjust the instruction or preservation choice.')
    for name, pin in before.get('pins', {}).items():
        if 'position' in pin and np.linalg.norm(new[name]-pin['position']) > .05 or 'rotation' in pin and Rotation.from_matrix(new_frames[name]@Rotation.from_quat(pin['rotation']).as_matrix().T).magnitude() > math.radians(.1):
            raise ValueError('That change conflicts with a joint pin. Release the pin explicitly in Pose Studio or change the instruction.')


def variation_source(root,payload):
    value=payload.get('variationOf')
    if not value:return None
    output,mode,actors,prompt=task(payload)
    if not payload.get('creative'):raise ValueError('Preview this direction before requesting more choices.')
    key=value.get('id','') if isinstance(value,dict) else ''
    if not re.fullmatch(r'text-[a-f0-9]{32}',key):raise ValueError('Invalid pose variation source.')
    source=read_json(root/'temp/text'/f'{key}.json') or read_json(root/'data/text'/f'{key}.json')
    if (not source or source.get('signature')!=value.get('signature') or source['signature']!=signature({k:v for k,v in source.items() if k!='signature'})
        or source['prompt']!=prompt or source['output']!=output or source['mode']!=mode or source['environment']!=environment(root,actors)
        or source.get('generation',{}).get('style','natural')!=payload.get('style','natural') or source.get('generation',{}).get('handShapes',True)!=payload.get('handShapes',False)):
        raise ValueError('The selected variation changed. Preview this instruction again.')
    return source


def variation_sources(root,payload):
    source=variation_source(root,payload)
    if not source:return []
    references=payload['variationOf'].get('choices')
    if references is None:return [source]
    if (not isinstance(references,list) or not 1<=len(references)<=3
        or any(not isinstance(r,dict) or set(r)!={'id','signature'} or not isinstance(r['id'],str) or not isinstance(r['signature'],str) for r in references)
        or len({r['id'] for r in references})!=len(references)
        or source['id'] not in {r['id'] for r in references}):
        raise ValueError('The previous choices changed. Preview this instruction again.')
    return [variation_source(root,dict(payload,variationOf=reference)) for reference in references]


def _generate_one(root, payload, intent, progress, body_seeds=None):
    from daz import validate_pose
    from editor import same_profile
    from rigs import profile
    from textconstraints import enforce
    from soma import apply_goal, fit_waist, place_floor, verify_goals, verify_weight
    from pose_design import fit_support, verify_support
    from hand_design import verify as verify_hands
    output, mode, actors, prompt = task(payload)
    intent = enforce(validate_intent(intent, payload),payload)
    if intent['status'] != 'plan': return dict(intent=intent)
    if not isinstance(body_seeds,list) or len(body_seeds)!=len(actors):raise ValueError('Kimodo must supply a body proposal for each actor.')
    intent=validate_intent(intent,payload)
    scene_id = 'text-'+uuid.uuid4().hex; image_id = 'pose-'+uuid.uuid4().hex
    poses, protections = [], []
    for actor, row, body in zip(actors, intent['actors'], body_seeds):
        progress('Fitting Person '+str(actor['id']), 35+(actor['id']-1)*25)
        pose = copy.deepcopy(body)
        validate_pose(pose)
        pose.setdefault('rootRotation',[0.,0.,0.])
        if pose['rigId'] != actor['rigId'] or not same_profile(pose['rig'], profile(root, actor['rigId'])):raise ValueError('The selected rig changed. Generate this preview again.')
        before = copy.deepcopy(pose)
        design_support={r['side']:r['state'] for r in pose.get('footSupport',[])}
        for change in row['changes']:apply_goal(pose,change)
        fit_waist(pose,row.get('design',{}).get('arms',{}))
        support = {**design_support,**row['support']} or ({'l':'air','r':'air'} if row['recipe']=='jump' else {})
        if design_support:
            # A requested leg lift cannot be solved by planting that foot.
            for change in row['changes']:
                if change['part'] in ('l_leg','r_leg','l_knee','r_knee') and change['movement'] in ('raise','bend'):
                    side=change['part'][0]
                    if side not in row['support']:support[side]='air'
        if design_support and pose.get('bodyGenerator',{}).get('supportKind','upright')=='upright':
            straight={c['part'][0] for c in row['changes'] if c['part'].endswith(('_leg','_knee')) and c['movement']=='straighten' and c['amount']>=.9}
            fit_support(pose,support,straight_knees=straight)
        for side,state in support.items():
            if state in ('heel','toe') and side in row['support']:aim(pose,side+'_foot',[0,.4 if state=='heel' else -.4,1])
        place_floor(pose,support,row['support'],hand_shapes=payload.get('handShapes',False))
        if support:pose['footSupport']=[dict(side=s,state=v) for s,v in support.items()]
        protected(before,pose,row['preserve'])
        protections.append((before,row['preserve'],row['changes']))
        pose.update(quality=None,edited=True,label=prompt[:80],imageId=image_id,personId=actor['id'],origin='editor',studio=True)
        pose.pop('layout',None)
        poses.append(pose)
    if len(poses)==2 and intent['interaction']=='none':
        for i,pose in enumerate(poses):pose['translation'][0]+=(i-.5)*100
    if intent['interaction']!='none':
        from textsolve import interaction
        poses=interaction(poses,intent['interaction'],progress,prompt,hand_shapes=payload.get('handShapes',False))
    for pose,(before,regions,changes) in zip(poses,protections):
        protected(before,pose,regions)
        verify_directions(pose,changes)
        row=intent['actors'][pose['personId']-1]
        verify_goals(pose,changes,row.get('design',{}).get('arms',{}))
        if row.get('design',{}).get('weight') in ('l','r'):verify_weight(pose,row['design']['weight'])
        verify_support(pose)
        verify_hands(pose)
        if pose.get('bodyContacts'):
            from body_contacts import verify as verify_body_contacts
            verify_body_contacts(pose)
        validate_pose(pose)
    generation=dict(version=2,style=payload.get('style','natural'),handShapes=payload.get('handShapes',False),seed=payload.get('variationSeed',0))
    providers=sorted({p.get('bodyGenerator',{}).get('provider','kimodo') for p in body_seeds})
    generation['providers']=dict(body='+'.join(providers),hands='rule-based-shapes' if payload.get('handShapes',False) else 'relaxed',face='preserved',interpreter=payload.get('_interpreter','body-rules'))
    generation['goals']=[dict(actor=row['id'],affectedRegions=sorted({c['part'] for c in row['changes']}),preservedRegions=row['preserve'],hands=next((p.get('handGoals',[]) for p in poses if p['personId']==row['id']),[]),contacts=next((p.get('textContacts',p.get('bodyContacts',{})) for p in poses if p['personId']==row['id']),{})) for row in intent['actors']]
    from kimodo_runtime import pack_signature
    generation.update(bodyGenerator='kimodo',bodyPackSignature=pack_signature(),snapshots=[p.get('bodyGenerator') for p in body_seeds])
    metadata=dict(version=1,id=scene_id,prompt=prompt,output=output,mode=mode,intent=intent,generation=generation,environment=environment(root,actors),interpreter=payload.get('_interpreter','body-rules'),runtime=payload.get('_runtime'),created=time.time(),poses=poses,expressions=[])
    metadata['signature']=signature(metadata)
    atomic_json(root/'temp/text'/f'{scene_id}.json',metadata)
    progress('Preview ready · Apply keeps this result',100)
    return metadata


def accept(root, payload):
    from daz import validate_pose
    scene_id = payload.get('id', '')
    if not re.fullmatch(r'text-[a-f0-9]{32}', scene_id): raise ValueError('Invalid text preview.')
    record = read_json(root/'temp/text'/f'{scene_id}.json')
    if not record or record['signature'] != payload.get('signature') or record['signature']!=signature({k:v for k,v in record.items() if k!='signature'}): raise ValueError('The text preview changed or expired. Preview the instruction again.')
    actors=[dict(id=a['id'],rigId=next((p['rigId'] for p in record['poses'] if p['personId']==a['id']),next((e['rigId'] for e in record['expressions'] if e['actorId']==a['id']),''))) for a in record['intent']['actors']]
    if record['environment']!=environment(root,actors):raise ValueError('The model, runtime or rig profiles changed. Preview again before applying.')
    if record.get('generation',{}).get('bodyGenerator')=='kimodo':
        from kimodo_runtime import pack_signature
        if record['generation'].get('bodyPackSignature')!=pack_signature():raise ValueError('The Kimodo pack changed. Preview again before applying.')
    if record.get('generation',{}).get('version')!=2 or record.get('output')!='pose' or record.get('mode')!='create':raise ValueError('This pending preview uses a retired generation workflow. Preview again; accepted history is kept.')
    for pose in record['poses']: validate_pose(pose)
    atomic_json(root/'data/text'/f'{scene_id}.json', record)
    return record


def history(root):
    return [dict(id=v['id'], name=v['prompt'][:90], thumbnail='/logo.svg', created=v['created'], solved=True, kind='text') for p in (root/'data/text').glob('text-*.json') if (v := read_json(p, {})).get('version') == 1]
