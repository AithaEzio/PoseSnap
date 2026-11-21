import copy
import ast
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock
import numpy as np
from cropped import classify,prepare,zero_nodes,neutral,adjust_accepted
from measurements import MHR,target_points
from wholebody import BODY
from test_interaction import fixture
from test_posture import measured_fixture
from coupled import fit_targets
from retarget import retarget
from daz import duf

ROOT=Path(__file__).resolve().parents[1]


def cropped_source():
    source,pose=fixture(1,0)
    source.update(extractionMethod='smart',imageSize=[1200,900],personBox=[300,100,850,900],projectedKeypoints=[[600,400] for _ in range(70)])
    raw=[[600,400,.95] for _ in range(17)]
    for i,name in BODY.items():
        if any(part in name for part in ('knee','ankle')):
            raw[i]=[600,899,.1];source['projectedKeypoints'][MHR[name]]=[600,1050]
    source['measurements']=[dict(name=name,xy=raw[i][:2],region='body',known=True,weight=.99,personId=1) for i,name in BODY.items()]
    return source,dict(id=1,box=source['personBox'],keypoints=raw),pose


class CropTests(unittest.TestCase):
    def test_unobserved_detail_on_a_zeroed_chain_cannot_pull_the_visible_pose(self):
        source,person,_=cropped_source()
        source['measurements'].append(dict(name='l_bigtoe',region='l_foot',xy=[600,400],known=True,weight=.99,personId=1))
        source['projectedKeypoints'][MHR['l_bigtoe']]=[600,400]
        result=prepare(ROOT,source,dict(zeroCroppedJoints=True),person)
        self.assertIn('l_foot',result['cropPolicy']['zeroSemantics'])
        self.assertFalse(next(p for p in result['measurements'] if p['name']=='l_bigtoe')['known'])
        self.assertTrue(next(p for p in result['measurements'] if p['name']=='l_wrist')['known'])

    def test_g8_anatomical_attachments_use_bend_centres_not_distal_twist_centres(self):
        from rigs import default_profile
        from retarget import fk
        for rig_id in ('g8f','g8m','g9'):
            rig=default_profile(rig_id);pose=dict(rig=rig,rotations={},translation=[0,0,0])
            points=target_points(pose)[0];positions=fk(rig,{})[1]
            for side in ('l','r'):
                for name,g8,g9 in (('shoulder','ShldrBend','_upperarm'),('elbow','ForearmBend','_forearm'),('hip','ThighBend','_thigh')):
                    np.testing.assert_allclose(points[side+'_'+name],positions[side+(g9 if rig_id=='g9' else g8)],atol=1e-10)
    def test_accepted_crop_adjustment_keeps_visible_values_placement_and_pins(self):
        from measurements import reference_camera
        from posture import persist_baseline
        source,person,pose=cropped_source();pose['referenceCamera']=reference_camera(source,[0,0,0])
        pose['rotations']['lShin']=[45,0,0];pose['rotations']['rShin']=[30,0,0]
        pose['rotations']['rShldrBend']=[10,12,15];pose['rootRotation']=[0,15,0]
        pose['pins']={'lFoot':{'position':[1,2,3]}}
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);persist_baseline(folder,[source],[pose]);before=copy.deepcopy(pose)
            derived=prepare(ROOT,source,dict(zeroCroppedJoints=True),person)
            with patch('editor.checked_poses'):
                result=adjust_accepted(ROOT,folder,[source],[derived],dict(currentPoses=[pose]))
            after=result['poses'][0]
            self.assertEqual(pose,before)
            self.assertEqual(after['rotations']['lShin'],[45,0,0])
            self.assertEqual(after['rotations']['rShin'],[0,0,0])
            self.assertEqual(after['rotations']['rShldrBend'],before['rotations']['rShldrBend'])
            for key in ('translation','rootRotation','referenceCamera','pins','rig'):self.assertEqual(after[key],before[key])
            self.assertTrue(result['diagnostics']['visiblePosePreserved'])
            self.assertIsNone(adjust_accepted(ROOT,folder,[source],[derived],dict(currentPoses=[pose],rigId='g9')))

    def test_interaction_preparation_never_builds_a_discarded_target_preview(self):
        tree=ast.parse((ROOT/'worker/main.py').read_text())
        function=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='dispatch')
        engine=Mock();engine.solve.return_value=dict(personId=1);engine.timings=dict(cacheHit=True,totalSeconds=.01)
        namespace=dict(ROOT=ROOT,ENGINE=engine,KIMODO=None)
        exec(compile(ast.Module(body=[function],type_ignores=[]),'worker/main.py','exec'),namespace)
        with patch('retarget.retarget',side_effect=AssertionError('Discarded target must not be fitted')):
            result=namespace['dispatch']('solve',dict(prepareInteraction=True,extractionContext='interaction'),lambda *_:None)
        self.assertEqual(result,dict(personId=1,sourceReady=True,executionTimings=engine.timings))
        with self.assertRaisesRegex(ValueError,'context'):namespace['dispatch']('solve',dict(prepareInteraction=True),lambda *_:None)

    def test_clipped_confident_landmark_guesses_do_not_override_absent_detector_anchors(self):
        source,person,_=cropped_source();before=copy.deepcopy(source)
        result=prepare(ROOT,source,dict(zeroCroppedJoints=True),person)
        self.assertEqual(source,before)
        for side in ('l','r'):
            self.assertIn(side+'_thigh',result['cropPolicy']['zeroSemantics'])
            self.assertIn(side+'_shin',result['cropPolicy']['zeroSemantics'])
            self.assertFalse(next(p for p in result['measurements'] if p['name']==side+'_knee')['known'])
            self.assertNotIn(side+'_upperarm',result['cropPolicy']['zeroSemantics'])

    def test_low_confidence_and_occlusion_inside_image_do_not_mean_cropped(self):
        source,person,_=cropped_source();source['personBox']=[300,100,850,800]
        for i in (13,14,15,16):person['keypoints'][i]=[600,500,.1]
        source['projectedKeypoints']=[[600,500] for _ in range(70)]
        for p in source['measurements']:p.update(xy=[600,500],known=False)
        result=prepare(ROOT,source,dict(zeroCroppedJoints=True),person)
        self.assertFalse(result['cropPolicy']['zeroSemantics'])
        self.assertEqual(result['cropPolicy']['landmarks']['l_knee']['state'],'uncertain')

    def test_full_frame_noop_and_partial_finger_segment(self):
        source,person,_=cropped_source();source['personBox']=[300,100,850,800]
        for point in person['keypoints']:point[2]=.99
        result=prepare(ROOT,source,dict(zeroCroppedJoints=True),person)
        self.assertFalse(result['cropPolicy']['zeroSemantics'])
        source['personBox'][2]=1200
        for part in (1,2,3):
            name='l_index'+str(part);source['measurements'].append(dict(name=name,region='l_hand',xy=[1100+part*10,300],known=True,weight=.99,personId=1))
        source['measurements'].append(dict(name='l_indextip',region='l_hand',xy=[1250,300],known=False,weight=.99,personId=1))
        source['projectedKeypoints'][MHR['l_indextip']]=[1250,300]
        result=prepare(ROOT,source,dict(zeroCroppedJoints=True),person)
        self.assertIn('l_index3',result['cropPolicy']['zeroSemantics'])
        self.assertNotIn('l_index2',result['cropPolicy']['zeroSemantics'])
        self.assertNotIn('l_hand',result['cropPolicy']['zeroSemantics'])

    def test_owned_visible_hand_detail_protects_arm_when_cropped_elbow_hides_wrist_anchor(self):
        source,person,_=cropped_source();source['personBox'][2]=1200
        person['keypoints'][8]=[1250,450,.01];person['keypoints'][10]=[900,450,.07]
        source['projectedKeypoints'][8]=[1250,450]
        for part in ('thumb1','thumb2','thumb3','index1','index2','index3','middle1','middle2'):
            source['measurements'].append(dict(name='r_'+part,xy=[900,400],region='r_hand',known=True,weight=.99,personId=1))
        wrist=next(p for p in source['measurements'] if p['name']=='r_wrist');wrist.update(xy=[900,450],known=True)
        result=prepare(ROOT,source,dict(zeroCroppedJoints=True),person)
        self.assertNotIn('r_upperarm',result['cropPolicy']['zeroSemantics'])
        self.assertNotIn('r_forearm',result['cropPolicy']['zeroSemantics'])

    def test_original_boundary_not_person_crop_and_visible_descendant_keeps_its_chain(self):
        source,person,_=cropped_source();source['personBox']=[300,100,850,800]
        source['projectedKeypoints'][7]=[1400,400];person['keypoints'][7]=[1400,400,.1]
        self.assertEqual(classify(source,person)['l_elbow']['state'],'uncertain')
        source['personBox'][2]=1200
        derived=prepare(ROOT,source,dict(zeroCroppedJoints=True),person)
        self.assertEqual(derived['cropPolicy']['landmarks']['l_elbow']['state'],'cropped')
        self.assertNotIn('l_upperarm',derived['cropPolicy']['zeroSemantics'])

    def test_full_frame_and_toggle_off_preserve_channels_on_all_rigs(self):
        from rigs import default_profile
        source,person,_=cropped_source()
        source['names']=['root','c_head','l_upleg','l_lowleg','r_upleg','r_lowleg']
        source['parents']=[-1,0,0,2,0,4]
        source['restPositions']=[[0,1,0],[0,1.7,0],[.1,1,0],[.1,.5,0],[-.1,1,0],[-.1,.5,0]]
        source['rotations']=np.tile(np.eye(3),(6,1,1)).tolist();source['restRotations']=copy.deepcopy(source['rotations'])
        source['positions']=copy.deepcopy(source['restPositions'])
        from scipy.spatial.transform import Rotation
        source['rotations'][3]=Rotation.from_euler('x',70,degrees=True).as_matrix().tolist()
        source['rotations'][5]=Rotation.from_euler('x',55,degrees=True).as_matrix().tolist()
        for rig_id in ('g8f','g8m','g9'):
            rig=default_profile(rig_id)
            original=retarget(source,rig)
            off=retarget(prepare(ROOT,source,dict(zeroCroppedJoints=False),person),rig)
            self.assertEqual(original['rotations'],off['rotations'])
            derived=prepare(ROOT,source,dict(zeroCroppedJoints=True),person);on=retarget(derived,rig)
            self.assertTrue(on['cropPolicy']['joints'])
            for node in zero_nodes(derived,rig):
                for axis,value in enumerate(on['rotations'].get(node,[0,0,0])):
                    n=next(n for n in rig['nodes'] if n['id']==node);key='xyz'[axis];limit=n['limits'].get(key,{})
                    if not limit.get('locked') and key not in n.get('driven',[]) and (not limit.get('clamped') or limit['min']<=0<=limit['max']):self.assertLess(abs(value),.1)
            for node in original['rotations'].keys()-zero_nodes(derived,rig):self.assertEqual(original['rotations'][node],on['rotations'][node])
            self.assertEqual(rig,on['rig'])
            animations=duf(on,'keep')['scene']['animations']
            self.assertFalse(any('/scale/' in row['url'] for row in animations))

    def test_pure_defaults_validation_and_ownership(self):
        source,person,_=cropped_source();source['extractionMethod']='pure'
        result=prepare(ROOT,source,dict(zeroCroppedJoints=True),person)
        self.assertFalse(result['cropPolicy']['enabled'])
        source['extractionMethod']='smart'
        self.assertTrue(prepare(ROOT,source,{},person)['cropPolicy']['enabled'])
        with self.assertRaisesRegex(ValueError,'preference'):prepare(ROOT,source,dict(zeroCroppedJoints='on'),person)
        with self.assertRaisesRegex(ValueError,'another person'):classify(source,dict(person,id=2))

    def test_neutral_respects_locks_drivers_and_limits(self):
        node=dict(limits=dict(x=dict(min=5,max=20,clamped=True),y=dict(locked=True)),driven=['z'])
        self.assertEqual(neutral(node,[10,12,14]),[5.,12,14])

    def test_confirmed_hand_contact_preserves_cropped_arm_chain(self):
        source,person,_=cropped_source()
        for index in (7,9):person['keypoints'][index]=[1300,400,.1];source['projectedKeypoints'][MHR[BODY[index]]]=[1300,400]
        source['personBox'][2]=1200
        contact=dict(personId=1,otherId=2,part='l_palm',region='r_palm',confirmed=True,enabled=True)
        derived=prepare(ROOT,source,dict(zeroCroppedJoints=True,contacts=[contact]),person)
        self.assertNotIn('l_upperarm',derived['cropPolicy']['zeroSemantics'])
        self.assertNotIn('l_forearm',derived['cropPolicy']['zeroSemantics'])

    def test_target_fit_does_not_rebend_neutral_channels_or_undo_manual_studio_edits(self):
        source,pose=measured_fixture()
        source['extractionMethod']='smart'
        pose['cropPolicy']=dict(version=1,enabled=True,zeroSemantics=['l_thigh','l_shin','l_foot'],joints=['lThighBend','lShin','lFoot'])
        for name in ('l_knee','l_ankle','l_heel','l_bigtoe','l_smalltoe'):
            for p in source['measurements']:
                if p['name']==name:p['known']=False
        source['cropPolicy']=dict(version=1,enabled=True,zeroSemantics=['l_thigh','l_shin','l_foot'])
        for value in (0.,22.):
            pose['rotations']['lShin']=[value,0,0]
            result=fit_targets([source],[pose],preserve=True)['poses'][0]
            self.assertEqual(result['rotations']['lShin'],[value,0,0])
            self.assertEqual(result['footSupport'][0]['state'],'unknown')


if __name__=='__main__':unittest.main()
