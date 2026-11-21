"""Regressions from the independent Smart Fit audit; no inference or DAZ."""
import ast,copy,inspect,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace,ModuleType
from unittest.mock import patch
import numpy as np
from scipy.spatial.transform import Rotation
from test_posture import measured_fixture
from test_interaction import fixture
from coupled import fit_targets
from cropped import prepare
from measurements import target_points,project_target
from posture import context_key
from storage import atomic_json

ROOT=Path(__file__).resolve().parents[1]

class Captured(Exception):pass

class SmartReleaseTests(unittest.TestCase):
    def test_absent_coordinates_do_not_zero_an_occluded_arm(self):
        source,_=measured_fixture(0)
        source.update(extractionMethod='smart',imageSize=[1200,900],personBox=[0,100,850,800],projectedKeypoints=[[600,400] for _ in range(70)])
        source['measurements']=[dict(name=n,xy=[600,400],region='body',known=True,weight=.99,personId=1) for n in ('l_elbow','l_wrist')]
        raw=[[600,400,.95] for _ in range(17)];raw[7]=raw[9]=[0,0,0]
        result=prepare(ROOT,source,dict(zeroCroppedJoints=True),dict(id=1,box=source['personBox'],keypoints=raw))
        self.assertNotIn('l_upperarm',result['cropPolicy']['zeroSemantics'])
        self.assertEqual(result['cropPolicy']['landmarks']['l_elbow']['state'],'uncertain')

    def test_pin_target_and_component_changes_invalidate_context(self):
        _,pose=measured_fixture(0);base=context_key([pose]);pose['pins']={'lHand':{'position':[1,2,3]}}
        self.assertNotEqual(base,context_key([pose]));key=context_key([pose]);pose['pins']['lHand']['position'][0]+=7
        self.assertNotEqual(key,context_key([pose]));key=context_key([pose]);pose['pins']['lHand']['rotation']=[0,0,0,1]
        self.assertNotEqual(key,context_key([pose]))

    def test_reachable_soft_pin_changes_the_actual_fitted_result(self):
        source,pose=measured_fixture(0);state=target_points(pose,True)[2];target=state[1]['lHand'].tolist()
        pose['pins']={'lHand':{'position':target,'rotation':Rotation.from_matrix(state[0]['lHand']).as_quat().tolist()}}
        for p in source['measurements']:
            if p['name']=='l_wrist':p['xy']=(np.array(p['xy'])+[15,5]).tolist()
        pinned=fit_targets([source],[pose],warm_start=True,preserve=True)
        other=copy.deepcopy(pose);other.pop('pins');control=fit_targets([source],[other],warm_start=True,preserve=True)
        gap=np.linalg.norm(target_points(pinned['poses'][0],True)[2][1]['lHand']-target)
        self.assertLess(gap,.5);self.assertNotEqual(pinned['poses'][0]['rotations'],control['poses'][0]['rotations'])
        self.assertEqual(pinned['poses'][0]['pins'],pose['pins']);self.assertTrue(pinned['diagnostics']['pins'])

    def test_floating_flat_support_has_a_nonzero_floor_objective(self):
        source,pose=measured_fixture(0);pose['translation'][1]=5
        points=target_points(pose)[0]
        for p in source['measurements']:p['xy']=project_target(points[p['name']],pose['referenceCamera']).tolist()
        captured={}
        def stop(fun,x,**kwargs):captured['residual']=fun(x);raise Captured()
        with patch('coupled.least_squares',side_effect=stop),self.assertRaises(Captured):
            fit_targets([source],[pose],support=[dict(personId=1,side=s,state='flat') for s in ('l','r')],warm_start=True,preserve=True)
        self.assertGreater(np.linalg.norm(captured['residual']),1)

    def test_duplicate_hands_with_tied_owners_are_not_known_twice(self):
        from wholebody import resolve_ownership
        groups=[[dict(personId=i,name='l_wrist',region='body',xy=[x,100],known=True,weight=.95),dict(personId=i,name='l_wrist',region='l_hand',xy=[100,100],known=True,weight=.95),dict(personId=i,name='l_indextip',region='l_hand',xy=[110,100],known=True,weight=.95)] for i,x in ((1,99),(2,101))]
        result=resolve_ownership(groups)
        self.assertTrue(all(not p['known'] for group in result for p in group if p['region']=='l_hand'))

    def test_incoming_contact_activates_both_arm_chains(self):
        sources=[];poses=[]
        for i in (1,2):
            source,pose=measured_fixture(0);source['personId']=pose['personId']=i
            for p in source['measurements']:p['personId']=i
            source['measurements']=[p for p in source['measurements'] if not p['name'].endswith(('wrist','elbow','shoulder'))]
            pose['rig']['nodes'].append(dict(id='lMid1',parent='lHand',center=[43,109,0],end=[46,108,0],type='bone',orientation=[0,0,0],order='XYZ',limits={}))
            sources.append(source);poses.append(pose)
        found={}
        def stop(*args,**kwargs):
            frame=inspect.currentframe().f_back
            while frame and 'variables' not in frame.f_locals:frame=frame.f_back
            found['variables']=frame.f_locals['variables'];raise Captured()
        contact=dict(personId=1,otherId=2,part='l_palm',region='l_palm',confirmed=True)
        with patch('coupled.least_squares',side_effect=stop),self.assertRaises(Captured):fit_targets(sources,poses,contacts=[contact],preserve=True,warm_start=True)
        for owner in (0,1):self.assertTrue(any(i==owner and n=='lHand' for i,n,a in found['variables']))

    def test_canonical_solver_order_preserves_caller_actor_order(self):
        poses=[dict(personId=2),dict(personId=1)];sources=copy.deepcopy(poses)
        with patch('coupled._fit_targets',side_effect=lambda s,p,*args:dict(poses=p)) as inner:
            result=fit_targets(sources,poses)
        self.assertEqual([p['personId'] for p in inner.call_args.args[1]],[1,2])
        self.assertEqual([p['personId'] for p in result['poses']],[2,1])

    def test_target_code_changes_do_not_invalidate_raw_source(self):
        from wholebody import signature
        from refinement import target_signature
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'worker').mkdir();p=root/'worker/coupled.py';p.write_text('policy A')
            source_before=signature(root);target_before=target_signature(root);p.write_text('policy B changed')
            self.assertEqual(source_before,signature(root));self.assertNotEqual(target_before,target_signature(root))
            (root/'worker/inference.py').write_text('source inference changed')
            self.assertNotEqual(source_before,signature(root))

    def test_segmentation_changes_invalidate_cached_full_sources(self):
        from wholebody import signature
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);p=root/'models/segmentation/sam2.1_hiera_tiny.pt';p.parent.mkdir(parents=True);p.write_bytes(b'old')
            before=signature(root);p.write_bytes(b'new model');self.assertNotEqual(before,signature(root))
            before=signature(root);config=root/'vendor/sam2/sam2/configs/sam2.1/sam2.1_hiera_t.yaml';config.parent.mkdir(parents=True);config.write_text('new configuration')
            self.assertNotEqual(before,signature(root))

    def test_target_transaction_and_rotation_math_do_not_invalidate_sources(self):
        from wholebody import signature
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'worker').mkdir()
            ref=root/'worker/refinement.py';ref.write_text('def refine_sources():\n return 1\ndef target_signature():\n return 1\n')
            mapping=root/'worker/retarget.py';mapping.write_text('def source_map():\n return normalized(1)\ndef normalized(x):\n return x\ndef retarget():\n return 1\n')
            before=signature(root);ref.write_text(ref.read_text().replace('def target_signature():\n return 1','def target_signature():\n return 2'));mapping.write_text(mapping.read_text().replace('def retarget():\n return 1','def retarget():\n return 2'))
            self.assertEqual(before,signature(root))
            mapping.write_text(mapping.read_text().replace('return x','return x + 1'));self.assertNotEqual(before,signature(root))

    def test_real_installed_source_signature_handles_module_docstrings(self):
        from wholebody import signature
        value=signature(ROOT)
        self.assertRegex(value,r'^[0-9a-f]{24}$');self.assertEqual(value,signature(ROOT))

    def test_touching_distinct_hands_keep_their_own_detail(self):
        from wholebody import resolve_ownership
        groups=[[dict(personId=i,name='l_wrist',region='body',xy=[x,100],known=True,weight=.95),dict(personId=i,name='l_wrist',region='l_hand',xy=[100,100],known=True,weight=.95),dict(personId=i,name='l_indextip',region='l_hand',xy=[tip,100],known=True,weight=.95)] for i,x,tip in ((1,99,120),(2,101,80))]
        self.assertTrue(all(p['known'] for group in resolve_ownership(groups) for p in group))

    def test_camera_cache_requires_matching_provenance(self):
        from PIL import Image
        from inference import Inference
        from cache_provenance import stage_signature
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);Image.new('RGB',(64,64)).save(root/'source.png');atomic_json(root/'people.json',[dict(id=1,box=[0,0,64,64])]);atomic_json(root/'camera.json',np.eye(3).tolist())
            engine=Inference(root);payload=dict(imageId='audit',personId=1,extractionMethod='smart')
            with patch('inference.image_dir',return_value=root),patch('inference.cached_source',return_value=None),patch('wholebody.available',return_value=True),patch('torch.cuda.is_available',return_value=True),patch('torch.cuda.get_device_properties',return_value=SimpleNamespace(total_memory=16*1024**3)),patch.object(engine,'release'),patch.object(engine,'camera',side_effect=Captured) as camera:
                with self.assertRaises(Captured):engine.solve(payload,lambda *_:None)
                camera.assert_called_once()
                identity=dict(version=1,imageId='audit',imageSize=[64,64],signature=stage_signature(root,('worker/inference.py','worker/camera_depth.py','models/camera/model.pt','vendor/MoGe/moge/model/v2.py')))
                atomic_json(root/'camera-provenance.json',identity);camera.reset_mock()
                with patch('wholebody.Landmarker.measure',side_effect=Captured),self.assertRaises(Captured):engine.solve(payload,lambda *_:None)
                camera.assert_not_called()

    def test_solo_conversion_does_not_reuse_group_layout(self):
        from storage import read_json,image_dir
        from rigs import profile
        source,pose=measured_fixture(0);source['refinementMode']='accurate';source['extractionMethod']='smart'
        group=copy.deepcopy(pose);group['layout']=dict(personIds=[1,2]);fresh=copy.deepcopy(pose);fresh['layout']=None
        node=next(n for n in ast.parse((ROOT/'worker/main.py').read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef) and n.name=='dispatch')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);atomic_json(root/'people.json',[dict(id=1)]);ns=dict(ROOT=root,ENGINE=None,KIMODO=None,read_json=read_json,image_dir=lambda *_:root)
            exec(compile(ast.Module(body=[node],type_ignores=[]),'worker-dispatch','exec'),ns)
            with patch('refinement.accepted_result',return_value=dict(poses=[group,dict(group,personId=2)])),patch('instances.cached_source',return_value=source),patch('rigs.profile',return_value=pose['rig']),patch('cropped.prepare',return_value=source),patch('retarget.retarget',return_value=fresh) as retarget,patch('coupled.fit_targets',return_value=dict(poses=[fresh])),patch('posture.persist_baseline'):
                result=ns['dispatch']('retarget',dict(imageId='audit',personId=1,rigId=pose['rigId'],extractionMethod='smart'),lambda *_:None)
            self.assertIsNone(result['layout']);retarget.assert_called_once()

    def test_new_crop_policy_releases_previously_excluded_contact_arm(self):
        source,pose=measured_fixture(0)
        pose['cropPolicy']=dict(enabled=True,zeroSemantics=['l_upperarm','l_forearm','l_hand'])
        source['cropPolicy']=dict(version=1,signature='new',enabled=True,zeroSemantics=[],landmarks={})
        found={}
        def stop(*args,**kwargs):
            frame=inspect.currentframe().f_back
            while frame and 'variables' not in frame.f_locals:frame=frame.f_back
            found['variables']=frame.f_locals['variables'];raise Captured()
        with patch('coupled.least_squares',side_effect=stop),self.assertRaises(Captured):fit_targets([source],[pose],warm_start=True,preserve=True)
        self.assertTrue(any(n=='lHand' for i,n,a in found['variables']))
        self.assertEqual(pose['cropPolicy']['zeroSemantics'],['l_upperarm','l_forearm','l_hand'])

    def test_mask_cache_is_bound_to_model_and_preprocessing(self):
        from PIL import Image
        from segmentation import selected_mask
        from cache_provenance import stage_signature
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);weight=root/'models/segmentation/sam2.1_hiera_tiny.pt';weight.parent.mkdir(parents=True);weight.write_bytes(b'old')
            Image.new('L',(32,32),255).save(root/'mask-key.png')
            files=('worker/segmentation.py','worker/instances.py','models/segmentation/sam2.1_hiera_tiny.pt','vendor/sam2/sam2/configs/sam2.1/sam2.1_hiera_t.yaml')
            atomic_json(root/'mask-key.json',dict(version=2,context=['key'],personKey='key',imageSize=[32,32],signature=stage_signature(root,files)))
            builder=ModuleType('sam2.build_sam');builder.build_sam2=lambda *args,**kw:(_ for _ in ()).throw(Captured())
            predictor=ModuleType('sam2.sam2_image_predictor');predictor.SAM2ImagePredictor=object
            person=dict(keypoints=[[10,10,.9]],box=[0,0,32,32])
            with patch.dict('sys.modules',{'sam2.build_sam':builder,'sam2.sam2_image_predictor':predictor}),patch('segmentation.identity',return_value='key'),patch('segmentation.mask_prompts',return_value=([[10,10]],[])),patch('torch.cuda.empty_cache'):
                selected_mask(root,root,np.zeros((32,32,3),np.uint8),person,[person],lambda *_:None)
                weight.write_bytes(b'new updated model')
                with self.assertRaises(Captured):selected_mask(root,root,np.zeros((32,32,3),np.uint8),person,[person],lambda *_:None)

    def test_changed_pin_rejects_pending_apply_without_overwriting_history(self):
        from refinement import refine
        from posture import persist_baseline
        from wholebody import signature
        source,pose=measured_fixture(0);pose['pins']={'lHand':{'position':[43,109,-400]}}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source['refinementSignature']=signature(root);atomic_json(root/'people.json',[dict(id=1)]);persist_baseline(root,[source],[pose])
            atomic_json(root/'refinement.json',dict(accepted='kept'));before=(root/'refinement.json').read_bytes()
            payload=dict(version=2,policyVersion=1,imageId='same',currentPoses=[pose])
            def fitted(sources,poses,*args,**kwargs):return dict(poses=copy.deepcopy(poses),diagnostics=dict(accepted=True))
            with patch('refinement.image_dir',return_value=root),patch('editor.checked_poses'),patch('refinement.cached_source',return_value=source),patch('rigs.profile',return_value=pose['rig']),patch('coupled.fit_targets',side_effect=fitted):
                preview=refine(root,payload,lambda *_:None)
                changed=copy.deepcopy(pose);changed['pins']['lHand']['position'][0]+=7
                with self.assertRaisesRegex(ValueError,'changed'):refine(root,dict(payload,action='apply',previewId=preview['previewId'],currentPoses=[changed]),lambda *_:None)
                self.assertEqual(before,(root/'refinement.json').read_bytes())
