"""Evidence, ownership, fallback and cache contracts; no neural inference."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'worker'))
import reference_guidance as guidance
from camera_depth import save as save_geometry,load as load_geometry,load_normals
from guidance_runtime import letterbox
from instances import identity,cached_source,source_path
from storage import import_image,atomic_json,image_dir
from measurements import MHR


class GuidanceEvidence(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        (self.root/'data/history').mkdir(parents=True)
        self.image_id='a'*24
        self.folder=image_dir(self.root,self.image_id);self.folder.mkdir()
        Image.new('RGB',(80,60),(30,80,120)).save(self.folder/'source.png')
        atomic_json(self.folder/'image.json',dict(id=self.image_id,width=80,height=60,name='test.png',inputKind='photo'))

    def person(self):
        return dict(id=1,box=[0,0,80,60],keypoints=[],detector='controlled')

    def raw(self):
        p=self.person()
        return dict(version=3,personId=1,imageId=self.image_id,personKey=identity(p),extractionMethod='pure',pureVersion=1,marker='original')

    def test_limb_normal_requires_three_consistent_owned_samples(self):
        normal=np.zeros((60,80,3));normal[...,2]=-1
        valid=np.ones((60,80),bool);mask=valid.copy()
        np.testing.assert_allclose(guidance.limb_normal(normal,valid,mask,[15,30],[65,30],[80,60]),[0,0,-1])
        valid[:]=False;valid[30,40]=True
        self.assertIsNone(guidance.limb_normal(normal,valid,mask,[15,30],[65,30],[80,60]))
        valid[:]=True;normal[:,40:,2]=1
        self.assertIsNone(guidance.limb_normal(normal,valid,mask,[15,30],[65,30],[80,60]))
        mask[:]=False
        self.assertIsNone(guidance.limb_normal(normal,valid,mask,[15,30],[65,30],[80,60]))

    def test_colour_visualization_is_not_numeric_depth(self):
        path=self.root/'colour.png';Image.new('RGB',(20,20),(1,2,3)).save(path)
        for kind in ('metric-depth','relative-depth'):
            with self.assertRaisesRegex(ValueError,'grayscale depth'):
                import_image(self.root,dict(path=str(path),kind=kind))

    def test_missing_preferences_use_automatic_current_engine(self):
        self.assertEqual(guidance.options(self.root),dict(imageGuidance='auto',geometryEngine='moge2'))

    def test_off_is_original_even_with_a_saved_trial_engine(self):
        atomic_json(self.root/'data/settings.json',dict(imageGuidance='off',geometryEngine='moge3'))
        self.assertEqual(guidance.options(self.root)['geometryEngine'],'moge2')

    def test_retired_request_field_cannot_switch_models(self):
        self.assertEqual(guidance.options(self.root, dict(imageGuidance='off', geometryEngine='moge3')),
                         dict(imageGuidance='off', geometryEngine='moge2'))

    def test_prepared_surface_maps_do_not_claim_pure_pose_application(self):
        source=dict(self.raw(),mhr={})
        rows=[dict(name='l_wrist',xy=[10,10],known=True,depthSource='provided-surface-order')]
        with patch('reference_guidance.measurements',return_value=(rows,[],[])):
            result=guidance.enrich(self.root,source,dict(imageGuidance='auto',geometryEngine='moge2'),dict(state='ready'))
        self.assertTrue(result['referenceEvidence']['prepared'])
        self.assertFalse(result['referenceEvidence']['applied'])
        self.assertEqual(result['mhr'],source['mhr'])

    def test_invalid_explicit_preferences_are_rejected(self):
        for field,value in [('imageGuidance','fast'),('imageGuidance',True)]:
            with self.assertRaises(ValueError):guidance.options(self.root,{field:value})

    def test_malformed_saved_preferences_recover_without_coercion(self):
        atomic_json(self.root/'data/settings.json',dict(imageGuidance=3,geometryEngine=False))
        self.assertEqual(guidance.options(self.root),dict(imageGuidance='auto',geometryEngine='moge2'))

    def test_missing_optional_model_never_spawns_or_changes_an_input(self):
        original=(self.folder/'source.png').read_bytes()
        with patch('reference_guidance.subprocess.Popen',side_effect=AssertionError('must not run')):
            result=guidance.prepare(self.root,[self.image_id],'auto')
        self.assertEqual(result[self.image_id]['state'],'missing')
        self.assertEqual((self.folder/'source.png').read_bytes(),original)

    def test_existing_depth_never_runs_an_rgb_inverse_renderer(self):
        atomic_json(self.folder/'image.json',dict(id=self.image_id,width=80,height=60,name='depth.png',inputKind='relative-depth'))
        with patch('reference_guidance.subprocess.Popen',side_effect=AssertionError('depth of depth')):
            result=guidance.prepare(self.root,[self.image_id],'detailed')
        self.assertEqual(result[self.image_id]['state'],'provided-depth')

    def test_automatic_surface_path_preserves_observations_exactly(self):
        points=[dict(name='l_wrist',xy=[14.,20.],known=True,region='body',weight=.8)]
        result,normals,_=guidance.measurements(self.root,self.image_id,points,'person','auto')
        self.assertEqual(result,points);self.assertIsNot(result,points);self.assertEqual(normals,[])

    def test_unverified_mask_excludes_surface_fitting(self):
        points=[dict(name='l_wrist',xy=[14.,20.],known=True,region='body',weight=.8)]
        result,normals,notes=guidance.measurements(self.root,self.image_id,points,'person','detailed')
        self.assertEqual(result,points);self.assertEqual(normals,[])
        self.assertTrue(any('mask' in note for note in notes))

    def test_mask_interiors_exclude_boundaries_and_other_people(self):
        mask=np.zeros((60,80),bool);mask[10:50,10:40]=True
        self.assertTrue(guidance.interior_mask(mask,[22,25],[80,60]))
        self.assertFalse(guidance.interior_mask(mask,[10,25],[80,60]))
        self.assertFalse(guidance.interior_mask(mask,[60,25],[80,60]))

    def test_letterbox_preserves_all_pixels_and_aspect_mapping(self):
        image=Image.new('RGB',(80,20),(40,120,200))
        square,box=letterbox(image)
        self.assertEqual(square.shape,(448,448,3));self.assertEqual(box,(0,168,448,112))
        self.assertTrue(np.all(square[168:280]==[40,120,200]))
        expected=(np.array([39.5,9.5])+.5)*[448/80,112/20]-.5
        values=np.arange(448*112,dtype=np.float32).reshape(112,448)
        self.assertEqual(guidance.sample(values,[39.5,9.5],[80,20]),guidance.sample(values,expected,[448,112]))

    def test_detailed_map_quality_is_independent_of_the_extraction_setting(self):
        self.assertEqual(guidance.options(self.root,{'imageGuidance':'detailed'})['imageGuidance'],'auto')
        with patch('reference_guidance.prepare',return_value={}) as prepare:
            guidance.inspection(self.root,dict(imageId=self.image_id,provider='image',
                map='original',mapQuality='detailed',imageGuidance='off'),lambda *_:None)
        self.assertEqual(prepare.call_args.args[2],'detailed')

    def test_automatic_trial_reuses_baseline_and_maps_without_starting_helpers(self):
        from inference import Inference
        source=dict(self.raw(),mhr={})
        engine=Inference(self.root)
        with patch.object(engine,'_solve',return_value=source) as baseline, \
             patch('reference_guidance.AUTOMATIC_CUES_QUALIFIED',True), \
             patch('reference_guidance.prepare',side_effect=AssertionError('Unexpected ShadeNet pass')), \
             patch('reference_guidance.prepare_masks',side_effect=AssertionError('Unexpected segmentation pass')), \
             patch('reference_guidance.measurements',return_value=([],[],[])):
            actual=engine.solve(dict(imageId=self.image_id,personId=1,imageGuidance='auto'),lambda *_:None)
        baseline.assert_called_once()
        self.assertEqual(actual['referenceEvidence']['outcome'],'insufficient')

    def test_original_identity_bypasses_current_guided_selection(self):
        person=self.person();source=self.raw();atomic_json(source_path(self.folder,person,'pure'),source)
        key='b'*64
        guided=dict(source,marker='guided',sourceGuidance=dict(version=1,id=key))
        atomic_json(self.folder/('guidance-source-'+key+'.json'),guided)
        atomic_json(self.folder/('guidance-selected-'+identity(person)+'-pure.json'),dict(version=1,id=key,settings=guidance.options(self.root)))
        self.assertEqual(cached_source(self.folder,person,'pure')['marker'],'guided')
        self.assertEqual(cached_source(self.folder,person,'pure',dict(version=1,id='original'))['marker'],'original')
        self.assertEqual(cached_source(self.folder,person,'pure',dict(version=1,id=key))['marker'],'guided')

    def test_missing_historical_guidance_cannot_silently_use_a_new_source(self):
        person=self.person();atomic_json(source_path(self.folder,person,'pure'),self.raw())
        self.assertIsNone(cached_source(self.folder,person,'pure',dict(version=1,id='c'*64)))

    def test_cache_identity_excludes_rigs_cameras_and_actor_assignment(self):
        p=self.root/'models/guidance/shadenet5-mix-refined.onnx';p.parent.mkdir(parents=True);p.write_bytes(b'identity-only')
        item=guidance.record(self.root,self.image_id);before=guidance.cache_key(self.root,item,'auto')
        atomic_json(self.root/'data/settings.json',dict(rigId='g9',camera=[1,2,3],actors=[2,1]))
        self.assertEqual(guidance.cache_key(self.root,item,'auto'),before)
        self.assertNotEqual(guidance.cache_key(self.root,dict(item,originalSha256='changed'),'auto'),before)

    def test_corrupted_cache_metadata_is_not_reused(self):
        key='d'*64;folder=self.root/'data/guidance/maps';folder.mkdir(parents=True)
        (folder/(key+'.json')).write_text('{invalid',encoding='utf-8')
        self.assertIsNone(guidance.load(self.root,key))

    def test_cache_cannot_escape_its_private_directory(self):
        key='e'*64;folder=self.root/'data/guidance/maps';folder.mkdir(parents=True)
        atomic_json(folder/(key+'.json'),dict(version=1,path='../escape.npz'))
        self.assertIsNone(guidance.load(self.root,key))

    def test_saved_trial_spacing_cache_is_read_only(self):
        image = np.zeros((60,80,3),np.uint8)
        valid = np.ones((60,80),bool)
        normals = np.broadcast_to([0.,0.,-1.],(60,80,3)).astype(np.float32)
        metadata = save_geometry(self.root,self.folder,image,np.eye(3).tolist(),np.ones((60,80),np.float32),valid,normals)
        current = self.folder/'camera-depth.npz'
        legacy = self.folder/'camera-depth-moge3.npz'
        with legacy.open('wb') as stream:
            np.savez_compressed(stream, depth=np.full((60,80),2.,np.float32), valid=valid)
        metadata.update(provider='MoGe-3', path=legacy.name, sha256=hashlib.sha256(legacy.read_bytes()).hexdigest())
        atomic_json(legacy.with_suffix('.json'),metadata)
        self.assertTrue(np.all(load_geometry(self.root,self.folder)[1]==1))
        self.assertEqual(load_normals(self.root,self.folder)[0]['basis'],'x-right,y-down,z-forward')
        with patch('camera_depth.signature',side_effect=AssertionError('Legacy reads must not require a model')):
            self.assertTrue(np.all(load_geometry(self.root,self.folder,image,provider='MoGe-3')[1]==2))
        changed = image.copy()
        changed[0,0] = 255
        self.assertIsNone(load_geometry(self.root,self.folder,changed,provider='MoGe-3'))
        metadata['provider'] = 'MoGe-2'
        atomic_json(legacy.with_suffix('.json'),metadata)
        self.assertIsNone(load_geometry(self.root,self.folder,provider='MoGe-3'))
        self.assertTrue(current.is_file())

    def test_depth_original_keeps_exact_16_bit_file_and_zero_values(self):
        values=np.array([[0,65535],[1024,20000]],dtype=np.uint16)
        original=self.root/'depth.png';Image.fromarray(values).save(original)
        before=original.read_bytes()
        imported=import_image(self.root,dict(path=str(original),kind='relative-depth'))
        self.assertEqual(imported['inputKind'],'relative-depth')
        key=imported['referenceOriginal'];meta=json.loads((self.root/'data/reference-assets'/key/'asset.json').read_text())
        stored=self.root/'data/reference-assets'/key/meta['file']
        self.assertEqual(stored.read_bytes(),before)
        with Image.open(stored) as image:np.testing.assert_array_equal(np.asarray(image),values)

    def test_photo_import_keeps_legacy_pixel_identity(self):
        original=self.root/'photo.png';image=Image.new('RGB',(10,12),(20,30,40));image.save(original)
        expected=hashlib.sha256(image.tobytes()+str(image.size).encode()).hexdigest()[:24]
        self.assertEqual(import_image(self.root,dict(path=str(original)))['id'],expected)

    def test_surface_normal_uses_rotation_only_and_correct_camera_basis(self):
        points=dict(a=np.array([0.,0.,0.]),b=np.array([1.,0.,0.]))
        goal=dict(a='a',b='b',normalCamera=[0.,0.,-1.],weight=1.)
        self.assertAlmostEqual(guidance.normal_error(points,goal),0)
        rotation=np.array([[0.,0.,1.],[0.,1.,0.],[-1.,0.,0.]])
        self.assertAlmostEqual(guidance.normal_error(points,goal,rotation),1)

    def test_ordinal_pairs_require_owned_known_body_samples(self):
        points=[dict(name='l_wrist',xy=[0,10],known=True,region='body',depthSurfaceValue=1.,depthRange=2.,depthConvention='white-far',depthSource='estimated-surface-order'),
                dict(name='r_wrist',xy=[40,10],known=True,region='body',depthSurfaceValue=2.,depthRange=2.,depthConvention='white-far',depthSource='estimated-surface-order')]
        self.assertEqual(guidance.ordinal_pairs(points),[('l_wrist','r_wrist')])
        points[1]['known']=False;self.assertEqual(guidance.ordinal_pairs(points),[])

    def test_guided_candidate_cannot_lose_an_accepted_hand(self):
        names=['l_shoulder','r_shoulder','l_elbow','r_elbow']
        points=[dict(name=n,known=True,xy=[20.,20.],region='body') for n in names]
        old=dict(projectedKeypoints=np.full((70,2),30.).tolist(),keypoints3d=np.zeros((70,3)).tolist(),personBox=[0,0,100,100],handAcceptance=dict(l=dict(accepted=True)))
        new=dict(copy.deepcopy(old),projectedKeypoints=np.full((70,2),20.).tolist())
        self.assertTrue(guidance.candidate_is_better(old,new,points)[0])
        new['handAcceptance']['l']['accepted']=False
        self.assertFalse(guidance.candidate_is_better(old,new,points)[0])

    def import_depth(self,values,kind='relative-depth'):
        path=self.root/'provided.png';Image.fromarray(values).save(path)
        return import_image(self.root,dict(path=str(path),kind=kind))['id']

    def test_relative_zero_is_valid_and_white_near_order_is_explicit(self):
        values=np.zeros((60,80),np.uint16);values[:,40:]=65535
        image_id=self.import_depth(values)
        points=[dict(name=name,xy=[x,30],known=True,region='body',weight=1.) for name,x in [('l_wrist',12),('r_wrist',68)]]
        with patch('reference_guidance.owned_mask',return_value=np.ones((60,80),dtype=bool)):
            rows,normals,_=guidance.measurements(self.root,image_id,points,'manual','detailed')
        self.assertEqual(rows[0]['depthSurfaceValue'],0.)
        self.assertEqual(guidance.ordinal_pairs(rows),[('r_wrist','l_wrist')])
        self.assertEqual(normals,[])
        self.assertNotIn('depthSurfaceValue',points[0])

    def test_relative_order_uses_subject_range_when_background_dominates_frame(self):
        values = np.zeros((800, 1000), np.uint16)
        values[100:450, 350:395] = 2000
        values[260:450, 350:395] = 42000
        self.assertEqual(float(np.percentile(values, 95)), 0.)
        image_id = self.import_depth(values)
        polygon = [[350, 100], [394, 100], [394, 449], [350, 449]]
        points = [dict(name='l_wrist', xy=[372, 165], known=True, region='body', weight=1.),
                  dict(name='r_wrist', xy=[372, 350], known=True, region='body', weight=1.)]
        mask = np.zeros(values.shape, dtype=bool)
        mask[polygon[0][1]:polygon[2][1]+1, polygon[0][0]:polygon[2][0]+1] = True
        with patch('reference_guidance.owned_mask', return_value=mask):
            rows, _, _ = guidance.measurements(self.root, image_id, points, 'manual', 'detailed')
        self.assertEqual([row['depthSurfaceValue'] for row in rows], [2000., 42000.])
        self.assertEqual(guidance.ordinal_pairs(rows), [('r_wrist', 'l_wrist')])

    def test_metric_plane_normals_require_calibration_and_have_camera_basis(self):
        values=np.full((60,80),1000,np.uint16);values[:,64:]=1100
        image_id=self.import_depth(values,'metric-depth')
        camera=dict(projection='perspective',intrinsics=[[100,0,40],[0,100,30],[0,0,1]],metricScale=True,provenance='calibrated')
        result=guidance.provided_depth(self.root,image_id,camera,'camera-z',.1)
        self.assertTrue(result['normalValid'][30,40]);np.testing.assert_allclose(result['normal'][30,40],[0,0,-1],atol=1e-6)
        self.assertIsNone(guidance.provided_depth(self.root,image_id,dict(camera,provenance='estimated'),'camera-z',.1)['normal'])
        self.assertIsNone(guidance.provided_depth(self.root,image_id,camera,'white-near',.1)['normal'])
        self.assertIsNone(guidance.provided_depth(self.root,image_id,camera,'camera-z',None)['normal'])

    def test_metric_depth_holes_and_discontinuities_never_supply_normals(self):
        values=np.full((60,80),1000,np.uint16);values[:,40:]=2000;values[20,20]=0
        image_id=self.import_depth(values,'metric-depth')
        camera=dict(projection='perspective',intrinsics=[[100,0,40],[0,100,30],[0,0,1]],metricScale=True,provenance='calibrated')
        result=guidance.provided_depth(self.root,image_id,camera,'camera-z',.1)
        self.assertFalse(result['normalValid'][20,20]);self.assertFalse(result['normalValid'][20,19])
        self.assertFalse(result['normalValid'][30,39]);self.assertFalse(result['normalValid'][30,40])
        self.assertTrue(result['normalValid'][30,25])

    def test_tiny_depth_remains_readable_without_invented_normals(self):
        image_id=self.import_depth(np.array([[0,255]],np.uint16),'metric-depth')
        camera=dict(projection='perspective',intrinsics=np.eye(3).tolist(),metricScale=True,provenance='calibrated')
        self.assertIsNone(guidance.provided_depth(self.root,image_id,camera,'camera-z',1.)['normal'])

    def test_stale_unverified_mask_cannot_own_surface_measurements(self):
        person=self.person();atomic_json(self.folder/'people.json',[person]);key=identity(person)
        Image.new('L',(80,60),255).save(self.folder/('mask-'+key+'.png'))
        self.assertIsNone(guidance.owned_mask(self.root,self.image_id,key))
        atomic_json(self.folder/('mask-'+key+'.json'),dict(version=2,personKey=key,context=['wrong-owner']))
        self.assertIsNone(guidance.owned_mask(self.root,self.image_id,key))

    def test_unqualified_automatic_is_a_true_original_fallback(self):
        from inference import Inference
        source=dict(self.raw(),measurements=[dict(name='l_wrist',xy=[2,3],known=True)],mhr={'unchanged':True})
        before=copy.deepcopy(source);engine=Inference(self.root)
        with patch.object(engine,'_solve',return_value=source),patch('reference_guidance.prepare',side_effect=AssertionError('No redundant helper')),patch('measurements.canonical',side_effect=AssertionError('Do not reinterpret raw observations')):
            actual=engine.solve(dict(imageId=self.image_id,personId=1,imageGuidance='auto'),lambda *_:None)
        self.assertEqual(source,before)
        self.assertEqual(actual['measurements'],source['measurements'])
        self.assertEqual(actual['mhr'],source['mhr'])
        self.assertFalse(actual['referenceEvidence']['prepared']);self.assertFalse(actual['referenceEvidence']['applied'])
        self.assertEqual(actual['sourceGuidance']['id'],'original')

    def test_optional_candidate_failure_returns_raw_source_and_explains_fallback(self):
        from inference import Inference
        source=dict(self.raw(),personBox=[0,0,80,60],imageSize=[80,60])
        engine=Inference(self.root)
        with patch.object(engine,'_solve',return_value=source),patch('reference_guidance.prepare',return_value={self.image_id:dict(state='ready')}),patch('reference_guidance.prepare_masks',return_value={}),patch('reference_guidance.DETAILED_CUES_QUALIFIED',True),patch('reference_guidance.supplemental_measurements',side_effect=ValueError('bad optional map')):
            actual=engine.solve(dict(imageId=self.image_id,personId=1,imageGuidance='detailed'),lambda *_:None)
        self.assertEqual(actual['sourceGuidance'],dict(version=1,id='original'))
        self.assertFalse(actual['referenceEvidence']['applied']);self.assertTrue(any('Optional image guidance failed' in note for note in actual['referenceEvidence']['notes']))
        self.assertNotIn('referenceEvidence',source)

    def test_depth_inspection_offers_no_albedo_and_never_spawns_a_model(self):
        values=np.zeros((60,80),np.uint16);values[:,64:]=1
        image_id=self.import_depth(values)
        with patch('reference_guidance.prepare',side_effect=AssertionError('provided depth')):
            inspected=guidance.inspection(self.root,dict(imageId=image_id,map='depth'),lambda *_:None)
        self.assertEqual(inspected['available'],['original','depth']);self.assertTrue(inspected['url'].startswith('data:image/png'))

    def test_alpha_holes_do_not_become_relative_depth_observations(self):
        pixels=np.full((60,80,4),255,np.uint8);pixels[:,:40,:3]=0;pixels[20,20,3]=0
        image_id=self.import_depth(pixels)
        depth=guidance.provided_depth(self.root,image_id)
        self.assertFalse(depth['valid'][20,20]);self.assertTrue(depth['valid'][20,19]);self.assertEqual(depth['values'][20,19],0)

    def test_depth_input_does_not_initialize_an_optional_geometry_engine(self):
        from inference import Inference
        image_id=self.import_depth(np.tile(np.arange(80,dtype=np.uint16),(60,1)))
        engine=Inference(self.root);raw=dict(self.raw(),imageId=image_id,mhr={})
        with patch.object(engine,'_solve',return_value=raw) as solve,patch.object(engine,'camera',side_effect=AssertionError('Depth does not need MoGe')):
            actual=engine.solve(dict(imageId=image_id,personId=1,imageGuidance='auto',geometryEngine='moge2'),lambda *_:None)
        self.assertNotIn('_geometryEngine', solve.call_args.args[0])
        self.assertEqual(actual['referenceEvidence']['geometryEngine'],'moge2');self.assertFalse(actual['referenceEvidence']['applied'])

    def test_detailed_rechecks_legacy_depth_samples_against_ownership(self):
        values=np.zeros((60,80),np.uint16);values[:,40:]=65535;image_id=self.import_depth(values)
        points=[dict(name='l_wrist',xy=[12,30],known=True,region='body',depthSurfaceValue=0,depthRange=65535,depthConvention='white-near')]
        rows,_,_=guidance.measurements(self.root,image_id,points,'no-mask','detailed')
        self.assertNotIn('depthSurfaceValue',rows[0]);self.assertIn('depthSurfaceValue',points[0])
        unchanged,_,_=guidance.measurements(self.root,image_id,points,'no-mask','auto')
        self.assertNotIn('depthSurfaceValue',unchanged[0]);self.assertEqual(unchanged[0]['xy'],points[0]['xy']);self.assertIn('depthSurfaceValue',points[0])

    def test_trial_camera_fallback_has_its_own_exact_saved_source(self):
        person=self.person();atomic_json(self.folder/'people.json',[person])
        raw=dict(self.raw(),mhr={},marker='moge3-camera')
        atomic_json(source_path(self.folder,person,'pure'),dict(raw,marker='moge2-camera'))
        result=guidance.enrich(self.root,raw,dict(imageGuidance='detailed',geometryEngine='moge3'),dict(state='unavailable',notes=['Original body estimate retained']),allow_cues=False)
        self.assertNotEqual(result['sourceGuidance']['id'],'original')
        actual=cached_source(self.folder,person,'pure',context=result['sourceGuidance'])
        self.assertEqual(actual['marker'],'moge3-camera');self.assertFalse(actual['referenceEvidence']['applied'])
        self.assertEqual(cached_source(self.folder,person,'pure',context=dict(version=1,id='original'))['marker'],'moge2-camera')

    def test_spacing_uses_the_accepted_engine_and_rejects_mixed_evidence(self):
        from spacing import geometry_provider
        self.assertEqual(geometry_provider([{},{}]),'MoGe-2')
        trial=dict(referenceEvidence=dict(geometryEngine='moge3'))
        self.assertEqual(geometry_provider([trial,trial]),'MoGe-3')
        with self.assertRaisesRegex(ValueError,'different geometry engines'):geometry_provider([{},trial])


if __name__=='__main__':unittest.main()
