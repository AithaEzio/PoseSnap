import copy
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import expression
import textpose as text
from textconstraints import actor_text, enforce, limbs, waist_arms
from storage import atomic_json, read_json
from daz import duf
from editor import checked_poses
from textoutput import accepted, combined_script

PROJECT = Path(__file__).resolve().parents[1]


class TextPoseTests(unittest.TestCase):
    def setUp(self):
        base=PROJECT/'temp/text-tests';base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        for rig in ('g8f','g8m','g9'):
            atomic_json(self.root/'data/rigs'/f'{rig}.json',read_json(PROJECT/'tests/fixtures/target-fit'/f'{rig}.json'))
        self.payload=dict(output='pose',mode='create',prompt='A relaxed standing pose',actors=[dict(id=1,rigId='g8f')],handShapes=True)

    def generate(self,payload=None,intent=None):
        # Explicit synthetic seeds isolate bounded fitting from model inference.
        p=payload or self.payload
        import kimodo_generation
        checked=intent or kimodo_generation.plan(self.root,p,{},None,lambda *_:None)
        if checked['status']!='plan':return dict(intent=checked)
        from textconstraints import posture_recipe
        from soma import place_floor
        seeds=[]
        for actor in p['actors']:
            pose=text.neutral(self.root,actor['rigId'],'pose-'+'0'*32,actor['id'])
            recipe=posture_recipe(p['prompt']) or 'relaxed';text.recipe(pose,recipe)
            pose['bodyGenerator']=dict(provider='synthetic-test-fixture',supportKind='upright',sourceClearanceCm=15.)
            support=dict(l='air',r='air') if recipe=='jump' else dict(l='flat',r='flat')
            place_floor(pose,support,support);pose['footSupport']=[dict(side=k,state=v) for k,v in support.items()]
            seeds.append(pose)
        return text._generate_one(self.root,p,checked,lambda *_:None,body_seeds=seeds)

    def test_jump_does_not_turn_airborne_legs_into_raised_legs(self):
        p=dict(self.payload,prompt='She is jumping with both hands up and both legs in air')
        i=text.basic_intent(p);self.assertEqual({c['part'] for c in i['actors'][0]['changes']},{'l_arm','r_arm'})
        result=self.generate(p);pose=result['poses'][0]
        self.assertTrue(all(s['state']=='air' for s in pose['footSupport']))
        from measurements import target_points
        self.assertAlmostEqual(min(v[1] for k,v in target_points(pose)[0].items() if k.endswith(('heel','bigtoe','smalltoe'))),15,places=4)
        self.assertNotIn('scale',json.dumps(duf(pose,'floor')))

    def test_hand_shapes_are_explicit_scoped_actions(self):
        p=dict(self.payload,prompt='Left hand fist')
        self.assertEqual(text.basic_intent(p)['actors'][0]['changes'],[dict(part='l_hand',movement='fist',amount=1.)])

    def test_more_like_this_validates_all_previous_choices_including_an_accepted_source(self):
        p=dict(self.payload,creative=True,candidateCount=3)
        records=[self.generate(p) for _ in range(3)]
        refs=[dict(id=r['id'],signature=r['signature']) for r in records]
        payload=dict(p,variationOf=dict(**refs[1],choices=refs))
        self.assertEqual([r['id'] for r in text.variation_sources(self.root,payload)],[r['id'] for r in records])
        # Apply may move ownership into history; it must remain a valid source.
        atomic_json(self.root/'data/text'/f"{records[1]['id']}.json",records[1])
        (self.root/'temp/text'/f"{records[1]['id']}.json").unlink()
        self.assertEqual(len(text.variation_sources(self.root,payload)),3)
        bad=[dict(refs[0]),dict(refs[1]),dict(refs[2],signature='forged')]
        with self.assertRaisesRegex(ValueError,'changed'):
            text.variation_sources(self.root,dict(p,variationOf=dict(**refs[1],choices=bad)))
        for choices in ([],refs*2,[refs[0],refs[0]],[dict(id=[],signature='bad')]):
            with self.subTest(choices=choices),self.assertRaises(ValueError):
                text.variation_sources(self.root,dict(p,variationOf=dict(**refs[1],choices=choices)))


    def test_limb_direction_rules_respect_negation_conflict_and_actor_ownership(self):
        self.assertFalse(limbs("Do not lower the left hand"));self.assertFalse(limbs('Left hand is not down'))
        self.assertFalse(limbs('Both legs in air'));self.assertFalse(limbs('Lowercase lettering on the left hand'))
        self.assertFalse(limbs('Lower the left hand slightly'));self.assertFalse(limbs('Raise the left arm 30 degrees'))
        self.assertEqual(limbs('Person 1 left hand is down'),[dict(part='l_arm',movement='lower',amount=1.)])
        p=dict(self.payload,prompt='Person 1 left hand is down. Person 2 right hand is up.',actors=[dict(id=1,rigId='g8f'),dict(id=2,rigId='g9')])
        intent=dict(status='plan',actors=[dict(id=i,recipe='standing',changes=[],preserve=[],expression={},support={}) for i in (1,2)])
        result=enforce(intent,p)
        self.assertEqual(result['actors'][0]['changes'],[dict(part='l_arm',movement='lower',amount=1.)])
        self.assertEqual(result['actors'][1]['changes'],[dict(part='r_arm',movement='raise',amount=1.)])
        p=dict(self.payload,prompt='Left hand up and left hand down')
        self.assertEqual(enforce(dict(status='plan',actors=[dict(id=1,changes=[])]),p)['status'],'clarify')
        p=dict(self.payload,prompt='Left hand down slightly')
        self.assertEqual(enforce(dict(status='plan',actors=[dict(id=1,changes=[])]),p)['status'],'clarify')


    def test_body_constraints_ignore_unrelated_negated_face_clauses(self):
        self.assertEqual(waist_arms('Left hand on the waist and no cheek puff.'),{'l':'waist'})
        self.assertEqual(waist_arms('Do not put the left hand on the waist.'),{})
        expected=[dict(part='r_arm',movement='raise',amount=1.),dict(part='l_arm',movement='lower',amount=1.)]
        for suffix in (', without changing her expression.',' without changing her expression.'):
            self.assertEqual(limbs('Right arm stretches overhead while the left hand stays low'+suffix),expected)
        self.assertEqual(limbs('Do not lower the left arm, but right arm up.'),[dict(part='r_arm',movement='raise',amount=1.)])
        self.assertEqual(limbs('Raise the left arm slightly and right arm down.'),[dict(part='r_arm',movement='lower',amount=1.)])


    def test_positional_hand_intent_is_not_a_wrist_rotation(self):
        p=self.payload
        original=dict(status='plan',actors=[dict(id=1,recipe='standing',changes=[dict(part='l_hand',movement='lower',amount=1.)])])
        clean=text.validate_intent(original,p)
        self.assertEqual(clean['actors'][0]['changes'],[dict(part='l_arm',movement='lower',amount=1.)])
        self.assertEqual(original['actors'][0]['changes'][0]['part'],'l_hand')


    def test_goal_fitting_respects_locked_and_driven_channels(self):
        from studio import semantics
        for rig in ('g8f','g8m','g9'):
            with self.subTest(rig=rig):
                pose=text.neutral(self.root,rig,'pose-'+'1'*32,1)
                nodes={n['id']:n for n in pose['rig']['nodes']};mapping=semantics(pose['rig'])
                arm='lShldrBend' if rig!='g9' else mapping['l_upperarm']
                thigh='lThighBend' if rig!='g9' else mapping['l_thigh']
                fixed=[(arm,0,13.),(thigh,1,9.),(mapping['l_index1'],2,-15.),(mapping['head'],1,7.)]
                for name,axis,value in fixed:
                    nodes[name]['limits']['xyz'[axis]]['locked']=True;pose['rotations'][name][axis]=value
                nodes[arm]['driven']=['y'];pose['rotations'][arm][1]=-12.
                nodes[mapping['head']]['driven']=['z'];pose['rotations'][mapping['head']][2]=3.
                atomic_json(self.root/'data/rigs'/f'{rig}.json',pose['rig'])
                before=copy.deepcopy(pose)
                after=copy.deepcopy(pose)
                for change in (dict(part='l_arm',movement='raise',amount=1.),dict(part='l_hand',movement='fist',amount=1.),dict(part='head',movement='turn_left',amount=1.)):
                    text.changed(after,change)
                for name,axis,value in fixed:self.assertEqual(after['rotations'][name][axis],value)
                self.assertEqual(after['rotations'][arm][1],-12.)
                self.assertEqual(after['rotations'][mapping['head']][2],3.)
                self.assertEqual(pose,before);self.assertEqual(after['rig'],before['rig'])

    def test_locked_root_orientation_rejects_conflicting_posture_or_contact(self):
        from textsolve import interaction
        pose=self.generate()['poses'][0];root=next(n for n in pose['rig']['nodes'] if not n['parent'])
        root['limits']['x']['locked']=True;pose['rootRotation'][0]=7.
        atomic_json(self.root/'data/rigs/g8f.json',pose['rig']);before=copy.deepcopy(pose)
        with self.assertRaisesRegex(ValueError,'locked figure orientation'):text.root_rotation(pose,[0.,0.,0.])
        self.assertEqual(pose,before);self.assertFalse(text.history(self.root))
        root['limits']['y']['locked']=True;pose['rootRotation'][1]=20.
        with self.assertRaisesRegex(ValueError,'locked figure orientation'):
            text.changed(pose,dict(part='torso',movement='turn_left',amount=1.))
        self.assertEqual(pose['rootRotation'],[7.,20.,0.])
        other=text.neutral(self.root,'g9','pose-'+'1'*32,2)
        with self.assertRaisesRegex(ValueError,'locked figure orientation'):interaction([pose,other],'front_hug',lambda *_:None)
        self.assertEqual(pose['rootRotation'],[7.,20.,0.])

    def test_apply_rejects_changed_profile_and_corrupt_preview(self):
        record=self.generate();path=self.root/'temp/text'/f"{record['id']}.json"
        corrupt=copy.deepcopy(record);corrupt['prompt']='tampered';atomic_json(path,corrupt)
        with self.assertRaisesRegex(ValueError,'changed or expired'):text.accept(self.root,dict(id=record['id'],signature=record['signature']))
        atomic_json(path,record);rig=read_json(self.root/'data/rigs/g8f.json');rig['label']='changed';atomic_json(self.root/'data/rigs/g8f.json',rig)
        with self.assertRaisesRegex(ValueError,'profiles changed'):text.accept(self.root,dict(id=record['id'],signature=record['signature']))


    def test_preview_is_not_accepted_history_and_apply_requires_signature(self):
        result=self.generate();self.assertFalse(text.history(self.root))
        with self.assertRaises(ValueError):text.accept(self.root,dict(id=result['id'],signature='bad'))
        saved=text.accept(self.root,dict(id=result['id'],signature=result['signature']))
        self.assertEqual(saved,result);self.assertEqual(text.history(self.root)[0]['id'],result['id'])
        checked_poses(self.root,result['poses'][0]['imageId'],result['poses'])
        self.assertEqual(accepted(self.root,dict(id=result['id'],actorId=1))[0],result['poses'][0])
        with self.assertRaises(ValueError):text.accept(self.root,dict(id='../outside',signature='bad'))


    def test_semantic_validation_rejects_unknown_names_numeric_errors_and_actor_swaps(self):
        base=text.basic_intent(self.payload)
        invalid=[]
        for key,value in [('id',2),('recipe','teleport')]:
            intent=copy.deepcopy(base);intent['actors'][0][key]=value;invalid.append(intent)
        for amount in (True,float('nan'),-1,2):
            intent=copy.deepcopy(base);intent['actors'][0]['changes']=[dict(part='l_arm',movement='raise',amount=amount)];invalid.append(intent)
        intent=copy.deepcopy(base);intent['actors'][0]['expression']={'identityMorph':1};invalid.append(intent)
        for intent in invalid:
            with self.assertRaises(ValueError):text.validate_intent(intent,self.payload)

    def test_retired_requests_are_rejected_and_capability_signature_tracks_rigs(self):
        with self.assertRaises(ValueError):text.capability(self.root,dict(self.payload,mode='modify'))
        before=text.signature(text.capability(self.root,self.payload));rig=read_json(self.root/'data/rigs/g8f.json');rig['nodes'][0]['end'][0]+=.01;atomic_json(self.root/'data/rigs/g8f.json',rig)
        self.assertNotEqual(before,text.signature(text.capability(self.root,self.payload)))


    def test_cancel_never_writes_an_accepted_result(self):
        def cancelled(*_):raise InterruptedError('cancelled')
        p=self.payload
        with self.assertRaises(InterruptedError):text._generate_one(self.root,p,text.basic_intent(p),cancelled,body_seeds=[text.neutral(self.root,'g8f','pose-'+'0'*32,1)])
        self.assertFalse(text.history(self.root))


    def test_all_interaction_recipes_fit_mixed_generation_contacts(self):
        from textsolve import interaction
        from measurements import target_points
        poses=[self.generate(dict(self.payload,actors=[dict(id=1,rigId=rig)]))['poses'][0] for rig in ('g8f','g9')]
        poses[1]['personId']=2
        before=copy.deepcopy(poses)
        for kind in text.INTERACTIONS[1:]:
            with self.subTest(kind=kind):
                result=interaction(poses,kind,lambda *_:None)
                self.assertLessEqual(max(result[0]['textContacts']['gapsCm']),2.)
                self.assertLessEqual(result[0]['textContacts']['torsoPenetrationCm'],2.)
                for a,b in zip(before,result):
                    self.assertEqual(a['rig'],b['rig'])
                    old,_=target_points(a);new,_=target_points(b)
                    self.assertAlmostEqual(min(v[1] for k,v in old.items() if k.endswith(('heel','bigtoe','smalltoe'))),min(v[1] for k,v in new.items() if k.endswith(('heel','bigtoe','smalltoe'))),places=5)
        self.assertEqual(poses,before)

    def test_combined_script_has_one_undo_and_no_scale_setters(self):
        pose=self.generate()['poses'][0]
        source=dict(version=2,kind='text',engine='text-intent-v1',sceneId='text-'+'1'*32,face=dict(id=1,actions={a:0 for a in expression.ACTIONS},extras={'tongueOut':0},landmarks=[],box=[],matrix=[]),unknown=[],warnings=[])
        facial=dict(rigId='g8f',source=source,options=dict(regions={r:True for r in expression.REGIONS}),channels={})
        script=combined_script(pose,facial,dict(drivers=[],mappings=[]),'floor',dict(ack='test',cancel='test',jobId='test'))
        self.assertEqual(script.count('beginUndo()'),1);self.assertEqual(script.count('acceptUndo('),1);self.assertIn('bodyPlan.verify()',script);self.assertIn('cancelUndo()',script)
        self.assertNotIn('__POSESNAP_CONFIG__',script);self.assertNotIn('.setScale',script)

    def test_legacy_combined_export_uses_a_canonical_generation_and_keeps_pose_title(self):
        from editor import new_pose
        for rig_id,label in (('g8f','Genesis 8 Female'),('g8m','Genesis 8 Male'),('g9','Genesis 9')):
            pose=new_pose(self.root,rig_id);pose['label']='Both holding hands';pose['rig']['label']='Legacy custom name'
            before=copy.deepcopy(pose)
            facial=dict(rigId=rig_id)
            script=combined_script(pose,facial,dict(drivers=[],mappings=[]),'keep',dict(ack='test',cancel='test',jobId='test'))
            config=json.JSONDecoder().raw_decode(script.split('var job=',1)[1])[0]
            self.assertEqual(config['label'],label)
            self.assertEqual(config['body']['pose']['label'],'Both holding hands')
            self.assertEqual(pose,before)


if __name__=='__main__':unittest.main()
