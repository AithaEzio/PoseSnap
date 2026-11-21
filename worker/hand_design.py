"""Reviewed anatomical hand goals shared by parsing, prompting and rig fitting."""
import hashlib
import json
import re
from instructions import clauses, negated

FINGERS = ('thumb', 'index', 'mid', 'ring', 'pinky')
PARTS = tuple(side+'_'+finger for side in ('l', 'r') for finger in FINGERS)
# Flexion per finger, then spread. The captured rig supplies the actual limits.
SHAPES = {
    'relaxed': ((.12, .13, .19, .24, .29), .08),
    'open': ((0., 0., 0., 0., 0.), .45),
    'fist': ((.8, .95, 1., 1., .95), 0.),
    'point': ((.6, 0., .9, .95, .9), .04),
    'thumb_up': ((0., .95, 1., 1., .95), .04),
    'peace': ((.65, 0., 0., .95, .9), .7),
    'pinch': ((.55, .6, .22, .27, .32), .08),
    'cupped': ((.3, .42, .48, .53, .58), .06),
}
MOVES = (*SHAPES, 'curl', 'extend', 'spread', 'oppose')
ALIASES = {'middle': 'mid', 'little': 'pinky', 'pinky': 'pinky', 'index': 'index', 'ring': 'ring', 'thumb': 'thumb'}


def signature():
    from pathlib import Path
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def allowed(part):
    if part in PARTS:
        return ('curl', 'extend', 'spread', 'oppose') if part.endswith('thumb') else ('curl', 'extend', 'spread')
    return tuple(SHAPES) if part.endswith('_hand') else ()


def phrases(text):
    """Explicit gestures are side-scoped; negated or ambiguous phrases stay out."""
    result = []
    for clause in clauses(text):
        if negated(clause): continue
        patterns = (
            r'\b(left|right|both) hands?\s+(?:(?:is|are|in|makes?|forms?)\s+)?(?:a\s+)?(relaxed|open|fist|point(?:ing)?|thumbs?[ -]?up|peace(?: sign)?|pinch(?:ing)?|cupped)\b',
            r'\b(relax|open|close|clench|cup)\s+(?:(?:the|her|his|their)\s+)?(left|right|both) hands?\b',
            r'\b(left|right|both)\s+(thumbs?|index(?: finger)?s?|middle(?: finger)?s?|ring fingers?|pinky(?: finger)?s?|little fingers?)\s+(?:(?:is|are)\s+)?(curl(?:ed)?|extend(?:ed)?|straight|spread|oppos(?:e|ed))\b',
            r'\b(curl|extend|spread|oppose)\s+(?:(?:the|her|his|their)\s+)?(left|right|both)\s+(thumbs?|index(?: finger)?s?|middle(?: finger)?s?|ring fingers?|pinky(?: finger)?s?|little fingers?)\b',
            r'\b(left|right|both)\s+(peace(?: sign)?|thumbs?[ -]?up|fist)\b',
        )
        for index, pattern in enumerate(patterns):
            for match in re.finditer(pattern, clause):
                if index == 0: side, movement = match.groups(); finger = None
                elif index == 1: movement, side = match.groups(); finger = None
                elif index == 2: side, finger, movement = match.groups()
                elif index == 3: movement, side, finger = match.groups()
                else: side, movement = match.groups(); finger = None
                movement = {'relax':'relaxed','close':'fist','clench':'fist','cup':'cupped','pointing':'point','pinching':'pinch','peace sign':'peace','straight':'extend','curled':'curl','extended':'extend','opposed':'oppose'}.get(movement, movement)
                if movement.startswith('thumb'): movement = 'thumb_up'
                part = ALIASES[re.match(r'\w+', finger)[0].rstrip('s')] if finger else 'hand'
                for prefix in ('l', 'r') if side == 'both' else (side[0],):
                    result.append(dict(part=prefix+'_'+part, movement=movement, amount=1.))
    return list({(c['part'], c['movement']):c for c in result}.values())


def targets(pose, change):
    from studio import semantics
    side, part = change['part'].split('_', 1); movement = change['movement']
    mapping = semantics(pose['rig']); nodes = {n['id']:n for n in pose['rig']['nodes']}
    sign = 1 if side == 'l' else -1
    shape, spread = SHAPES.get(movement, ((0.,)*5, 0.))
    result = {}; requested = {}
    for number, finger in enumerate(FINGERS):
        if part != 'hand' and finger != part: continue
        flex = shape[number] if part == 'hand' else 1. if movement == 'curl' else 0.
        for segment in (1, 2, 3):
            name = mapping.get(f'{side}_{finger}{segment}')
            if not name: raise ValueError('The captured rig has no '+side+' '+finger+' chain. Refresh its rig before shaping fingers.')
            node = nodes[name]; old = pose['rotations'][name]; value = list(old); wanted = list(old)
            axes = {1:sign*(30. if segment == 1 else 55.)*flex} if finger == 'thumb' else {2:-sign*(65. if segment == 1 else 85.)*flex}
            if movement == 'spread' or part == 'hand':
                if segment == 1 and finger != 'thumb': axes[1] = sign*(8., 2., -5., -10.)[number-1]*(1. if movement == 'spread' else spread)
            if finger == 'thumb' and segment == 1 and (movement == 'oppose' or movement == 'pinch'):
                axes[0] = 30. if movement == 'oppose' else 20.
            # Independent spread/opposition leaves flexion untouched.
            if part != 'hand' and movement in ('spread', 'oppose'):
                axes.pop(1 if finger == 'thumb' else 2, None)
                if movement == 'spread' and finger == 'thumb': axes[2] = -sign*12.
            for axis, goal in axes.items():
                channel = 'xyz'[axis]; limit = node['limits'].get(channel, {})
                if limit.get('clamped'): goal = max(limit['min'], min(limit['max'], goal))
                goal = old[axis]+(goal-old[axis])*change['amount']
                wanted[axis] = float(goal)
                if not limit.get('locked') and channel not in node.get('driven', []): value[axis] = float(goal)
            result[name] = value
            requested[name] = wanted
    return result, requested


def apply(pose, change):
    fitted, expected = targets(pose, change)
    if change['movement'] in ('pinch','open','peace') and change['amount']>=.95:
        fitted,expected=fit_geometry(pose,change['part'][0],fitted,expected,change['movement'])
    pose['rotations'].update(fitted)
    for previous in pose.get('handGoals', []):
        for name in expected: previous['channels'].pop(name, None)
    pose['handGoals'] = [g for g in pose.get('handGoals', []) if g['channels']]
    pose.setdefault('handGoals', []).append(dict(change, channels=expected))


def fit_geometry(pose,side,fitted,expected,movement):
    """Fit captured fingertip geometry using free dials and fixed lengths."""
    import copy
    import numpy as np
    from scipy.optimize import least_squares
    from studio import semantics,rest_frame
    from textpose import frame
    trial=copy.deepcopy(pose);trial['rotations'].update(fitted)
    mapping=semantics(trial['rig']);nodes={n['id']:n for n in trial['rig']['nodes']}
    variables=[];initial=[];low=[];high=[]
    fingers=('thumb','index') if movement=='pinch' else ('index','mid') if movement=='peace' else FINGERS
    if movement=='peace':
        worlds,points=frame(trial);rays=[]
        for finger in fingers:
            node=nodes[mapping[f'{side}_{finger}3']]
            ray=points[node['id']]+worlds[node['id']]@(np.asarray(node['end'])-node['center'])-points[mapping[f'{side}_{finger}1']]
            rays.append(ray/np.linalg.norm(ray))
        forward=sum(rays);forward/=np.linalg.norm(forward)
        outward=points[mapping[side+'_index1']]-points[mapping[side+'_mid1']]
        outward-=forward*(outward@forward);outward/=np.linalg.norm(outward)
        # Twenty degrees is a readable V, fitted in the captured hand's plane.
        # Only the two proximal spread dials move; flexion stays authoritative.
        targets=[forward*np.cos(np.deg2rad(10))+sign*outward*np.sin(np.deg2rad(10)) for sign in (1,-1)]
    for finger in fingers:
        for segment in (1,2,3):
            name=mapping[f'{side}_{finger}{segment}'];node=nodes[name]
            axes=(0,1,2) if finger=='thumb' and segment==1 else (1,) if finger=='thumb' else (1,2) if segment==1 else (2,)
            if movement=='peace':axes=(1,) if segment==1 else ()
            for axis in axes:
                channel='xyz'[axis];limit=node['limits'].get(channel,{})
                if limit.get('locked') or channel in node.get('driven',[]):continue
                value=trial['rotations'][name][axis]
                lo=limit.get('min',-90.) if limit.get('clamped') else -90.;hi=limit.get('max',90.) if limit.get('clamped') else 90.
                if hi-lo<1e-6:continue
                variables.append((name,axis));initial.append(float(np.clip(value,lo,hi)));low.append(lo);high.append(hi)
    if not variables:
        verify_geometry(trial,side,movement)
        return fitted,expected
    initial=np.asarray(initial)
    def residual(values):
        for (name,axis),value in zip(variables,values):trial['rotations'][name][axis]=float(value)
        worlds,points=frame(trial);tips=[]
        for finger in fingers:
            node=nodes[mapping[f'{side}_{finger}3']]
            tips.append(points[node['id']]+worlds[node['id']]@(np.asarray(node['end'])-node['center']))
        # A small separation approximates finger pads; these are joint proxies.
        if movement=='pinch':
            direction=tips[0]-tips[1];distance=np.linalg.norm(direction)
            errors=direction*(max(0.,distance-.4)/max(distance,1e-6))/.2
        elif movement=='peace':
            rays=[tip-points[mapping[f'{side}_{finger}1']] for finger,tip in zip(fingers,tips)]
            errors=np.concatenate([(ray/np.linalg.norm(ray)-target)/.1 for ray,target in zip(rays,targets)])
        else:
            hand=mapping[side+'_hand'];middle=mapping[side+'_mid1']
            palm=points[hand]+worlds[hand]@(np.asarray(nodes[middle]['center'])-nodes[hand]['center'])*.65
            normal=worlds[hand]@rest_frame(trial['rig'],side+'_hand',mapping)[:,2]
            pads=tips+[points[mapping[f'{side}_{finger}{segment}']] for finger in fingers for segment in (2,3)]
            errors=[float((point-palm)@normal)/.25 for point in pads]
        return np.r_[errors,(values-initial)/90*.08]
    result=least_squares(residual,initial,bounds=(low,high),max_nfev=45,ftol=1e-6)
    residual(result.x)
    verify_geometry(trial,side,movement)
    for name,axis in variables:
        fitted[name][axis]=trial['rotations'][name][axis]
        expected[name][axis]=trial['rotations'][name][axis]
    return fitted,expected


def verify_geometry(pose,side,movement):
    import numpy as np
    from studio import semantics,rest_frame
    from textpose import frame
    mapping=semantics(pose['rig']);nodes={n['id']:n for n in pose['rig']['nodes']};worlds,points=frame(pose)
    tips={}
    for finger in FINGERS:
        node=nodes[mapping[f'{side}_{finger}3']]
        tips[finger]=points[node['id']]+worlds[node['id']]@(np.asarray(node['end'])-node['center'])
    if movement=='pinch':
        if np.linalg.norm(tips['thumb']-tips['index'])>2.:
            raise ValueError('The fingertip proxies cannot form this pinch within 2 cm. Your accepted result is kept.')
    elif movement=='open':
        hand=mapping[side+'_hand'];middle=mapping[side+'_mid1']
        palm=points[hand]+worlds[hand]@(np.asarray(nodes[middle]['center'])-nodes[hand]['center'])*.65
        normal=worlds[hand]@rest_frame(pose['rig'],side+'_hand',mapping)[:,2]
        pads=[*tips.values(),*(points[mapping[f'{side}_{f}{n}']] for f in FINGERS for n in (2,3))]
        if max(abs(float((p-palm)@normal)) for p in pads)>1.:
            raise ValueError('The fingers cannot form an open palm within the captured joint limits. Your accepted result is kept.')
    elif movement=='peace':
        rays=[];straightness={}
        for finger in ('index','mid','ring','pinky'):
            chain=[points[mapping[f'{side}_{finger}{n}']] for n in (1,2,3)]+[tips[finger]]
            ray=chain[-1]-chain[0];length=sum(np.linalg.norm(b-a) for a,b in zip(chain,chain[1:]))
            straightness[finger]=np.linalg.norm(ray)/max(length,1e-9)
            if finger in ('index','mid'):rays.append(ray/max(np.linalg.norm(ray),1e-9))
        angle=np.degrees(np.arccos(np.clip(rays[0]@rays[1],-1.,1.)))
        outward=points[mapping[side+'_index1']]-points[mapping[side+'_mid1']]
        if not 10.<=angle<=40. or (rays[0]-rays[1])@outward<=0 or min(straightness[f] for f in ('index','mid'))<.9 or max(straightness[f] for f in ('ring','pinky'))>.8:
            raise ValueError('The captured hand cannot form a clear peace sign within its joint limits. Your accepted result is kept.')


def verify(pose):
    for goal in pose.get('handGoals', []):
        for name, wanted in goal['channels'].items():
            if max(abs(a-b) for a,b in zip(pose['rotations'][name], wanted)) > .1:
                raise ValueError('Fitting or a locked channel prevents the requested finger gesture. Your accepted result is kept.')
        if goal['movement'] in ('pinch','open','peace') and goal['amount']>=.95:verify_geometry(pose,goal['part'][0],goal['movement'])
