import copy,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from test_interaction import fixture
from posture import core_frame,drift,infer_support,persist_baseline,load_baselines,context_key,guidance_options
from coupled import fit_targets
from measurements import target_points,reference_camera,project_target
from refinement import refine
from storage import atomic_json,read_json
from wholebody import signature
from daz import duf

def measured_fixture(tilt=12):
    source,pose=fixture(1,0)
    spine=dict(id='abdomenLower',parent='hip',center=[0,110,0],end=[0,140,0],type='bone',orientation=[0,0,0],order='XYZ',limits={})
    pose['rig']['nodes'].insert(2,spine);next(n for n in pose['rig']['nodes'] if n['id']=='chestUpper')['parent']='abdomenLower'
    pose['rotations']['abdomenLower']=[-tilt,0,0];pose['rootRotation']=[0,0,0];pose['translation']=[0,0,-400]
    pose['referenceCamera']=reference_camera(source,[0,0,0]);source['personBox']=[300,10,800,650]
    points,_=target_points(pose)
    source['measurements']=[dict(personId=1,name=name,region='l_foot' if name.startswith('l_') and name.endswith(('heel','bigtoe','smalltoe')) else 'r_foot' if name.startswith('r_') and name.endswith(('heel','bigtoe','smalltoe')) else 'body',known=True,weight=.95,xy=project_target(p,pose['referenceCamera']).tolist()) for name,p in points.items() if name.endswith(('shoulder','elbow','wrist','hip','knee','ankle','heel','bigtoe','smalltoe'))]
    source['restPositions']=(np.asarray([n['center'] for n in pose['rig']['nodes']])/100).tolist()
    source['keypoints3d']=np.zeros((70,3)).tolist()
    return source,pose

class PostureTests(unittest.TestCase):
    def test_shoulder_motion_is_not_torso_lean(self):
        _,pose=measured_fixture(15)
        for side,sign in (('l',1),('r',-1)):
            collar=dict(id=side+'Collar',parent='chestUpper',center=[sign*5,145,0],end=[sign*20,145,0],type='bone',orientation=[0,0,0],order='XYZ',limits={})
            pose['rig']['nodes'].insert(4,collar)
            next(n for n in pose['rig']['nodes'] if n['id']==side+'ShldrBend')['parent']=collar['id']
            pose['rotations'][collar['id']]=[0,0,0]
        original=core_frame(pose);pose['rotations']['lCollar']=[0,45,30];pose['rotations']['rCollar']=[0,-45,-30]
        self.assertAlmostEqual(core_frame(pose)['tilt'],original['tilt'],places=10)
        self.assertLess(drift(pose,dict(pose,rotations={**pose['rotations'],'lCollar':[0,0,0],'rCollar':[0,0,0]}))['coreRotationDegrees'],1e-8)
        pose['rootRotation'][0]=5
        self.assertAlmostEqual(core_frame(pose)['tilt']-original['tilt'],5,places=8)
    def test_new_target_policy_gets_its_own_immutable_anchor(self):
        source,pose=measured_fixture()
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);persist_baseline(folder,[source],[pose]);old_id=pose['postureBaseline']['id']
            old_bytes=(folder/'posture-baselines'/f'{old_id}.json').read_bytes()
            corrected=copy.deepcopy(pose);corrected['targetFitVersion']=2;corrected['rotations']['lHand']=[12,0,0]
            persist_baseline(folder,[source],[corrected]);new_id=corrected['postureBaseline']['id']
            self.assertNotEqual(old_id,new_id)
            self.assertEqual((folder/'posture-baselines'/f'{old_id}.json').read_bytes(),old_bytes)
            self.assertEqual(load_baselines(folder,[source],[corrected])[0]['rotations']['lHand'],[12,0,0])
    def test_auto_lifted_leg_is_air_not_raised_heel(self):
        source,pose=measured_fixture();source['keypoints3d'][15][1]=.70;source['keypoints3d'][16][1]=.70;source['keypoints3d'][17][1]=.75
        states=infer_support(source,pose)
        self.assertEqual(states['l']['state'],'air');self.assertEqual(states['r']['state'],'flat')
        source.pop('keypoints3d');self.assertEqual(infer_support(source,pose)['r']['state'],'unknown')
    def test_both_air_retains_floor_height_and_export(self):
        source,pose=measured_fixture();pose['translation'][1]=40
        result=fit_targets([source],[pose],support=[dict(personId=1,side=s,state='air') for s in ('l','r')],warm_start=True,preserve=True)
        candidate=result['poses'][0]
        self.assertEqual(candidate['referenceCamera'],pose['referenceCamera']);self.assertAlmostEqual(candidate['translation'][1],40)
        self.assertEqual([p['state'] for p in result['diagnostics']['support']],['air','air'])
        rows=duf(candidate,'floor')['scene']['animations'];self.assertEqual(next(r['keys'][0][1] for r in rows if r['url'].endswith('translation/y/value')),40)
        with self.assertRaisesRegex(ValueError,'airborne'):duf(candidate,'origin')
    def test_preserves_world_core_under_detail_evidence_and_repeated_passes(self):
        source,pose=measured_fixture(20);anchor=copy.deepcopy(pose)
        next(p for p in source['measurements'] if p['name']=='l_wrist')['xy'][0]+=8
        result=fit_targets([source],[pose],warm_start=True,preserve=True,anchors=[anchor])
        self.assertTrue(result['diagnostics']['accepted']);candidate=result['poses'][0]
        self.assertLess(drift(candidate,pose)['coreRotationDegrees'],1e-6)
        repeated=fit_targets([source],[candidate],warm_start=True,preserve=True,anchors=[anchor])
        self.assertLess(drift(repeated['poses'][0],anchor)['coreRotationDegrees'],1e-6)
        self.assertEqual(candidate['rig'],anchor['rig']);self.assertEqual(candidate['rootRotation'],anchor['rootRotation'])
    def test_upright_is_bounded_and_does_not_zero_the_spine(self):
        source,pose=measured_fixture()
        result=fit_targets([source],[pose],warm_start=True,preserve=True,guidance=[dict(personId=1,preset='upright',strength=.35)])
        self.assertTrue(result['diagnostics']['accepted'],result['diagnostics'])
        candidate=result['poses'][0]
        self.assertLess(abs(core_frame(candidate)['tilt']),abs(core_frame(pose)['tilt'])-.2)
        self.assertNotEqual(candidate['rotations']['abdomenLower'],[0,0,0]);self.assertEqual(candidate['rootRotation'],pose['rootRotation'])
        self.assertEqual(candidate['quality']['coverage']['observed'],len(source['measurements']))
    def test_repeated_interaction_keeps_original_root_budgets_and_studio_intent(self):
        source,pose=measured_fixture();other_source,other_pose=copy.deepcopy(source),copy.deepcopy(pose)
        other_source['personId']=2;other_source['personKey']='2';other_pose['personId']=2
        anchors=copy.deepcopy([pose,other_pose]);pose['translation'][0]+=7.9;pose['rootRotation'][1]=1.4
        other_pose['translation'][0]+=40;other_pose['rootRotation'][1]=9
        for _ in range(3):
            result=fit_targets([source,other_source],[pose,other_pose],warm_start=True,preserve=True,anchors=anchors)
            pose,other_pose=result['poses']
            self.assertLessEqual(abs(pose['translation'][0]-anchors[0]['translation'][0]),8.0001)
            self.assertLessEqual(abs(pose['rootRotation'][1]),1.5001)
            # Deliberate edits outside the automatic budget remain fixed.
            self.assertAlmostEqual(other_pose['translation'][0],40)
            self.assertAlmostEqual(other_pose['rootRotation'][1],9)
    def test_guidance_validation_and_compensating_world_rotation(self):
        _,pose=measured_fixture();other=copy.deepcopy(pose);other['rootRotation'][0]=8;other['rotations']['abdomenLower'][0]-=8
        # A compensated torso angle still changes the pelvis's world frame.
        self.assertGreater(drift(other,pose)['coreRotationDegrees'],7)
        for hint in (dict(personId=2,preset='upright',strength=.35),dict(personId=1,preset='upright',strength=float('nan')),dict(personId=1,preset='unknown',strength=.35)):
            with self.assertRaises(ValueError):guidance_options([hint],[pose])
    def test_immutable_anchor_and_changed_source_invalidation(self):
        source,pose=measured_fixture()
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);persist_baseline(folder,[source],[pose]);ident=pose['postureBaseline']['id'];before=(folder/'posture-baselines'/f'{ident}.json').read_bytes()
            changed=copy.deepcopy(pose);changed['rotations']['abdomenLower'][0]=20;persist_baseline(folder,[source],[changed])
            self.assertEqual(before,(folder/'posture-baselines'/f'{ident}.json').read_bytes());self.assertEqual(load_baselines(folder,[source],[changed])[0]['rotations'],pose['rotations'])
            source['personKey']='different'
            with self.assertRaisesRegex(ValueError,'extraction or rig changed'):load_baselines(folder,[source],[changed])

class PreviewTransactionTests(unittest.TestCase):
    def test_preview_cancel_apply_stale_and_undo_current_context(self):
        source,pose=measured_fixture()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source['refinementSignature']=signature(root);atomic_json(root/'people.json',[dict(id=1)]);atomic_json(root/'refinement.json',dict(previous=True));before=(root/'refinement.json').read_bytes()
            payload=dict(version=2,policyVersion=1,action='preview',imageId='same',currentPoses=[pose])
            def fitted(sources,poses,*args,**kwargs):
                result=copy.deepcopy(poses);result[0]['rotations']['lHand']=[5,0,0]
                return dict(version=3,poses=result,diagnostics=dict(accepted=True),imageId='same')
            with patch('refinement.image_dir',return_value=root),patch('editor.checked_poses'),patch('refinement.cached_source',return_value=source),patch('rigs.profile',return_value=pose['rig']),patch('coupled.fit_targets',side_effect=fitted) as fitting:
                preview=refine(root,payload,lambda *_:None)
                self.assertEqual((root/'refinement.json').read_bytes(),before);self.assertEqual(fitting.call_args.args[1][0]['rotations'],pose['rotations'])
                apply=dict(payload,action='apply',previewId=preview['previewId'])
                changed=copy.deepcopy(pose);changed['rotations']['lHand']=[1,0,0]
                with self.assertRaisesRegex(ValueError,'pose, extraction or measurements changed'):refine(root,dict(apply,currentPoses=[changed]),lambda *_:None)
                self.assertEqual((root/'refinement.json').read_bytes(),before)
                result=refine(root,apply,lambda *_:None);self.assertEqual(read_json(root/'refinement.json')['poses'],result['poses'])
                # Undo's original current pose overrides the most recent disk fit.
                next_preview=refine(root,payload,lambda *_:None)
                self.assertEqual(fitting.call_args.args[1][0]['rotations'],pose['rotations'])
                saved=(root/'refinement.json').read_bytes()
                refine(root,dict(payload,action='cancel',previewId=next_preview['previewId']),lambda *_:None)
                self.assertFalse((root/'temp/refinement-previews'/f"{next_preview['previewId']}.json").exists());self.assertEqual((root/'refinement.json').read_bytes(),saved)
    def test_cancel_during_preview_never_commits(self):
        source,pose=measured_fixture()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source['refinementSignature']=signature(root);atomic_json(root/'people.json',[dict(id=1)]);atomic_json(root/'refinement.json',dict(previous=True));before=(root/'refinement.json').read_bytes()
            with patch('refinement.image_dir',return_value=root),patch('editor.checked_poses'),patch('refinement.cached_source',return_value=source),patch('rigs.profile',return_value=pose['rig']):
                with self.assertRaises(InterruptedError):refine(root,dict(version=2,policyVersion=1,imageId='same',currentPoses=[pose]),lambda *_:(_ for _ in ()).throw(InterruptedError()))
            self.assertEqual(before,(root/'refinement.json').read_bytes())

if __name__=='__main__':unittest.main()
