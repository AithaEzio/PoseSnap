import copy
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from scipy.spatial.transform import Rotation

import textpose
import kimodo_generation
import body_contacts
from storage import atomic_json
from studio import semantics

ROOT=Path(__file__).resolve().parents[1]


class KimodoControlTests(unittest.TestCase):
    def setUp(self):
        base=ROOT/'temp/kimodo-control-tests';base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        for rig in ('g8f','g8m','g9'):
            atomic_json(self.root/f'data/rigs/{rig}.json',json.loads((ROOT/f'tests/fixtures/target-fit/{rig}.json').read_text()))


    def test_wrong_floor_support_is_not_accepted_as_standing(self):
        pose=textpose.neutral(self.root,'g9','pose-'+'0'*32,1)
        pose['bodyContacts']=dict(kind='crawl')
        with self.assertRaises(ValueError):body_contacts.verify(pose)
        for prompt,kind in [('A person on all fours','crawl'),('A seated person','seated'),('A person lying supine','lying'),('A handstand','inverted'),('A kneeling person','kneel')]:self.assertEqual(body_contacts.kind(prompt),kind)

    def test_floor_contracts_reject_missing_supports_and_wrong_facing(self):
        from unittest.mock import patch
        pose=textpose.neutral(self.root,'g9','pose-'+'0'*32,1);m=semantics(pose['rig'])
        frames,joints=textpose.frame(pose);joints[m['hip']]=np.array([0.,30.,0.]);joints[m['spine4']]=np.array([0.,30.,40.])
        from studio import rest_frame
        for side in ('l','r'):frames[m[side+'_hand']]=Rotation.align_vectors([[0.,-1.,0.]],[rest_frame(pose['rig'],side+'_hand',m)[:,2]])[0].as_matrix()
        markers={s+'_'+p:0. for s in ('l','r') for p in ('heel','bigtoe','smalltoe','palm','knee')};markers.update(hip=30.,spine4=30.,head=30.,l_elbow=20.,r_elbow=20.)
        pose['bodyContacts']=dict(kind='crawl',requirements={})
        markers['r_palm']=11.
        with patch('body_contacts.surfaces',return_value=(markers,joints,m,1.,frames)):
            with self.assertRaises(ValueError):body_contacts.verify(pose)
            markers['r_palm']=0.;body_contacts.verify(pose)
            markers['l_fingers']=-3.
            with self.assertRaises(ValueError):body_contacts.verify(pose)
        pose=textpose.neutral(self.root,'g9','pose-'+'0'*32,1);pose['rootRotation']=[90.,0.,0.]
        pose['bodyGenerator']=dict(floorRequirements=body_contacts.requirements('Lying supine'))
        body_contacts.place(pose,'lying');world,_=textpose.frame(pose)
        self.assertGreater((world[m['spine4']]@np.array([0.,0.,1.]))[1],.5)
        pose['bodyContacts']['requirements']['facing']='prone'
        with self.assertRaises(ValueError):body_contacts.verify(pose)

    def test_unqualified_handholding_layouts_do_not_silently_use_default_sides(self):
        from textconstraints import preflight
        payload=dict(mode='create',output='pose',prompt='Both holding hands',actors=[dict(id=1,rigId='g8f'),dict(id=2,rigId='g9')])
        self.assertIsNone(preflight(payload))
        for prompt in ('Both holding hands overhead','Person 1 right hand holding hands with Person 2 left hand','Both holding hands diagonally','Two people face each other and hold hands','Two people hold hands face-to-face','Both hold hands; Person 1 holds with the right hand','Person 1 left hand holding hands with the left hand of Person 2'):
            self.assertEqual(preflight(dict(payload,prompt=prompt))['status'],'clarify')
        self.assertIsNone(preflight(dict(payload,prompt='Person 1 holds with the left hand and Person 2 uses the right hand, both holding hands')))
        for prompt in ('A one-handed handstand','A handstand on one hand','A three-point crawl'):
            self.assertEqual(preflight(dict(payload,prompt=prompt))['status'],'clarify')
        self.assertEqual(body_contacts.requirements('Kneeling on the right knee')['kneeSide'],'r')

    def test_unbound_partner_arm_and_self_shoulder_target_need_clarification(self):
        from textconstraints import preflight
        payload=dict(mode='create',output='pose',prompt='',actors=[dict(id=1,rigId='g8f'),dict(id=2,rigId='g9')])
        for prompt in ('Person 2 hugs Person 1 with the right arm','Person 2 right hand on Person 2 left shoulder','Person 1 left hand on their own left shoulder','Person 1 right arm front hug','Person 2 hugs Person 1, Person 2 right arm side hug'):
            with self.subTest(prompt=prompt):self.assertEqual(preflight(dict(payload,prompt=prompt))['status'],'clarify')
        for prompt in ('Person 2 right arm side hug Person 1','Person 2 puts a right hand on Person 1 left shoulder','Two people front hug'):
            with self.subTest(prompt=prompt):self.assertIsNone(preflight(dict(payload,prompt=prompt)))

    def test_compatible_pin_survives_partner_contact_refitting(self):
        from textsolve import interaction
        a=textpose.neutral(self.root,'g8f','pose-'+'0'*32,1);b=textpose.neutral(self.root,'g9','pose-'+'0'*32,2)
        pair=interaction([a,b],'handhold',lambda *_:None)
        mapping=semantics(pair[0]['rig']);frames,points=textpose.frame(pair[0]);name=mapping['l_foot']
        pair[0]['pins']={name:dict(position=points[name].tolist(),rotation=Rotation.from_matrix(frames[name]).as_quat().tolist())}
        original=copy.deepcopy(pair);pair[1]['translation'][0]+=3.
        solved=interaction(pair,'handhold',lambda *_:None)
        textpose.protected(original[0],solved[0],[])
        self.assertLessEqual(max(solved[0]['textContacts']['gapsCm']),2.)
        self.assertEqual(solved[0]['rig'],original[0]['rig'])
        self.assertEqual(solved[1]['rig'],original[1]['rig'])

    def test_mixed_proportion_interactions_keep_rig_geometry_and_contact_tolerance(self):
        from textsolve import interaction
        from daz import duf
        for kind in ('front_hug','side_hug','handhold','shoulder'):
            a=textpose.neutral(self.root,'g8m','pose-'+'0'*32,1);b=textpose.neutral(self.root,'g9','pose-'+'0'*32,2)
            # Different captured proportions are test geometry, not scale dials.
            for node in b['rig']['nodes']:
                for key in ('center','end'):node[key]=[v*.82 for v in node[key]]
            original=copy.deepcopy([a,b]);solved=interaction([a,b],kind,lambda *_:None)
            for before,after in zip(original,solved):
                self.assertEqual(before['rig'],after['rig'])
                self.assertLessEqual(max(after['textContacts']['gapsCm']),2.)
                self.assertNotIn('scale',json.dumps(duf(after,'keep')))

    def test_conflicting_pinned_contact_keeps_the_original_scene(self):
        from textsolve import interaction
        a=textpose.neutral(self.root,'g8f','pose-'+'0'*32,1);b=textpose.neutral(self.root,'g9','pose-'+'0'*32,2)
        a['translation'][0]=-200.;b['translation'][0]=200.
        for pose,side in ((a,'l'),(b,'r')):
            name=semantics(pose['rig'])[side+'_hand'];frames,points=textpose.frame(pose)
            pose['pins']={name:dict(position=points[name].tolist(),rotation=Rotation.from_matrix(frames[name]).as_quat().tolist())}
        original=copy.deepcopy([a,b])
        with self.assertRaises(ValueError):interaction([a,b],'handhold',lambda *_:None)
        self.assertEqual([a,b],original)

    def test_reachable_contact_cannot_bypass_partner_layout_validation(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from textsolve import interaction
        from measurements import target_points
        for kind in ('side_hug','handhold'):
            with self.subTest(kind=kind):
                pair=[textpose.neutral(self.root,r,'pose-'+'0'*32,i+1) for i,r in enumerate(('g8f','g9'))]
                states=[target_points(p,include_frames=True) for p in pair]
                points=[copy.deepcopy(s[0]) for s in states]
                for key in points[1]:points[1][key]+=np.array([100.,0.,20.])
                hip=(points[0]['l_hip']+points[0]['r_hip'])/2;chest=(points[0]['l_shoulder']+points[0]['r_shoulder'])/2
                if kind=='side_hug':
                    height=max(100.,np.ptp(np.asarray([n['center'] for n in pair[0]['rig']['nodes']]),axis=0)[1])
                    spine=semantics(pair[0]['rig'])['spine4']
                    back=hip+(chest-hip)*.65+states[0][2][0][spine]@np.array([0.,0.,-height*.065])
                    points[1]['l_palm']=back
                    points[1]['l_elbow']=(back+points[1]['l_shoulder'])/2+np.array([0.,0.,-30.])
                    points[1]['l_wrist']=back+np.array([0.,0.,-3.])
                else:
                    clasp=hip+np.array([50.,-8.,17.])
                    for actor,side in ((0,'l'),(1,'r')):
                        points[actor][side+'_palm']=clasp.copy()
                        points[actor][side+'_wrist']=clasp+np.array([0.,0.,3.])
                        points[actor][side+'_elbow']=(clasp+points[actor][side+'_shoulder'])/2
                        points[actor][side+'_index1']=points[actor][side+'_wrist']+np.array([1.,0.,0.])
                        points[actor][side+'_pinky1']=points[actor][side+'_wrist']+np.array([0.,1.,0.])
                original=copy.deepcopy(pair)
                # A converged optimizer is not proof of a coherent composition.
                # Reachable palms must not hide a distant or depth-offset pair.
                def measured(pose,**_):
                    i=pose['personId']-1
                    return points[i],states[i][1],states[i][2]
                with patch('textsolve.target_points',side_effect=measured),patch('textsolve.least_squares',side_effect=lambda _,x,**kw:SimpleNamespace(x=x)):
                    with self.assertRaisesRegex(ValueError,'too far apart|beside each other'):
                        interaction(pair,kind,lambda *_:None,'Person 2 side hug Person 1')
                self.assertEqual(pair,original)

    def test_free_form_contacts_survive_the_complete_kimodo_plan(self):
        from textconstraints import interaction_request
        for prompt,expected in [('Two people holding hands','handhold'),('Two people front hug','front_hug'),('Two people side hug','side_hug'),('Person 2 puts a right hand on Person 1 left shoulder','shoulder')]:
            payload=dict(mode='create',output='pose',prompt=prompt,actors=[dict(id=1,rigId='g8f'),dict(id=2,rigId='g9')],bodyGenerator='kimodo',creative=True)
            intent=kimodo_generation.plan(self.root,payload,{},None,lambda *_:None)
            self.assertEqual(intent['status'],'plan');self.assertEqual(intent['interaction'],expected)
        self.assertEqual(interaction_request('A person shrugs'),'none')
        self.assertEqual(interaction_request('Do not hug'),'none')


    def test_returned_scene_measures_requested_contacts_and_actor_sides(self):
        from measurements import target_points
        payload=dict(mode='create',output='pose',prompt='Person 2 puts a right hand on Person 1 left shoulder',actors=[dict(id=1,rigId='g8f'),dict(id=2,rigId='g9')],bodyGenerator='kimodo')
        intent=kimodo_generation.plan(self.root,payload,{},None,lambda *_:None)
        bodies=[textpose.neutral(self.root,a['rigId'],'pose-'+'0'*32,a['id']) for a in payload['actors']]
        for body in bodies:
            body['bodyGenerator']=dict(provider='kimodo',selectionScore=0.,sourceClearanceCm=0.)
            body['footSupport']=[dict(side=s,state='flat') for s in ('l','r')]
        result=textpose._generate_one(self.root,payload,intent,lambda *_:None,body_seeds=bodies)
        poses=result['poses'];a,b=[target_points(p)[0] for p in poses]
        self.assertLessEqual(np.linalg.norm(b['r_palm']-a['l_shoulder']),2.)
        self.assertEqual(poses[0]['textContacts']['attachments'],[dict(actor=2,part='r_palm',partner=1,target='l_shoulder')])


if __name__=='__main__':unittest.main()
