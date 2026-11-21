"""SOMA snapshots to captured Genesis rigs. Rotations and placement only."""
import copy
import math
import numpy as np
from retarget import align, constrained_rotation, rotation
from rigs import evaluated_channels, pose_bone
from studio import rest_frame, semantics

BODY = dict(hip='Hips', spine1='Spine1', spine2='Spine2', spine3='Chest', spine4='Chest', neck1='Neck1', neck2='Neck2', head='Head')
for side, prefix in (('l', 'Left'), ('r', 'Right')):
    BODY.update({side+'_'+key: prefix+name for key, name in dict(shoulder='Shoulder', upperarm='Arm', forearm='ForeArm', hand='Hand', thigh='Leg', shin='Shin', foot='Foot', toes='ToeBase').items()})


def unit(vector):
    length = np.linalg.norm(vector)
    if length < 1e-7: raise ValueError('A SOMA anatomical axis has zero length.')
    return vector/length


def source_frame(key, names, rest):
    if key in ('hip', 'spine1', 'spine2', 'spine3', 'spine4', 'neck1', 'neck2', 'head'): return np.eye(3)
    side, part = key.split('_', 1); prefix = 'Left' if side == 'l' else 'Right'
    end = {'shoulder':'Arm', 'upperarm':'ForeArm', 'forearm':'Hand', 'hand':'HandMiddle1', 'thigh':'Shin', 'shin':'Foot', 'foot':'ToeBase', 'toes':'ToeEnd'}[part]
    y = unit(rest[names[prefix+end]]-rest[names[BODY[key]]])
    guide = np.array([0., 1., 0.]) if part in ('foot', 'toes') else np.array([0., 0., 1.])
    if part == 'hand':
        width = rest[names[prefix+'HandIndex1']]-rest[names[prefix+'HandPinky1']]
        guide = np.cross(y, width)*(1 if side == 'l' else -1)
    z = guide-y*(y@guide)
    if np.linalg.norm(z) < 1e-7: z = np.array([1., 0., 0.])-y*y[0]
    z = unit(z)
    return np.column_stack((np.cross(y, z), y, z))


def validate_clip(clip):
    names = [str(x) for x in clip['joint_names']]
    if len(names) != 77 or len(set(names)) != 77: raise ValueError('Expected the pinned 77-joint SOMA output skeleton.')
    frames = len(clip['posed_joints'])
    if frames != 90: raise ValueError('Kimodo returned an unexpected clip length.')
    for key, shape in [('posed_joints', (90, 77, 3)), ('global_rot_mats', (90, 77, 3, 3)), ('rest_joints', (77, 3)), ('root_positions', (90, 3))]:
        value = np.asarray(clip[key])
        if value.shape != shape or not np.isfinite(value).all(): raise ValueError('Invalid SOMA '+key)
    matrices = clip['global_rot_mats']
    if np.max(np.abs(matrices@np.swapaxes(matrices, -1, -2)-np.eye(3))) > .005 or np.min(np.linalg.det(matrices)) < .995: raise ValueError('SOMA rotations are not proper orthogonal matrices.')
    if not set(BODY.values()).issubset(names): raise ValueError('The SOMA joint names differ from the supported model.')
    return {name:i for i, name in enumerate(names)}


def snapshot(root, rig_id, clip, index, actor=1, prompt=''):
    from textpose import neutral, frame
    from daz import validate_pose
    names = validate_clip(clip)
    if type(index) is not int or not 5 <= index < 85: raise ValueError('Choose an interior SOMA frame.')
    pose = neutral(root, rig_id, 'pose-'+'0'*32, actor)
    rig = pose['rig']; original_rig = copy.deepcopy(rig)
    mapping = semantics(rig); inverse = {node:key for key, node in mapping.items() if key in BODY}
    for side in ('l', 'r'):
        for part, bend in [('upperarm','ShldrBend'), ('forearm','ForearmBend'), ('thigh','ThighBend')]:
            if any(n['id'] == side+bend for n in rig['nodes']): inverse[side+bend] = side+'_'+part
    world = {}; channels = copy.deepcopy(pose['rotations']); limited = []
    rest = clip['rest_joints']; source = clip['global_rot_mats'][index]
    pending = list(rig['nodes'])
    while pending:
        advanced = False
        for node in pending[:]:
            if node['parent'] and node['parent'] not in world: continue
            parent = world.get(node['parent'], np.eye(3)); orient = rotation(node['orientation']); key = inverse.get(node['id'])
            if key:
                calibration = source_frame(key, names, rest)@rest_frame(rig, key, mapping).T
                desired = source[names[BODY[key]]]@calibration
                if node['id'].endswith('Bend'):
                    axis = np.asarray(node['end'])-node['center']
                    desired = parent@align(axis, parent.T@desired@axis)
                fitted_node = copy.deepcopy(node)
                for axis in node.get('driven', []): fitted_node['limits'][axis] = {**fitted_node['limits'].get(axis, {}), 'locked':True}
                values, changed = constrained_rotation(fitted_node, orient.T@parent.T@desired@orient)
                channels[node['id']] = values
                if changed: limited.append(node['id'])
            effective = evaluated_channels(rig, channels).get(node['id'], [0, 0, 0])
            world[node['id']] = parent@orient@rotation(effective, node['order'])@orient.T
            pending.remove(node); advanced = True
        if not advanced: raise ValueError('The target rig hierarchy cannot be fitted.')
    pose['rotations'] = {n['id']:channels[n['id']] for n in rig['nodes'] if pose_bone(n)}
    # Source meters become placement centimeters. Root X/Z locomotion is centered
    # for a static single-actor preview; the target's skeleton remains unchanged.
    hip = next(n for n in rig['nodes'] if n['id'] == mapping['hip'])
    pose['translation'] = [0., float(clip['root_positions'][index, 1]*100-hip['center'][1]), 0.]
    contacts = np.asarray(clip['foot_contacts'][index])
    if contacts.shape != (6,): raise ValueError('Expected the 77-joint API foot-contact layout.')
    support = {}
    for side, offset in [('l', 0), ('r', 3)]:
        heel, toe = contacts[offset] > .5, max(contacts[offset+1:offset+3]) > .5
        support[side] = 'flat' if heel and toe else 'heel' if heel else 'toe' if toe else 'air'
    pose['footSupport'] = [dict(side=s, state=state) for s, state in support.items()]
    worlds, _ = frame(pose); errors = []
    for key in [s+'_'+p for s in ('l', 'r') for p in ('upperarm', 'forearm', 'thigh', 'shin')]:
        actual = worlds[mapping[key]]@rest_frame(rig, key, mapping)[:, 1]
        target = source[names[BODY[key]]]@source_frame(key, names, rest)[:, 1]
        errors.append(math.degrees(math.acos(float(np.clip(unit(actual)@unit(target), -1, 1)))))
    if max(errors) > 55 or np.percentile(errors, 95) > 35: raise ValueError('This SOMA snapshot exceeds the captured rig’s movement limits. Another frame is needed.')
    from hand_design import apply as shape_hand
    for side in ('l','r'):shape_hand(pose,dict(part=side+'_hand',movement='relaxed',amount=1. if side=='l' else .85))
    pose.pop('handGoals',None)
    pose['warnings'] = ['Experimental Kimodo body snapshot. Fingers begin relaxed. Optional hand shapes use rule-based estimates; facial controls remain unchanged.']
    if limited: pose['warnings'].append('Captured rig limits adjusted: '+', '.join(limited))
    source_clearance = min(clip['posed_joints'][index, names[name], 1] for name in ('LeftFoot', 'LeftToeBase', 'LeftToeEnd', 'RightFoot', 'RightToeBase', 'RightToeEnd'))*100
    from body_contacts import kind,requirements
    contact_kind=kind(prompt)
    if contact_kind=='upright' and all(state=='air' for state in support.values()) and source_clearance-2. < .5:
        raise ValueError('The source contact prediction disagrees with its foot height. Another frame is needed.')
    pose['bodyGenerator'] = dict(version=1, provider='kimodo', frame=index, seed=int(clip['seed']), supportKind=contact_kind,floorRequirements=requirements(prompt),sourceUnits='meters', sourceClearanceCm=max(0., float(source_clearance)-2.), maximumDirectionErrorDegrees=max(errors))
    if rig != original_rig: raise ValueError('SOMA fitting changed protected target rig metadata.')
    validate_pose(pose)
    return pose


def airborne_request(prompt):
    import re
    from textconstraints import body_clauses
    from instructions import negated
    return any(re.search(r'\b(?:jumps?|jumping|leaps?|leaping|airborne|in (?:the )?air)\b', clause) and not negated(clause) for clause in body_clauses(prompt))


def frame_scores(clip, prompt, constraints=None):
    """Rank action silhouettes, excluding requested limbs from creative scoring.

    Contact/air phase and weight alignment are eligibility checks. Major-joint
    jitter is rejected; near-zero velocity is never a general quality reward.
    These geometric heuristics are development diagnostics, not confidence.
    """
    import re
    names = validate_clip(clip)
    points = clip['posed_joints']; rotations = clip['global_rot_mats']
    relative = points-points[:, names['Hips']:names['Hips']+1]
    local = np.einsum('tni,tij->tnj', relative, rotations[:, names['Hips']])
    major = [names[n] for n in dict.fromkeys(BODY.values())]
    velocity = np.linalg.norm(np.diff(relative[:, major], axis=0), axis=2).mean(axis=1)
    acceleration = np.linalg.norm(np.diff(relative[:, major], n=2, axis=0), axis=2).mean(axis=1)
    constraints = constraints or {}; changes = constraints.get('changes', [])
    fixed_arms = {c['part'][0] for c in changes if c['part'].endswith(('_arm','_forearm','_hand'))}
    fixed_arms.update(constraints.get('design', {}).get('arms', {}))
    fixed_legs = {c['part'][0] for c in changes if c['part'].endswith(('_leg','_knee','_foot'))}
    weight = constraints.get('design', {}).get('weight')
    jumping = airborne_request(prompt)
    from body_contacts import kind,requirements
    contact_kind=kind(prompt);floor_requirements=requirements(prompt)
    dancing = bool(re.search(r'\b(?:dance|dances|dancing)\b', prompt, re.I))
    walking = bool(re.search(r'\b(?:walk|walks|walking|run|runs|running)\b', prompt, re.I))
    happy = bool(re.search(r'\b(?:happy|celebrat\w*)\b', prompt, re.I))
    def angle(a, b): return math.acos(float(np.clip(unit(a)@unit(b), -1, 1)))/math.pi
    scores = {}
    for index in range(5, 85):
        if velocity[index] > .12 or acceleration[index-1] > .10: continue
        contact = np.asarray(clip['foot_contacts'][index])
        p = {name:local[index, number] for name, number in names.items()}
        height = min(points[index, names[s+part], 1] for s in ('Left','Right') for part in ('Foot','ToeBase','ToeEnd'))-.02
        if contact_kind=='upright' and not any(contact > .5) and height < .005: continue
        posture_penalty=0.
        if contact_kind!='upright':
            chest=unit(points[index,names['Chest']]-points[index,names['Hips']]); vertical=chest[1]
            hand_y=max(points[index,names[s+'Hand'],1] for s in ('Left','Right'))
            knee_y=max(points[index,names[s+'Shin'],1] for s in ('Left','Right')) if contact_kind=='crawl' else min(points[index,names[s+'Shin'],1] for s in ('Left','Right'))
            if contact_kind=='kneel' and floor_requirements.get('kneeSide'):knee_y=points[index,names[('Left' if floor_requirements['kneeSide']=='l' else 'Right')+'Shin'],1]
            if contact_kind=='kneel' and knee_y>.12:continue
            if contact_kind=='crawl' and (hand_y>.12 or knee_y>.12 or abs(vertical)>.7):continue
            if contact_kind=='lying' and (abs(vertical)>.4 or points[index,names['Hips'],1]>.3):continue
            if contact_kind=='inverted' and (vertical>-.4 or hand_y>.12):continue
            if contact_kind=='seated' and floor_requirements.get('flatFeet'):
                # Source posture ranks proposals; fixed floor/contact tolerances
                # belong to the final captured Genesis rig, after bounded fit.
                posture_penalty+=max(0.,.5-vertical)*5
                for side in ('Left','Right'):
                    thigh=points[index,names[side+'Shin']]-points[index,names[side+'Leg']]
                    shin=points[index,names[side+'Foot']]-points[index,names[side+'Shin']]
                    posture_penalty+=abs(unit(thigh)[1])*2+max(0.,unit(shin)[1]+.5)*2
        if jumping and (any(contact > .5) or height < .04): continue
        if weight in ('l','r'):
            side, other, offset = ('Left','Right',0) if weight=='l' else ('Right','Left',3)
            center = .6*p['Hips']+.3*p['Chest']+.1*p['Head']
            if not any(contact[offset:offset+3] > .5) or np.linalg.norm((center-p[side+'Foot'])[[0,2]])+.01 > np.linalg.norm((center-p[other+'Foot'])[[0,2]]): continue
        elbows = {}; knees = {}; active = []
        for side, prefix in [('l','Left'), ('r','Right')]:
            elbows[side] = angle(p[prefix+'ForeArm']-p[prefix+'Arm'], p[prefix+'Hand']-p[prefix+'ForeArm'])
            knees[side] = angle(p[prefix+'Shin']-p[prefix+'Leg'], p[prefix+'Foot']-p[prefix+'Shin'])
            if side not in fixed_arms:
                elevation = angle(p[prefix+'ForeArm']-p[prefix+'Arm'], np.array([0.,-1.,0.]))
                active.append(elevation+.5*elbows[side])
        arm = float(np.mean(active)) if active else 0.
        knee = float(np.mean([v for s,v in knees.items() if s not in fixed_legs])) if len(fixed_legs)<2 else 0.
        arm_asym = abs(elbows['l']-elbows['r']) if not fixed_arms else 0.
        leg_asym = abs(knees['l']-knees['r']) if not fixed_legs else 0.
        spine = unit(p['Chest']-p['Hips']); curve = abs(spine[0])+.5*abs(spine[2])
        facing = rotations[index,names['Hips']].T@rotations[index,names['Chest']]@np.array([0.,0.,1.])
        twist = abs(math.atan2(facing[0], facing[2]))/math.pi
        if jumping: score = height*3+knee*.6+arm*.15
        elif dancing: score = 1.4*arm+.8*knee+.8*(arm_asym+leg_asym)+.5*(twist+curve)
        elif walking:
            stride = abs(p['LeftFoot'][2]-p['RightFoot'][2]) if not fixed_legs else 0.
            score = stride*2+knee*.6+leg_asym*.5+arm*.15
        elif happy: score = arm*.8+knee*.4+(arm_asym+leg_asym)*.3+curve*.3
        else: score = (arm_asym+leg_asym)*.4+curve*.4+twist*.3+knee*.15
        scores[index] = float(score-posture_penalty)
    return scores


def shortlist(clip, prompt, count=2, constraints=None):
    names = validate_clip(clip)
    major = [names[n] for n in dict.fromkeys(BODY.values())]
    relative = clip['posed_joints'][:, major]-clip['posed_joints'][:, names['Hips']:names['Hips']+1]
    scores = frame_scores(clip, prompt, constraints)
    selected = []
    for index in sorted(scores, key=lambda i:(scores[i], -abs(i-45)), reverse=True):
        different = all(np.sqrt(np.mean(np.sum((relative[index]-relative[other])**2, axis=1))) >= .035 for other in selected)
        if all(abs(index-other) >= 12 for other in selected) and different: selected.append(index)
        if len(selected) == count: break
    return selected


def apply_goal(pose, change):
    """Actor-relative torso/head goals; the established limb/finger solver remains."""
    from textpose import changed, frame, bounded_rotation, aim
    from scipy.spatial.transform import Rotation
    part, movement, amount = change['part'], change['movement'], change['amount']
    if part.endswith('_leg') and movement == 'raise':
        worlds, _ = frame(pose); mapping = semantics(pose['rig'])
        return aim(pose, part[0]+'_thigh', worlds[mapping['hip']]@np.array([.1 if part[0]=='l' else -.1, .25, 1.]))
    if part.endswith(('_leg', '_knee')) and movement in ('bend', 'straighten'):
        worlds, _ = frame(pose); mapping = semantics(pose['rig']); side = part[0]
        nodes = {n['id']:n for n in pose['rig']['nodes']}; thigh = nodes[mapping[side+'_thigh']]
        direction = unit(worlds[thigh['id']]@(np.asarray(thigh['end'])-thigh['center']))
        axis = unit(worlds[thigh['id']]@np.array([1., 0., 0.]))
        target = Rotation.from_rotvec(axis*math.radians(100*amount if movement == 'bend' else 0.)).as_matrix()@direction
        return aim(pose, side+'_shin', target)
    if part not in ('torso', 'head'): return changed(pose, change)
    mapping = semantics(pose['rig']); nodes = {n['id']:n for n in pose['rig']['nodes']}
    worlds, _ = frame(pose); hip = worlds[mapping['hip']]
    if movement in ('upright', 'lean_forward', 'lean_back'):
        vector = [0., 1., 0. if movement == 'upright' else .6*amount*(1 if movement == 'lean_forward' else -1)]
        return aim(pose, 'spine1' if part == 'torso' else 'head', hip@vector)
    if movement not in ('turn_left', 'turn_right'): raise ValueError('Unsupported torso/head goal.')
    keys = [key for key in (('spine1', 'spine2', 'spine3', 'spine4') if part == 'torso' else ('neck1', 'neck2', 'head')) if key in mapping]
    facing = hip.T@worlds[mapping[keys[-1]]]@np.array([0., 0., 1.])
    delta = math.radians((45 if movement == 'turn_left' else -45)*amount)-math.atan2(facing[0], facing[2])
    for index, key in enumerate(keys):
        current, _ = frame(pose); node = nodes[mapping[key]]; orient = rotation(node['orientation'])
        turn = Rotation.from_rotvec(np.array([0., delta*(index+1)/len(keys), 0.])).as_matrix()
        desired = hip@turn@hip.T@worlds[node['id']]
        local = orient.T@current.get(node['parent'], np.eye(3)).T@desired@orient
        pose['rotations'][node['id']] = bounded_rotation(pose, node, local)


def waist_targets(pose, arms):
    from textpose import frame
    worlds, positions = frame(pose); mapping = semantics(pose['rig']); nodes = {n['id']:n for n in pose['rig']['nodes']}
    hip = nodes[mapping['hip']]; out = {}
    for side, goal in arms.items():
        if goal != 'waist': continue
        width = abs(nodes[mapping[side+'_thigh']]['center'][0]-hip['center'][0])
        rise = nodes[mapping['spine1']]['center'][1]-hip['center'][1]
        out[side] = positions[hip['id']]+worlds[hip['id']]@np.array([(1 if side == 'l' else -1)*width*2, .65*rise, 3.])
    return out


def fit_waist(pose, arms):
    from editor import reach
    mapping = semantics(pose['rig'])
    for side, target in waist_targets(pose, arms).items():
        result = reach(pose, mapping[side+'_hand'], target)
        if result['distanceCm'] > 2.: raise ValueError('This snapshot cannot place the requested hand on the waist within the captured rig limits.')
        pose['rotations'] = result['pose']['rotations']


def place_floor(pose, support, explicit, hand_shapes=True):
    from measurements import target_points
    from textpose import frame
    support_kind=pose.get('bodyGenerator',{}).get('supportKind','upright')
    if support_kind!='upright':
        if support_kind in ('crawl','inverted'):
            from hand_design import apply as shape_hand
            for side in ('l','r'):
                if hand_shapes and not any(g['part'].startswith(side+'_') for g in pose.get('handGoals',[])):
                    shape_hand(pose,dict(part=side+'_hand',movement='open',amount=1.))
                    pose['handGoals'][-1]['source']='floor-support'
        from body_contacts import place
        place(pose,support_kind)
        return
    points, _ = target_points(pose)
    keys = lambda state: ('heel',) if state == 'heel' else ('bigtoe', 'smalltoe') if state == 'toe' else ('heel', 'bigtoe', 'smalltoe')
    contacts = [points[side+'_'+key][1] for side, state in support.items() if state != 'air' for key in keys(state)]
    if contacts: pose['translation'][1] -= float(min(contacts))
    else:
        lowest = min(points[side+'_'+key][1] for side in ('l', 'r') for key in ('heel', 'bigtoe', 'smalltoe'))
        clearance = max(.5, pose['bodyGenerator']['sourceClearanceCm'])
        pose['translation'][1] += float(clearance-lowest)
    # This first provider supports upright / airborne body contact. Unrecognised
    # floor support must fail rather than grounding the feet through the body.
    _, joints = frame(pose); mapping = semantics(pose['rig'])
    if any(joints[mapping[key]][1] < margin for key, margin in [('hip', 10.), ('head', 8.), *[(side+'_'+part, 2.) for side in ('l', 'r') for part in ('hand', 'shin')]]):
        raise ValueError('Kimodo could not verify this floor contact. Try another body direction, or refine your accepted pose in Pose Studio.')


def verify_weight(pose, side):
    """Support and body-mass proxy alignment; this does not claim force simulation."""
    if side not in ('l','r'): return
    from textpose import frame
    _, points = frame(pose); mapping = semantics(pose['rig'])
    center = .6*points[mapping['hip']]+.3*points[mapping['spine4']]+.1*points[mapping['head']]
    other = 'r' if side=='l' else 'l'
    support = {r['side']:r['state'] for r in pose['footSupport']}
    if support.get(side)=='air' or np.linalg.norm((center-points[mapping[side+'_foot']])[[0,2]])+1. > np.linalg.norm((center-points[mapping[other+'_foot']])[[0,2]]):
        raise ValueError('The fitted body does not align over the requested supporting leg. Try another composition.')


def verify_goals(pose, changes, arms):
    """Independent checks after support/gesture fitting, in the actor's frame."""
    from textpose import frame
    from scipy.spatial.transform import Rotation
    worlds, positions = frame(pose); mapping = semantics(pose['rig']); nodes = {n['id']:n for n in pose['rig']['nodes']}
    hip = worlds[mapping['hip']]
    directions = {'raise':[.1, 1., .1], 'lower':[.1, -1., 0.], 'forward':[0., -.2, 1.], 'back':[0., -.2, -1.], 'bend':[0., .4, 1.], 'straighten':[0., -1., 0.]}
    for goal in changes:
        part, movement, amount = goal['part'], goal['movement'], goal['amount']
        if part in ('torso', 'head'):
            key = 'spine4' if part == 'torso' and movement.startswith('turn_') else 'spine1' if part == 'torso' else 'head'
            if movement.startswith('turn_'):
                front = hip.T@worlds[mapping[key]]@np.array([0., 0., 1.])
                actual = math.atan2(front[0], front[2]); target = math.radians((45 if movement == 'turn_left' else -45)*amount)
                error = abs(math.atan2(math.sin(actual-target), math.cos(actual-target)))
                if error > math.radians(15): raise ValueError('The fitted '+part+' cannot satisfy the requested turn.')
            else:
                vector = [0., 1., 0. if movement == 'upright' else .6*amount*(1 if movement == 'lean_forward' else -1)]
                node = nodes[mapping[key]]; actual = unit(worlds[node['id']]@(np.asarray(node['end'])-node['center']))
                if actual@unit(hip@vector) < math.cos(math.radians(15)): raise ValueError('The fitted '+part+' cannot satisfy the requested lean.')
        elif part.endswith(('_leg', '_knee')) and movement in ('bend', 'straighten'):
            side = part[0]
            from measurements import target_points
            anatomy,_=target_points(pose)
            upper = unit(anatomy[side+'_knee']-anatomy[side+'_hip'])
            lower = unit(anatomy[side+'_ankle']-anatomy[side+'_knee'])
            angle = math.degrees(math.acos(float(np.clip(upper@lower, -1, 1))))
            tolerance=5 if movement=='straighten' else 18
            if abs(angle-(100*amount if movement=='bend' else 0.)) > tolerance: raise ValueError('The fitted knee cannot satisfy the requested '+('straight leg.' if movement=='straighten' else 'bend.'))
        elif movement in directions and amount >= .9:
            side, region = part.split('_', 1)
            key = side+'_'+dict(arm='upperarm', leg='thigh', knee='shin', foot='foot', forearm='forearm', hand='hand')[region]
            node = nodes[mapping[key]]
            vector = np.array(directions[movement]); vector[0] *= 1 if side == 'l' else -1
            if region=='leg' and movement=='raise': vector = np.array([.1 if side=='l' else -.1, .25, 1.])
            actual = unit(worlds[node['id']]@(np.asarray(node['end'])-node['center']))
            if actual@unit(hip@vector) < .8: raise ValueError('The fitted '+part+' cannot satisfy '+movement+' within the rig limits.')
        else:
            from hand_design import verify as verify_hands
            verify_hands(pose)
    for side, target in waist_targets(pose, arms).items():
        if np.linalg.norm(positions[mapping[side+'_hand']]-target) > 2.: raise ValueError('The requested waist contact was lost during fitting.')
