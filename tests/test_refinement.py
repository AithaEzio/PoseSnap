import copy, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from test_interaction import fixture
from wholebody import affine_crop,decode_simcc,FLIP,resolve_ownership,Landmarker,signature
from evidence import measured_prompts,prompt_errors
from measurements import MHR,canonical,overrides,target_points,reference_camera,project_target,quality
from coupled import dependency_chain,fitting_rig,contact_graph,fit_targets
from daz import duf
from storage import atomic_json
from benchmark import evaluate
from refinement import refine,accepted_result,source_signature
from benchmark_data import attribution_license,landmarks,candidates,image_url

class MeasurementTests(unittest.TestCase):
    def test_warm_target_fit_requires_the_original_reference_camera(self):
        source,pose=fixture(1,0);pose['referenceCamera']=reference_camera(source,[0,0,0]);pose['referenceCamera']['imageSize']=[1,2]
        with self.assertRaisesRegex(ValueError,'another reference camera'):fit_targets([source],[pose],warm_start=True)
    def test_flip_fuses_distributions_with_correct_sides_and_half_pixel_bins(self):
        x=np.zeros((1,133,16));y=np.zeros((1,133,16));x[:,:,3]=.8;y[:,:,6]=.9
        x[0,91,:]=0;x[0,91,5]=.9
        reflected_x=x[:,FLIP,::-1].copy();reflected_y=y[:,FLIP].copy()
        engine=Landmarker(Path('.'));inverse=np.array([[1,0,0],[0,1,0]],float)
        with patch.object(engine,'vectors',side_effect=[(x,y,inverse),(reflected_x,reflected_y,inverse)]):
            points,scores,error=engine.paired(None,None,fuse=True)
        np.testing.assert_allclose(points[91],[2.5,3]);np.testing.assert_allclose(error,0);self.assertGreater(scores[91],.7)
    def test_disagreeing_flip_remains_uncertain_after_fusion(self):
        x=np.zeros((1,21,40));y=x.copy();x[:,:,2]=1;y[:,:,6]=1
        flip_x=x.copy();flip_x[:,:,2]=0;flip_x[:,:,4]=1
        inverse=np.array([[1,0,0],[0,1,0]],float);engine=Landmarker(Path('.'))
        with patch.object(engine,'vectors',side_effect=[(x,y,inverse),(flip_x[:,:,::-1],y,inverse)]):
            points,scores,error=engine.paired(None,None,'hand')
        np.testing.assert_allclose(error,1.)
    def test_independent_prompts_exclude_unknown_and_low_confidence_detail(self):
        items=[dict(name='l_thumbtip',xy=[20,30],weight=.9,known=True,region='l_hand'),dict(name='r_thumbtip',xy=[50,30],weight=.99,known=False,region='r_hand'),dict(name='l_heel',xy=[20,80],weight=.6,known=True,region='l_foot')]
        result=measured_prompts(items,[]);self.assertEqual(len(result),1);self.assertEqual(result[0]['mhr'],42)
        projected=np.zeros((70,2));projected[42]=[20,30];self.assertEqual(prompt_errors(projected,result,100)[0],0)
    def test_original_resolution_crop_roundtrip_with_padding(self):
        image=np.zeros((600,900,3),np.uint8)
        _,inverse=affine_crop(image,[-40,80,340,550],(288,384))
        center=np.array([144,192])@inverse[:,:2].T+inverse[:,2]
        np.testing.assert_allclose(center,[150,315],atol=.001)
        x=np.zeros((1,1,576));y=np.zeros((1,1,768));x[0,0,288]=.9;y[0,0,384]=.8
        points,scores=decode_simcc(x,y,inverse)
        np.testing.assert_allclose(points[0],center);self.assertAlmostEqual(scores[0],.8)
    def test_flip_and_finger_orders_are_not_mirrored(self):
        self.assertEqual(FLIP[91],112);self.assertEqual(FLIP[17],20)
        self.assertEqual([FLIP[FLIP[i]] for i in range(133)],list(range(133)))
        self.assertEqual([MHR[n] for n in ('l_thumb1','l_thumb2','l_thumb3','l_thumbtip')],[45,44,43,42])
        self.assertEqual([MHR[n] for n in ('r_index1','r_index2','r_index3','r_indextip')],[28,27,26,25])
    def test_unknown_and_missing_points_do_not_count_as_successes(self):
        s,p=fixture(1,0);points,_=target_points(p);cam=reference_camera(s,[0,0,0])
        s['personBox']=[0,0,500,800]
        s['measurements']=[dict(personId=1,name='l_wrist',region='body',known=True,weight=1.,xy=project_target(points['l_wrist'],cam).tolist()),dict(personId=1,name='l_thumbtip',region='l_hand',known=False,weight=1.,xy=[1,1])]
        q=quality(s,p,cam)
        self.assertEqual(q['coverage'],dict(observed=1,expected=60));self.assertEqual(q['visible']['matched'],1)
        self.assertIsNone(q['regions']['l_hand']['matched']);self.assertEqual(q['regions']['l_hand']['count'],0)
    def test_guided_unknown_and_invalid_corrections_are_transactional(self):
        source,_=fixture(1,0);before=canonical(source)
        result=overrides([before],[dict(personId=1,name='l_wrist',xy=[10,20],unknown=True)],source['imageSize'])
        self.assertFalse(next(p for p in result[0] if p['name']=='l_wrist')['known']);self.assertEqual(canonical(source),before)
        for correction in (dict(personId=2,name='l_wrist',xy=[10,20]),dict(personId=1,name='l_wrist',xy=[float('nan'),20]),dict(personId=1,name='unknown',xy=[10,20]),dict(personId=1,name='r_heel',xy=[1300,20])):
            with self.assertRaises(ValueError):overrides([before],[correction],source['imageSize'])
    def test_reference_origin_and_principal_point_roundtrip(self):
        source,_=fixture(1,0);source['camera'][0][2]=530;source['camera'][1][2]=410
        np.testing.assert_allclose(project_target([5,20,-400],reference_camera(source,[0,0,0])),[542.5,360])
        np.testing.assert_allclose(project_target([-15,15,-100],reference_camera(source,[20,5,-300])),[542.5,360])
    def test_toe_measurements_follow_toe_channels_without_moving_heel(self):
        _,pose=fixture(1,0)
        toe=dict(id='lToe',parent='lFoot',type='bone',center=[10,0,8],end=[10,0,18],orientation=[0,0,0],order='XYZ',limits={})
        pose['rig']['nodes'].append(toe);before=copy.deepcopy(pose['rig']);neutral,_=target_points(pose)
        pose['rotations']['lToe']=[40,0,0];bent,deps=target_points(pose)
        self.assertEqual(deps['l_bigtoe'],'lToe');self.assertGreater(np.linalg.norm(bent['l_bigtoe']-neutral['l_bigtoe']),1.)
        np.testing.assert_allclose(bent['l_heel'],neutral['l_heel']);self.assertEqual(pose['rig'],before)

class CoupledTests(unittest.TestCase):
    def test_contact_evidence_is_independent_of_initial_depth(self):
        a,pa=fixture(1,0);b,pb=fixture(2,0)
        pa['translation'][2]=-800;pb['translation'][2]=500
        b['measurements']=canonical(b);a['measurements']=canonical(a)
        shoulder=next(p for p in b['measurements'] if p['name']=='l_shoulder')
        next(p for p in a['measurements'] if p['name']=='l_wrist')['xy']=shoulder['xy']
        graph=contact_graph([a,b],[pa,pb])
        self.assertTrue(any(c['personId']==1 and c['part']=='l_palm' for c in graph))
        unchanged=contact_graph([a,b],[pa,pb],graph)
        self.assertFalse(any(c['confirmed'] for c in unchanged))
    def test_erc_dependency_outside_parent_chain_is_retained(self):
        _,p=fixture(1,0);rig=p['rig'];extra=copy.deepcopy(rig['nodes'][1]);extra.update(id='driver',parent='figure')
        rig['nodes'].append(extra);rig['formulas']=[dict(output='test#lHand?rotation/x/value',operations=[dict(op='push',url='test#driver?rotation/x/value')])]
        self.assertIn('driver',dependency_chain(rig,'lHand'))
        self.assertIn('driver',[n['id'] for n in fitting_rig(rig)['nodes']])
    def test_fit_preserves_rig_and_exports_authoritative_channels(self):
        s,p=fixture(1,0);s['restPositions']=(np.array([n['center'] for n in p['rig']['nodes']])/100).tolist()
        original=copy.deepcopy(p['rig']);before=copy.deepcopy(p)
        fitted=fit_targets([s],[p],support=[dict(personId=1,side='l',state='air'),dict(personId=1,side='r',state='heel')])
        result=fitted['poses'][0]
        self.assertEqual(result['rig'],original);self.assertEqual(p,before)
        self.assertEqual(result['quality']['stage'],'target');self.assertEqual(result['referenceCamera']['intrinsics'],s['camera'])
        channels=duf(result,'floor')['scene']['animations']
        for name,angles in result['rotations'].items():
            for axis,angle in zip('xyz',angles):
                rows=[row for row in channels if row['url']==f'name://@selection/{name}:?rotation/{axis}/value']
                self.assertEqual(len(rows),1);self.assertAlmostEqual(rows[0]['keys'][0][1],angle,places=6)
        self.assertEqual(next(p for p in fitted['diagnostics']['support'] if p['side']=='l')['state'],'air')

class BenchmarkGateTests(unittest.TestCase):
    def test_missing_evidence_and_small_benchmark_cannot_qualify(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);atomic_json(base/'empty.json',dict(people=[]))
            manifest=dict(cases=[dict(id='one',imageDigest='unique',category='interaction-photo',people=[dict(personId=1,heightPx=100,landmarks=[dict(name='l_thumbtip',region='l_hand',xy=[10,10])])],runs=dict(baseline='empty.json',final='empty.json'))])
            report=evaluate(manifest,base)
            self.assertFalse(report['passed']);self.assertEqual(report['summary']['final']['hand'],1.)
            self.assertEqual(report['summary']['final']['coverage'],0.)
    def test_unchanged_perfect_predictions_are_not_25_percent_improvement(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);atomic_json(base/'perfect.json',dict(people=[dict(personId=1,points=dict(l_thumbtip=[10,10]))]))
            manifest=dict(cases=[dict(id='one',imageDigest='unique',category='single-person',people=[dict(personId=1,heightPx=100,landmarks=[dict(name='l_thumbtip',region='l_hand',xy=[10,10])])],runs=dict(baseline='perfect.json',final='perfect.json'))])
            self.assertEqual(evaluate(manifest,base)['paired']['hand']['ratio'],1.)
    def test_nonfinite_depth_contact_and_daz_checks_never_qualify(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)
            atomic_json(base/'invalid.json',dict(people=[dict(personId=1,rootCm=[0,0,0],points={}),dict(personId=2,rootCm=[0,0,0],points={})],contactGapsCm=dict(hug=0),checks=dict(personSwaps=0,reversedHandsFeet=0,footSupportCorrect=True,maximumDazChannelErrorDegrees=-1)))
            manifest=dict(cases=[dict(id='two',imageDigest='unique',category='genesis-render',relativeDepthCm=0,contacts=[dict(id='hug')],people=[dict(personId=i,heightPx=100,landmarks=[]) for i in (1,2)],runs=dict(final='invalid.json'))])
            report=evaluate(manifest,base);self.assertIn('two: DAZ channel agreement not verified',report['failures'])
            # JSON permits these values when written externally; evaluator rejects them.
            (base/'invalid.json').write_text('{"people":[{"personId":1,"rootCm":[0,0,NaN]},{"personId":2,"rootCm":[0,0,0]}],"contactGapsCm":{"hug":NaN},"checks":{"maximumDazChannelErrorDegrees":NaN}}',encoding='utf-8')
            report=evaluate(manifest,base)
            self.assertTrue(any('root-depth' in p for p in report['failures']));self.assertTrue(any('contact gap' in p for p in report['failures']));self.assertTrue(any('DAZ channel' in p for p in report['failures']))
    def test_incomplete_review_and_known_contact_truth_remain_pending(self):
        manifest=dict(cases=[dict(id='two',imageDigest='unique',category='genesis-render',people=[dict(personId=i,heightPx=100,landmarks=[]) for i in (1,2)],runs={},review=dict(category=False,ownership=False))])
        report=evaluate(manifest,Path('.'))
        self.assertTrue(any('review' in p for p in report['failures']));self.assertTrue(any('known interaction' in p for p in report['failures']))
    def test_invalid_truth_and_prediction_path_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);atomic_json(base/'empty.json',dict(people=[]))
            case=dict(id='one',imageDigest='unique',category='single-person',people=[dict(personId=1,heightPx=100,landmarks=[dict(name='l_wrist',region='body',xy=[float('nan'),2])])],runs=dict(final='empty.json'))
            with self.assertRaisesRegex(ValueError,'finite coordinates'):evaluate(dict(cases=[case]),base)
            case['runs']['final']='../outside.json'
            with self.assertRaisesRegex(ValueError,'benchmark folder'):evaluate(dict(cases=[case]),base)

class PublishedAnnotationTests(unittest.TestCase):
    def test_cc_by_filter_does_not_admit_restricted_or_unknown_images(self):
        self.assertTrue(attribution_license(dict(url='http://creativecommons.org/licenses/by/2.0/')))
        for url in ('https://creativecommons.org/licenses/by-nc/4.0/', 'https://creativecommons.org/licenses/by-nd/2.0/', 'https://creativecommons.org/licenses/by-sa/4.0/', 'https://example.com/licenses/by/4.0/'):
            self.assertFalse(attribution_license(dict(url=url)))
        self.assertFalse(attribution_license({}))
    def test_occluded_foot_and_missing_fingers_are_not_visible_truth(self):
        items=landmarks(dict(keypoints=[10,20,2,12,20,1,0,0,0,30,40,2,0,0,0,0,0,0]),'cmu-foot')
        self.assertEqual([p['name'] for p in items],['l_bigtoe','l_smalltoe','r_bigtoe'])
        self.assertEqual([p['visible'] for p in items],[True,False,True])
        self.assertTrue(all(p['region'].endswith('foot') for p in items))
    def test_candidate_ids_are_stable_and_no_interaction_truth_is_invented(self):
        image=dict(id=1,file_name='000000000001.jpg',license=4,coco_url='http://images.cocodataset.org/val2017/000000000001.jpg')
        annotation=dict(id=4,image_id=1,bbox=[10,10,100,200],keypoints=[10,20,2]*6)
        document=dict(images=[image],licenses=[dict(id=4,url='https://creativecommons.org/licenses/by/2.0/')],annotations=[annotation])
        result=candidates(document,'cmu-foot');self.assertEqual(result,candidates(document,'cmu-foot'))
        self.assertEqual(result[0]['people'][0]['personId'],1);self.assertNotIn('contacts',result[0])
        document['images'][0]['license']=2;self.assertEqual(candidates(document,'cmu-foot'),[])
    def test_download_url_cannot_escape_official_validation_images(self):
        image=dict(file_name='000000000001.jpg',coco_url='http://images.cocodataset.org/val2017/000000000001.jpg')
        self.assertEqual(image_url(image),image['coco_url'])
        for url in ('https://example.com/val2017/000000000001.jpg','file:///etc/passwd','http://images.cocodataset.org/train2017/000000000001.jpg','http://images.cocodataset.org/val2017/000000000001.jpg?redirect=elsewhere'):
            with self.assertRaises(ValueError):image_url(dict(image,coco_url=url))

class RefinementTransactionTests(unittest.TestCase):
    def test_automatic_refinement_reuses_detected_points_without_user_corrections(self):
        source,pose=fixture(1,0);source['mhr']={'saved':True}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source['refinementSignature']=signature(root);atomic_json(root/'people.json',[dict(id=1)])
            with patch('refinement.image_dir',return_value=root),patch('refinement.cached_source',return_value=source),patch('rigs.profile',return_value=pose['rig']),patch('retarget.retarget',return_value=pose),patch('refinement.refine_sources',side_effect=lambda root,sources,*_,**kwargs:sources) as fitting,patch('wholebody.Landmarker.measure') as measurement,patch('coupled.fit_targets',return_value=dict(poses=[pose],diagnostics=dict(accepted=True))):
                result=refine(root,dict(imageId='same',members=[dict(personId=1,rigId='g8m')],automatic=True,support=[dict(personId=1,side='r',state='toe')]),lambda *_:None)
            fitting.assert_called_once();measurement.assert_not_called();self.assertTrue(result['automatic']);self.assertEqual(result['corrections'],[]);self.assertEqual(result['supportOverrides'][0]['state'],'toe')
    def test_automatic_legacy_cache_requires_reextraction_and_preserves_accepted(self):
        source,pose=fixture(1,0)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);atomic_json(root/'people.json',[dict(id=1)]);atomic_json(root/'refinement.json',dict(previous=True));before=(root/'refinement.json').read_bytes()
            with patch('refinement.image_dir',return_value=root),patch('refinement.cached_source',return_value=source):
                with self.assertRaisesRegex(ValueError,'Extract again once'):refine(root,dict(imageId='same',members=[dict(personId=1,rigId='g8m')],automatic=True),lambda *_:None)
            self.assertEqual(before,(root/'refinement.json').read_bytes())
    def test_rejected_and_cancelled_refinement_preserves_previous_cache(self):
        source,pose=fixture(1,0)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);atomic_json(root/'people.json',[dict(id=1)]);atomic_json(root/'refinement.json',dict(previous=True))
            before=(root/'refinement.json').read_bytes()
            with patch('refinement.image_dir',return_value=root),patch('refinement.cached_source',return_value=source),patch('rigs.profile',return_value=pose['rig']),patch('retarget.retarget',return_value=pose),patch('coupled.fit_targets',return_value=dict(poses=[pose],diagnostics=dict(accepted=False))),patch('refinement.refine_sources') as neural:
                with self.assertRaises(ValueError):refine(root,dict(imageId='same',members=[dict(personId=1,rigId='g8m')]),lambda *_:None)
                neural.assert_not_called();self.assertEqual((root/'refinement.json').read_bytes(),before)
            with patch('refinement.image_dir',return_value=root),patch('refinement.cached_source',return_value=source),patch('rigs.profile',return_value=pose['rig']),patch('retarget.retarget',return_value=pose),patch('coupled.fit_targets',return_value=dict(poses=[pose],diagnostics=dict(accepted=True))):
                def cancel(*_):raise InterruptedError('Cancelled')
                with self.assertRaises(InterruptedError):refine(root,dict(imageId='same',members=[dict(personId=1,rigId='g8m')]),cancel)
                self.assertEqual((root/'refinement.json').read_bytes(),before)
    def test_legacy_corrections_require_fused_parameters_but_not_for_contacts(self):
        source,pose=fixture(1,0)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);atomic_json(root/'people.json',[dict(id=1)])
            with patch('refinement.image_dir',return_value=root),patch('refinement.cached_source',return_value=source),patch('rigs.profile',return_value=pose['rig']),patch('retarget.retarget',return_value=pose):
                with self.assertRaisesRegex(ValueError,'older extraction lacks fused parameters'):refine(root,dict(imageId='same',members=[dict(personId=1,rigId='g8m')],corrections=[dict(personId=1,name='l_wrist',xy=[50,50])]),lambda *_:None)
    def test_profile_and_person_signatures_invalidate_accepted_history(self):
        source,pose=fixture(1,0)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);atomic_json(root/'people.json',[dict(id=1)]);atomic_json(root/'refinement.json',dict(poses=[pose],refinementSources=[source],sourceSignatures={1:source_signature(source)}))
            with patch('refinement.cached_source',return_value=source),patch('rigs.profile',return_value=pose['rig']):self.assertIsNotNone(accepted_result(root,root))
            changed=copy.deepcopy(pose['rig']);changed['nodes'][1]['center'][1]+=1
            with patch('refinement.cached_source',return_value=source),patch('rigs.profile',return_value=changed):self.assertIsNone(accepted_result(root,root))
            source['personKey']='new-detection'
            with patch('refinement.cached_source',return_value=source),patch('rigs.profile',return_value=pose['rig']):self.assertIsNone(accepted_result(root,root))

if __name__=='__main__':unittest.main()
