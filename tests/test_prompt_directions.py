"""Natural direction phrases must survive planning and bounded rig fitting."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import kimodo_generation
import soma
import textpose
from studio import semantics

ROOT=Path(__file__).resolve().parents[1]
USER_PROMPT='A person stands in a confident, heroic pose with feet planted apart and both legs straight. The left arm hangs relaxed at the side. The right arm extends forward, holding a pistol aimed toward the camera; the torso stays upright.'


def payload(prompt,rig='g8f',actors=1):
    return dict(mode='create',output='pose',bodyGenerator='kimodo',prompt=prompt,
                actors=[dict(id=i+1,rigId=rig) for i in range(actors)],handShapes=False,
                creative=True,candidateCount=3,style='natural')


def planned(prompt,rig='g8f',actors=1):
    value=kimodo_generation.plan(ROOT,payload(prompt,rig,actors),{},None,lambda *_:None)
    return value


class PromptDirectionTests(unittest.TestCase):
    def test_reported_prompt_retains_both_arms_straight_legs_and_support(self):
        value=planned(USER_PROMPT)
        self.assertEqual(value['status'],'plan',value)
        actor=value['actors'][0]
        self.assertEqual({(g['part'],g['movement']) for g in actor['changes']},
                         {('l_arm','lower'),('r_arm','forward'),('l_leg','straighten'),('r_leg','straighten'),('torso','upright')})
        self.assertEqual(actor['support'],dict(l='flat',r='flat'))
        self.assertEqual(actor['bodyDescription'],USER_PROMPT)
        self.assertFalse(actor['expression'])

    def test_extended_reaching_and_verb_first_phrases_bind_the_correct_arm(self):
        for sentence in ('The right arm extends forward.','The right arm is extended forward.',
                         'The right arm reaches forward.','The right arm stretches straight forward.',
                         'Extend the right arm forward.','A person extends the right arm straight forward.'):
            with self.subTest(sentence=sentence):
                value=planned(sentence)
                self.assertEqual(value['status'],'plan',value)
                self.assertEqual([(g['part'],g['movement']) for g in value['actors'][0]['changes']],[('r_arm','forward')])
        value=planned('Both arms are extended backward.')
        self.assertEqual({(g['part'],g['movement']) for g in value['actors'][0]['changes']},{('l_arm','back'),('r_arm','back')})

    def test_relaxed_rest_is_an_arm_location_not_a_finger_gesture(self):
        for modifier in ('relaxed','loosely','naturally','comfortably'):
            value=planned('The left arm hangs '+modifier+' at the side.')
            self.assertEqual(value['status'],'plan',value)
            self.assertEqual([(g['part'],g['movement']) for g in value['actors'][0]['changes']],[('l_arm','lower')])
        value=planned('The left hand rests relaxed by the side.')
        self.assertEqual([(g['part'],g['movement']) for g in value['actors'][0]['changes']],[('l_arm','lower')])

    def test_new_synonyms_preserve_conflict_negation_actor_and_gesture_checks(self):
        for sentence in ("Don't extend the right arm forward.",
                         'The right arm extends forward and the right arm extends backward.',
                         'The left arm hangs relaxed at the side and the left arm is overhead.'):
            self.assertEqual(planned(sentence)['status'],'clarify',sentence)
        value=planned('Person 1 stands with the right arm extended forward. Person 2 stands with the left arm hanging relaxed at the side.',actors=2)
        self.assertEqual(value['status'],'plan',value)
        self.assertEqual([{(g['part'],g['movement']) for g in row['changes']} for row in value['actors']],
                         [{('r_arm','forward')},{('l_arm','lower')}])
        self.assertEqual(planned('The right hand forms a cupped grip and the right arm extends forward.')['status'],'clarify')
        value=planned('A person stands and jumps with both feet in the air.')
        self.assertEqual(value['actors'][0]['support'],dict(l='air',r='air'))

    def test_final_geometry_honors_the_arm_goals_on_every_supported_rig(self):
        folder=ROOT/'temp/prompt-direction-tests';folder.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder) as temporary:
            target=Path(temporary);(target/'data/rigs').mkdir(parents=True)
            for rig in ('g8f','g8m','g9'):
                with self.subTest(rig=rig):
                    source=ROOT/f'tests/fixtures/target-fit/{rig}.json'
                    (target/f'data/rigs/{rig}.json').write_bytes(source.read_bytes())
                    intent=kimodo_generation.plan(target,payload(USER_PROMPT,rig),{},None,lambda *_:None)
                    seed=textpose.neutral(target,rig,'pose-'+'0'*32,1)
                    textpose.changed(seed,dict(part='r_arm',movement='lower',amount=1.))
                    original=copy.deepcopy(seed)
                    for goal in intent['actors'][0]['changes']:soma.apply_goal(seed,goal)
                    textpose.verify_directions(seed,intent['actors'][0]['changes'])
                    soma.verify_goals(seed,[g for g in intent['actors'][0]['changes'] if g['part'].endswith('_arm')],{})
                    world,points=textpose.frame(seed);mapping=semantics(seed['rig'])
                    for side,axis,sign in (('r',2,1),('l',1,-1)):
                        shoulder=points.get(side+'ShldrBend',points[mapping[side+'_upperarm']])
                        delta=world[mapping['hip']].T@(points[mapping[side+'_hand']]-shoulder)
                        self.assertGreater(sign*delta[axis]/np.linalg.norm(delta),.9)
                    self.assertEqual(seed['rig'],original['rig'])
                    self.assertEqual(seed['translation'],original['translation'])
                    self.assertEqual(seed['rootRotation'],original['rootRotation'])
                    fingers={n for n in original['rotations'] if any(x in n.lower() for x in ('thumb','index','mid','ring','pinky'))}
                    self.assertEqual({n:seed['rotations'][n] for n in fingers},{n:original['rotations'][n] for n in fingers})

    def test_floor_fitting_keeps_explicit_knees_straight_and_feet_planted(self):
        from pose_design import verify_support
        folder=ROOT/'temp/prompt-direction-tests';folder.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder) as temporary:
            target=Path(temporary);(target/'data/rigs').mkdir(parents=True)
            for rig in ('g8f','g8m','g9'):
                with self.subTest(rig=rig):
                    (target/f'data/rigs/{rig}.json').write_bytes((ROOT/f'tests/fixtures/target-fit/{rig}.json').read_bytes())
                    args=payload(USER_PROMPT,rig)
                    intent=kimodo_generation.plan(target,args,{},None,lambda *_:None)
                    seed=textpose.neutral(target,rig,'pose-'+'0'*32,1)
                    seed['rootRotation']=[0.,0.,8.]
                    seed['footSupport']=[dict(side=s,state='flat') for s in ('l','r')]
                    seed['bodyGenerator']=dict(provider='kimodo',supportKind='upright',selectionScore=0.,sourceClearanceCm=0.)
                    result=textpose._generate_one(target,args,intent,lambda *_:None,body_seeds=[seed])
                    pose=result['poses'][0];verify_support(pose)
                    from measurements import target_points
                    points,_=target_points(pose)
                    for side in ('l','r'):
                        upper=soma.unit(points[side+'_knee']-points[side+'_hip'])
                        lower=soma.unit(points[side+'_ankle']-points[side+'_knee'])
                        angle=np.degrees(np.arccos(np.clip(upper@lower,-1,1)))
                        self.assertLess(angle,.25)
                    self.assertEqual(pose['rig'],seed['rig'])
                    self.assertEqual(pose['rootRotation'],seed['rootRotation'])
                    soma.apply_goal(pose,dict(part='l_knee',movement='bend',amount=.6))
                    with self.assertRaisesRegex(ValueError,'straight leg'):
                        soma.verify_goals(pose,[dict(part='l_leg',movement='straighten',amount=1.)],{})


if __name__=='__main__':unittest.main()
