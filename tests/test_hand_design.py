import copy
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np

import hand_design as hands
import textpose
from storage import atomic_json
from studio import semantics

ROOT = Path(__file__).resolve().parents[1]


class HandDesignTests(unittest.TestCase):
    def setUp(self):
        base = ROOT/'temp/hand-tests'; base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for rig in ('g8f', 'g8m', 'g9'):
            atomic_json(self.root/f'data/rigs/{rig}.json', json.loads((ROOT/f'tests/fixtures/target-fit/{rig}.json').read_text()))

    def test_all_shapes_change_only_the_requested_fingers_on_three_rigs(self):
        for rig in ('g8f','g8m','g9'):
            for shape in hands.SHAPES:
                with self.subTest(rig=rig,shape=shape):
                    pose = textpose.neutral(self.root,rig,'pose-'+'0'*32,1); before = copy.deepcopy(pose)
                    hands.apply(pose,dict(part='l_hand',movement=shape,amount=1.))
                    hands.verify(pose)
                    allowed = {semantics(pose['rig'])[f'l_{f}{s}'] for f in hands.FINGERS for s in (1,2,3)}
                    self.assertEqual(pose['rig'], before['rig'])
                    self.assertTrue(all(v == before['rotations'][k] for k,v in pose['rotations'].items() if k not in allowed))
                    nodes={n['id']:n for n in pose['rig']['nodes']}
                    for name in allowed:
                        for i,axis in enumerate('xyz'):
                            limit=nodes[name]['limits'].get(axis,{})
                            if limit.get('clamped'): self.assertTrue(limit['min'] <= pose['rotations'][name][i] <= limit['max'])
                    _, old = textpose.frame(before); _, new = textpose.frame(pose)
                    self.assertGreater(max(np.linalg.norm(new[n]-old[n]) for n in allowed), .05)

    def test_independent_finger_override_and_hand_preservation(self):
        pose=textpose.neutral(self.root,'g9','pose-'+'0'*32,1)
        hands.apply(pose,dict(part='r_hand',movement='fist',amount=1.))
        before=copy.deepcopy(pose)
        hands.apply(pose,dict(part='r_index',movement='extend',amount=1.))
        hands.verify(pose)
        with self.assertRaisesRegex(ValueError,'preserved region'):textpose.protected(before,pose,['hands'])
        self.assertEqual(pose['rotations'][semantics(pose['rig'])['r_mid2']],before['rotations'][semantics(pose['rig'])['r_mid2']])

    def test_locked_finger_is_not_silently_claimed_as_a_success(self):
        pose=textpose.neutral(self.root,'g8f','pose-'+'0'*32,1)
        name=semantics(pose['rig'])['l_index1']
        next(n for n in pose['rig']['nodes'] if n['id']==name)['limits']['z']['locked']=True
        hands.apply(pose,dict(part='l_hand',movement='fist',amount=1.))
        self.assertEqual(pose['rotations'][name][2],0.)
        with self.assertRaisesRegex(ValueError,'locked'):hands.verify(pose)

    def test_pinch_fits_captured_fingertip_geometry_without_scaling(self):
        for rig in ('g8f','g8m','g9'):
            for side in ('l','r'):
                pose=textpose.neutral(self.root,rig,'pose-'+'0'*32,1);original=copy.deepcopy(pose['rig'])
                hands.apply(pose,dict(part=side+'_hand',movement='pinch',amount=1.));hands.verify(pose)
                frames,points=textpose.frame(pose);mapping=semantics(pose['rig']);nodes={n['id']:n for n in pose['rig']['nodes']};tips=[]
                for finger in ('thumb','index'):
                    node=nodes[mapping[side+'_'+finger+'3']]
                    tips.append(points[node['id']]+frames[node['id']]@(np.asarray(node['end'])-node['center']))
                self.assertLess(np.linalg.norm(tips[0]-tips[1]),.8)
                self.assertEqual(pose['rig'],original)

    def test_open_palm_fits_finger_geometry_to_its_plane_on_both_sides(self):
        from measurements import target_points
        from studio import rest_frame
        for rig in ('g8f','g8m','g9'):
            for side in ('l','r'):
                pose=textpose.neutral(self.root,rig,'pose-'+'0'*32,1);original=copy.deepcopy(pose['rig'])
                hands.apply(pose,dict(part=side+'_hand',movement='open',amount=1.));hands.verify(pose)
                frames,_=textpose.frame(pose);mapping=semantics(pose['rig']);points=target_points(pose)[0]
                normal=frames[mapping[side+'_hand']]@rest_frame(pose['rig'],side+'_hand',mapping)[:,2]
                distances=[abs(float((point-points[side+'_palm'])@normal)) for name,point in points.items() if name.startswith(side+'_') and name.endswith('tip')]
                self.assertLess(max(distances),.5);self.assertEqual(pose['rig'],original)

    def test_reviewed_gestures_and_actor_ownership(self):
        for word,movement in [('thumbs up','thumb_up'),('peace sign','peace'),('cupped','cupped'),('pinch','pinch')]:
            payload=dict(output='pose',mode='create',actors=[dict(id=1,rigId='g8f')],prompt='Left hand '+word)
            self.assertEqual(textpose.basic_intent(payload)['status'],'clarify')
            intent=textpose.basic_intent(dict(payload,handShapes=True))
            self.assertEqual(intent['actors'][0]['changes'],[dict(part='l_hand',movement=movement,amount=1.)])
        self.assertEqual(hands.phrases('Do not curl the left index finger'),[])
        self.assertEqual(hands.phrases('Extend the right index finger'),[dict(part='r_index',movement='extend',amount=1.)])

    def test_compact_side_named_gestures_keep_their_actor_and_negation(self):
        from textconstraints import actor_text
        self.assertEqual(hands.phrases('an open right hand and a left peace sign'),[dict(part='r_hand',movement='open',amount=1.),dict(part='l_hand',movement='peace',amount=1.)])
        self.assertEqual(hands.phrases("Don't make a left peace sign"),[])
        prompt='Person 1 has a left peace sign. Person 2 has a right fist.'
        self.assertEqual(hands.phrases(actor_text(prompt,1,2)),[dict(part='l_hand',movement='peace',amount=1.)])
        self.assertEqual(hands.phrases(actor_text(prompt,2,2)),[dict(part='r_hand',movement='fist',amount=1.)])

    def test_peace_sign_has_a_readable_v_on_both_hands_of_each_captured_rig(self):
        from math import degrees,acos
        for rig in ('g8f','g8m','g9'):
            for side in ('l','r'):
                pose=textpose.neutral(self.root,rig,'pose-'+'0'*32,1);before=copy.deepcopy(pose)
                hands.apply(pose,dict(part=side+'_hand',movement='peace',amount=1.));hands.verify(pose)
                frames,points=textpose.frame(pose);mapping=semantics(pose['rig']);nodes={n['id']:n for n in pose['rig']['nodes']};directions=[]
                for finger in ('index','mid'):
                    node=nodes[mapping[f'{side}_{finger}3']]
                    vector=points[node['id']]+frames[node['id']]@(np.asarray(node['end'])-node['center'])-points[mapping[f'{side}_{finger}1']]
                    directions.append(vector/np.linalg.norm(vector))
                self.assertGreaterEqual(degrees(acos(np.clip(directions[0]@directions[1],-1,1))),10.)
                self.assertEqual(pose['rig'],before['rig'])
                other='r' if side=='l' else 'l'
                self.assertTrue(all(pose['rotations'][mapping[f'{other}_{f}{n}']]==before['rotations'][mapping[f'{other}_{f}{n}']] for f in hands.FINGERS for n in (1,2,3)))
        pose=textpose.neutral(self.root,'g9','pose-'+'0'*32,1)
        hands.apply(pose,dict(part='l_hand',movement='peace',amount=1.))
        # A later fitter may keep every goal label yet lose the actual V.
        for finger in ('index','mid'):pose['rotations'][semantics(pose['rig'])[f'l_{finger}1']][1]=0.
        with self.assertRaises(ValueError):hands.verify_geometry(pose,'l','peace')


if __name__ == '__main__':unittest.main()
