import copy
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch
import numpy as np
from scipy.spatial.transform import Rotation

import kimodo_generation
import kimodo_runtime as runtime
import soma
import textpose
from measurements import target_points
from storage import atomic_json
from studio import semantics

PROJECT = Path(__file__).resolve().parents[1]


def clip_fixture():
    data = json.loads((PROJECT/'tests/fixtures/kimodo-soma-rest.json').read_text())
    rest = np.asarray(data['rest']); parents = data['parents']; joints = len(rest)
    local = np.tile(np.eye(3), (90, joints, 1, 1)); world = local.copy()
    positions = np.zeros((90, joints, 3)); roots = np.tile([0., 1.1, 0.], (90, 1))
    for joint, parent in enumerate(parents):
        world[:, joint] = local[:, joint] if parent < 0 else world[:, parent]@local[:, joint]
        positions[:, joint] = roots if parent < 0 else positions[:, parent]+np.einsum('tij,j->ti', world[:, parent], rest[joint]-rest[parent])
    return dict(joint_names=np.asarray(data['names']), rest_joints=rest, posed_joints=positions, global_rot_mats=world, root_positions=roots, foot_contacts=np.ones((90, 6)), seed=np.asarray(42))


class KimodoTests(unittest.TestCase):
    def setUp(self):
        folder = PROJECT/'temp/kimodo-tests'; folder.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=folder); self.addCleanup(self.temp.cleanup); self.root = Path(self.temp.name)
        for rig in ('g8f', 'g8m', 'g9'):
            atomic_json(self.root/'data/rigs'/f'{rig}.json', json.loads((PROJECT/f'tests/fixtures/target-fit/{rig}.json').read_text()))
        self.payload = dict(mode='create', output='pose', prompt='A person is dancing', actors=[dict(id=1, rigId='g8f')], bodyGenerator='kimodo', creative=True)

    def test_provider_defaults_and_explicit_scope(self):
        self.assertEqual(runtime.provider({}), 'kimodo')
        self.assertEqual(runtime.provider(self.payload), 'kimodo')
        self.assertFalse(runtime.eligible({**self.payload, 'output':'expression'}))
        for extra in [dict(reference={'mode':'inspiration'}), dict(actors=[dict(id=1), dict(id=2)]), dict(prompt='A person is kneeling'), dict(prompt='A handstand')]:
            self.assertEqual(runtime.provider({**self.payload, **extra}), 'kimodo')
        with self.assertRaises(ValueError): runtime.provider(dict(bodyGenerator='untrusted'))

    def test_freeform_body_is_not_coerced_to_a_standing_recipe(self):
        payload = dict(self.payload, prompt='A ballerina spirals with one leg extended behind')
        intent = kimodo_generation.plan(self.root, payload, {}, None, lambda *_:None)
        self.assertEqual(intent['actors'][0]['recipe'], 'kimodo')
        self.assertEqual(intent['actors'][0]['bodyDescription'], payload['prompt'])
        changed = copy.deepcopy(intent); changed['actors'][0]['bodyDescription'] = 'A standing pose'
        with self.assertRaisesRegex(ValueError, 'silent rewrite'): textpose.validate_intent(changed, payload)

    def test_model_clarifications_and_preservation_are_never_discarded(self):
        with self.assertRaisesRegex(ValueError,'no longer supported'):
            kimodo_generation.plan(self.root,dict(self.payload,useAi=True),{},None,lambda *_:None)
        for prompt in ('Keep hips unchanged and raise left arm', 'Do not raise the left hand', 'Change her scale'):
            self.assertNotEqual(kimodo_generation.plan(self.root, dict(self.payload, prompt=prompt), {}, None, lambda *_:None)['status'], 'plan')

    def test_bad_skeleton_matrices_and_end_frames_fail(self):
        clip = clip_fixture(); clip['global_rot_mats'][20, 0, 0, 0] = 2
        with self.assertRaisesRegex(ValueError, 'orthogonal'): soma.validate_clip(clip)
        clip = clip_fixture()
        for index in (0, 4, 85, 89):
            with self.assertRaisesRegex(ValueError, 'interior'): soma.snapshot(self.root, 'g8f', clip, index)
        # Identical frames must not pretend to be two distinct snapshots.
        self.assertEqual(len(soma.shortlist(clip, 'a relaxed pose')), 1)

    def test_jump_selection_requires_actual_air_phase_not_a_raised_landing(self):
        clip = clip_fixture()
        self.assertEqual(soma.shortlist(clip, 'A person is jumping'), [])
        # The generated airborne phase may occur before frame 12. Contacts and
        # source clearance must agree; labeling a grounded frame air is invalid.
        clip['foot_contacts'][7:14] = 0
        clip['posed_joints'][7:14,:,1] += .25
        clip['root_positions'][7:14,1] += .25
        selected = soma.shortlist(clip, 'A person jumps with both hands up')
        self.assertTrue(selected)
        self.assertTrue(all(7<=index<14 for index in selected))
        self.assertFalse(soma.airborne_request('standing, not jumping'))
        clip = clip_fixture(); clip['foot_contacts'][:] = 0; clip['posed_joints'][:,:,1] -= .1
        self.assertEqual(soma.shortlist(clip, 'A person walks'), [])
        with self.assertRaisesRegex(ValueError, 'disagrees'): soma.snapshot(self.root, 'g8f', clip, 30)

    def test_literal_head_turns_and_weight_instructions_survive_planning(self):
        for direction in ('left','right'):
            payload = dict(self.payload, prompt='A confident person with the head turned '+direction)
            result = kimodo_generation.plan(self.root, payload, {}, None, lambda *_:None)
            self.assertEqual(result['actors'][0]['changes'], [dict(part='head',movement='turn_'+direction,amount=1.)])
        payload = dict(self.payload, prompt='A person rests their weight on the right leg with the left arm down.')
        intent = kimodo_generation.plan(self.root, payload, {}, None, lambda *_:None)
        self.assertEqual(intent['actors'][0]['design']['weight'], 'r')
        self.assertEqual(intent['actors'][0]['changes'], [dict(part='l_arm',movement='lower',amount=1.)])
        # Quiet, centered standing cannot pass an explicitly one-sided load.
        pose = soma.snapshot(self.root, 'g8f', clip_fixture(), 30)
        with self.assertRaises(ValueError): soma.verify_weight(pose, 'r')
        payload = dict(self.payload, prompt='A happy person raises the left hand.')
        intent = kimodo_generation.plan(self.root, payload, {}, None, lambda *_:None)
        self.assertEqual(intent['actors'][0]['changes'], [dict(part='l_arm',movement='raise',amount=1.)])

    def test_all_three_generations_preserve_rig_geometry_and_nonbody_channels(self):
        clip = clip_fixture()
        for rig in ('g8f', 'g8m', 'g9'):
            pose = soma.snapshot(self.root, rig, clip, 30)
            from rigs import profile, pose_bone
            self.assertEqual(pose['rig'], profile(self.root, rig))
            self.assertTrue(all(pose_bone(n) for n in pose['rig']['nodes'] if n['id'] in pose['rotations']))
            mapping = semantics(pose['rig'])
            # Rest hands are now a reviewed relaxed shape, not zeroed fingers.
            self.assertTrue(any(pose['rotations'][node] != [0.,0.,0.] for key,node in mapping.items() if 'index' in key))
            self.assertLess(pose['bodyGenerator']['maximumDirectionErrorDegrees'], 6.)

    def test_heel_toe_support_and_source_air_clearance_survive(self):
        clip = clip_fixture(); clip['foot_contacts'][:] = [0, 1, 1, 1, 0, 0]
        pose = soma.snapshot(self.root, 'g9', clip, 30)
        self.assertEqual(pose['footSupport'], [dict(side='l', state='toe'), dict(side='r', state='heel')])
        for rig in ('g8f', 'g8m', 'g9'):
            pose = soma.snapshot(self.root, rig, clip_fixture(), 30)
            pose['bodyGenerator']['sourceClearanceCm'] = 37.
            support = dict(l='air', r='air'); soma.place_floor(pose, support, {})
            points, _ = target_points(pose)
            self.assertAlmostEqual(min(points[s+'_'+k][1] for s in ('l','r') for k in ('heel','bigtoe','smalltoe')), 37., places=6)
            pose['bodyGenerator']['sourceClearanceCm'] = 7.
            soma.place_floor(pose, support, support)
            points, _ = target_points(pose)
            self.assertAlmostEqual(min(points[s+'_'+k][1] for s in ('l','r') for k in ('heel','bigtoe','smalltoe')), 7., places=6)

    def test_arm_and_head_goals_work_in_actor_frame_without_changing_other_arm(self):
        for rig in ('g8f', 'g8m', 'g9'):
            pose = soma.snapshot(self.root, rig, clip_fixture(), 30)
            original = copy.deepcopy(pose)
            goals = [dict(part='l_arm', movement='lower', amount=1.), dict(part='head', movement='turn_left', amount=1.)]
            for goal in goals: soma.apply_goal(pose, goal)
            soma.verify_goals(pose, goals, {})
            self.assertEqual({k:v for k,v in pose['rotations'].items() if k.startswith('r')}, {k:v for k,v in original['rotations'].items() if k.startswith('r')})
            self.assertEqual(pose['rig'], original['rig'])

    def test_leg_bend_and_raise_have_independent_geometric_checks(self):
        for rig in ('g8f', 'g8m', 'g9'):
            for part, movement in [('l_leg','raise'), ('r_knee','bend')]:
                pose = soma.snapshot(self.root, rig, clip_fixture(), 30)
                goal = dict(part=part, movement=movement, amount=1.)
                soma.apply_goal(pose, goal); soma.verify_goals(pose, [goal], {})
        pose = soma.snapshot(self.root, 'g8f', clip_fixture(), 30)
        with self.assertRaises(ValueError): soma.verify_goals(pose, [dict(part='l_arm', movement='raise', amount=1.)], {})

    def test_embedding_cache_is_bounded_and_bad_packets_fail(self):
        folder = self.root/'runtime/kimodo/core/kimodo'; folder.mkdir(parents=True)
        (folder/'sanitize.py').write_text('def sanitize_text(text): return " ".join(text.split())\n')
        engine = runtime.Runtime(self.root); self.addCleanup(engine.release)
        engine.encoder = Mock(); engine.encoder.stdin = io.BytesIO(); engine.encoder.poll.return_value = 0
        engine.cache.update({str(index):b'x'*16384 for index in range(1024)})
        packet = np.ones(4096, dtype='<f4').tobytes()
        with patch('kimodo_runtime.pack_signature', return_value='test'), patch('kimodo_runtime.pipe_bytes', side_effect=[struct.pack('<I', 0), packet]):
            prompt, result, cached = engine.encode('  A   pose ', lambda *_:None)
            self.assertEqual(prompt, 'A pose'); self.assertEqual(result, packet); self.assertFalse(cached)
            self.assertLessEqual(sum(map(len, engine.cache.values())), runtime.CACHE_BYTES)
            self.assertNotIn('0', engine.cache)
            self.assertTrue(engine.encode('A pose', lambda *_:None)[2])
        with patch('kimodo_runtime.pack_signature', return_value='different'), patch('kimodo_runtime.pipe_bytes', return_value=struct.pack('<I', 9000)):
            with self.assertRaisesRegex(ValueError, 'packet'): engine.encode('A pose', lambda *_:None)

    def test_cancellation_releases_both_helpers(self):
        engine = runtime.Runtime(self.root)
        with patch.object(engine, 'load'), patch.object(engine, 'encode', side_effect=InterruptedError('Cancelled')), patch.object(engine, 'release') as release:
            with self.assertRaises(InterruptedError): engine.clips('A pose', [1], lambda *_:None)
            release.assert_called_once()
            self.assertEqual(engine.error, '')

    def test_more_like_this_cannot_recycle_unselected_choices_from_the_previous_batch(self):
        payload=dict(self.payload,candidateCount=3,handShapes=False)
        intent=kimodo_generation.plan(self.root,payload,{},None,lambda *_:None)
        clip=clip_fixture();folder=self.root/'temp/kimodo/replay';folder.mkdir(parents=True)
        paths=[];bodies=[]
        for index,movement in enumerate(('raise','lower','forward')):
            path=folder/f'clip-{index}.npz';np.savez_compressed(path,**clip);paths.append(str(path))
            pose=soma.snapshot(self.root,'g8f',clip,30)
            textpose.changed(pose,dict(part='l_arm',movement=movement,amount=1.))
            bodies.append(pose)
        engine=Mock();engine.timings={};engine.clips.return_value=dict(clips=paths)
        with patch('soma.shortlist',return_value=[30]),patch('soma.snapshot',side_effect=copy.deepcopy(bodies)):
            first=kimodo_generation.generate(self.root,payload,intent,engine,lambda *_:None)
        self.assertEqual(len(first['alternatives']),3)
        references=[dict(id=r['id'],signature=r['signature']) for r in first['alternatives']]
        varied=dict(payload,variationSeed=123,variationOf=dict(id=first['id'],signature=first['signature'],choices=references))
        before={p.name:p.read_bytes() for p in (self.root/'temp/text').glob('*.json')}
        with patch('soma.shortlist',return_value=[30]),patch('soma.snapshot',side_effect=copy.deepcopy(bodies)):
            with self.assertRaisesRegex(ValueError,'no new distinct choices'):
                kimodo_generation.generate(self.root,varied,intent,engine,lambda *_:None)
        self.assertTrue(all((self.root/'temp/text'/name).read_bytes()==data for name,data in before.items()))
        self.assertFalse(textpose.history(self.root))


if __name__ == '__main__': unittest.main()
