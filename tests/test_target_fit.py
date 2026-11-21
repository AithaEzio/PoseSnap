"""Frozen real-source regression plus small, independent acceptance checks.

The observations are model estimates, not annotated accuracy ground truth.
No photos, networks, GPU inference or mutable user history are used here.
"""
import copy,json,unittest
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch
from types import SimpleNamespace
import numpy as np
from coupled import bounded_fallback,fit_targets,regional_observations,TARGET_FIT_VERSION
from measurements import quality,target_points,project_target
from retarget import retarget
from posture import drift
from inference import fused_checkpoint
from daz import duf
from test_posture import measured_fixture

FIXTURES=Path(__file__).parent/'fixtures/target-fit'

class FallbackTests(unittest.TestCase):
    def test_batched_capsule_distances_match_scalar_for_degenerate_and_random_segments(self):
        from interaction import segment_distance,segment_distances
        rng=np.random.default_rng(1941);p=rng.normal(size=(16,4,3))*100
        p[0]=0.;p[1]=[[0,0,0],[1,0,0],[0,1,0],[1,1,0]]
        p[2]=[[0,0,0],[1,0,0],[.5,-1,0],[.5,1,0]];p[3,1]=p[3,0]
        a,b,c,d=np.moveaxis(p,1,0)
        actual=segment_distances(a[:,None,:],b[:,None,:],c[None,:,:],d[None,:,:])
        expected=np.array([[segment_distance(x,y,z,w) for z,w in zip(c,d)] for x,y in zip(a,b)])
        np.testing.assert_allclose(actual,expected,atol=1e-10,rtol=1e-12)

    def test_reused_fk_frames_match_independent_geometry_and_posture(self):
        from interaction import geometry
        from posture import core_frame
        source,pose=measured_fixture(12)
        pose['translation']=[13.5,-7.25,43.75]
        state=target_points(pose,include_frames=True)[2]
        from retarget import rest_transforms
        prepared=target_points(pose,include_frames=True,rest=rest_transforms(pose['rig']))[2]
        for group,other in zip(state,prepared):
            for key in group:np.testing.assert_array_equal(group[key],other[key])
        local=(state[0],{k:v-np.asarray(pose['translation']) for k,v in state[1].items()})
        original=geometry(pose);reused=geometry(pose,frames=local)
        for key in original[0]:np.testing.assert_allclose(original[0][key],reused[0][key],atol=1e-10)
        for a,b in zip(original[1],reused[1]):
            np.testing.assert_allclose(a[0],b[0],atol=1e-10);np.testing.assert_allclose(a[1],b[1],atol=1e-10)
            self.assertEqual(a[2:],b[2:])
        a,b=core_frame(pose),core_frame(pose,state)
        for key in a['rotations']:np.testing.assert_allclose(a['rotations'][key],b['rotations'][key],atol=1e-10)
        self.assertEqual(a['depth'],b['depth']);self.assertEqual(a['tilt'],b['tilt'])

    def test_filtered_capsules_keep_their_actual_fk_dependencies(self):
        from interaction import geometry
        source,pose=measured_fixture(0)
        pose['cropPolicy']=dict(enabled=True,zeroSemantics=['l_upperarm','l_thigh','l_shin'])
        positions,capsules,_,dependencies=geometry(pose,include_dependencies=True)
        self.assertEqual(len(capsules),len(dependencies))
        for capsule,(start,end) in zip(capsules,dependencies):
            np.testing.assert_allclose(capsule[0],positions[start],atol=1e-10)
            np.testing.assert_allclose(capsule[1],positions[end],atol=1e-10)
        self.assertNotIn(('lShldrBend','lForearmBend'),dependencies)

    def test_detail_pass_has_live_progress_and_propagates_cancellation(self):
        source,pose=measured_fixture(0);calls=[]
        def optimizer(fun,start,**options):
            calls.append(options['max_nfev'])
            return SimpleNamespace(x=start.copy(),fun=fun(start),status=0)
        def progress(label,percent):
            if 'second pass' in label and label.endswith('s') and label[-2].isdigit():raise InterruptedError('cancelled')
        with patch('coupled.least_squares',side_effect=optimizer),patch('coupled.perf_counter',side_effect=range(1,100)),self.assertRaises(InterruptedError):
            fit_targets([source],[pose],progress=progress,warm_start=True,preserve=True)
        self.assertEqual(calls,[50,50])

    def test_arm_guard_does_not_double_count_specialist_hand_wrist(self):
        body=[dict(name='l_'+part,region='body') for part in ('shoulder','elbow','wrist')]
        duplicate=dict(name='l_wrist',region='l_hand')
        observations=[(0,p,2) for p in body+[duplicate]]+[(1,body[0],2)]
        self.assertEqual(regional_observations(observations,0,'l_arm'),body)
        self.assertEqual(regional_observations(observations,0,'l_hand'),[duplicate])
    def test_a_visible_hip_alone_is_not_a_visible_cropped_leg_chain(self):
        hip=dict(name='l_hip',region='body');knee=dict(name='l_knee',region='body')
        self.assertEqual(regional_observations([(0,hip,2)],0,'l_leg'),[])
        self.assertEqual(regional_observations([(0,hip,2),(0,knee,2)],0,'l_leg'),[hip,knee])
    def test_only_failed_chain_is_reduced_and_best_valid_trial_is_used(self):
        base=np.zeros(3);proposal=np.array([8.,10.,6.]);refit=Mock()
        check=lambda x:dict(message='Bad limb',columns={0,1}) if x[1]>3 else None
        result,failure,outcome=bounded_fallback(base,proposal,{0},check,lambda x:(x[1]-3)**2,refit)
        np.testing.assert_allclose(result,[8,2.5,6]);self.assertEqual(outcome,'partial');self.assertEqual(failure['message'],'Bad limb');refit.assert_not_called()
    def test_unsafe_placement_is_not_forced_into_accepted_pose(self):
        base=np.zeros(2);proposal=np.array([8.,6.]);refit=Mock(return_value=proposal)
        result,_,outcome=bounded_fallback(base,proposal,{0},lambda x:dict(message='Placement worsens evidence',columns={0}) if x[0]>2 else None,np.linalg.norm,refit)
        np.testing.assert_array_equal(result,base);self.assertEqual(outcome,'retained');refit.assert_not_called()
    def test_one_refit_can_recover_but_must_pass_complete_validation(self):
        base=np.zeros(3);proposal=np.array([8.,10.,6.])
        check=lambda x:None if 2.9<x[1]<3.1 and x[0]==8 and x[2]==6 else dict(message='Bad limb',columns={1})
        refit=Mock(return_value=np.array([8.,3.,6.]))
        result,_,outcome=bounded_fallback(base,proposal,{0},check,np.linalg.norm,refit)
        np.testing.assert_allclose(result,[8,3,6]);self.assertEqual(outcome,'partial');refit.assert_called_once_with({1})
        refit.return_value=np.array([8.,9.,6.]);result,_,outcome=bounded_fallback(base,proposal,{0},check,np.linalg.norm,refit)
        np.testing.assert_array_equal(result,base);self.assertEqual(outcome,'retained')
    def test_real_fk_partial_fit_retains_full_valid_placement(self):
        source,pose=measured_fixture(0)
        for item in source['measurements']:item['xy'][0]+=2.5
        def proposed(fun,start,**kwargs):
            context=dict(zip(fun.__code__.co_freevars,[c.cell_contents for c in fun.__closure__]))
            if 'candidate' not in context:
                fun=context['residual'];context=dict(zip(fun.__code__.co_freevars,[c.cell_contents for c in fun.__closure__]))
            candidate=context['candidate'];variables=dict(zip(candidate.__code__.co_freevars,[c.cell_contents for c in candidate.__closure__]))['variables']
            values=start.copy();values[variables.index((0,'translation',0))]+=1.;values[variables.index((0,'lFoot',0))]+=20.
            return SimpleNamespace(x=values,fun=fun(values),status=1)
        with patch('coupled.least_squares',side_effect=proposed):
            result=fit_targets([source],[pose],warm_start=True,preserve=True)
        p=result['poses'][0];self.assertEqual(result['diagnostics']['outcome'],'partial');self.assertTrue(p['quality']['fit']['placementPreserved'])
        self.assertAlmostEqual(p['translation'][0],pose['translation'][0]+1.,places=8)
        self.assertEqual(p['rotations']['lFoot'][0],0.)
        self.assertEqual(p['quality']['visible']['matched'],1.)
        self.assertEqual(p['referenceCamera'],pose['referenceCamera']);self.assertLess(drift(p,pose)['coreRotationDegrees'],1e-8)
    def test_raw_fused_checkpoint_survives_source_optimization(self):
        source=dict(refinementSignature='model',mhr=dict(modelParams=[1,2],shapeParams=[3],exprParams=[4]),cameraTranslation=[5,6,7],quality=dict(visible=dict(matched=.8)))
        snapshot=fused_checkpoint(source);source['mhr']['modelParams'][0]=99;source['cameraTranslation'][0]=99;source['quality']['visible']['matched']=0
        self.assertEqual(snapshot['mhr']['modelParams'],[1,2]);self.assertEqual(snapshot['cameraTranslation'],[5,6,7]);self.assertEqual(snapshot['quality']['visible']['matched'],.8)

class DancingRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=json.loads((FIXTURES/'dancing-source.json').read_text(encoding='utf-8'))
        cls.initial={};cls.results={}
        for rig_id in ('g8f','g8m','g9'):
            rig=json.loads((FIXTURES/(rig_id+'.json')).read_text(encoding='utf-8'))
            cls.initial[rig_id]=retarget(cls.source,rig)
            cls.results[rig_id]=fit_targets([cls.source],[cls.initial[rig_id]],preserve=True)
    def test_full_fits_and_per_region_errors_recover_on_all_three_rigs(self):
        expected={'g8f':37/60,'g8m':33/60,'g9':39/60}
        for rig_id,result in self.results.items():
            with self.subTest(rig=rig_id):
                p=result['poses'][0];q=p['quality'];self.assertTrue(result['diagnostics']['accepted']);self.assertEqual(result['diagnostics']['outcome'],'full')
                # A numerical solver can put an extra point just inside a hard
                # tolerance. Preserve the established minimum and error limits,
                # rather than rejecting a strictly better point count.
                self.assertGreaterEqual(q['visible']['matched'],expected[rig_id]);self.assertEqual(q['coverage'],dict(observed=60,expected=60))
                self.assertEqual(p['targetFitVersion'],TARGET_FIT_VERSION);self.assertEqual(q['fit']['outcome'],'full')
                self.assertLess(drift(p,self.initial[rig_id])['coreRotationDegrees'],1e-6)
                self.assertEqual(p['footSupport'],[dict(side='l',state='air'),dict(side='r',state='toe')])
        q=self.results['g8f']['poses'][0]['quality']
        # Anatomical G8 bend centres replace distal twist centres. Body error
        # must now stay below 25 px (formerly 51); small distal tradeoffs reflect
        # the conflicting body/specialist wrist measurements, not ground truth.
        for region,maximum in {'body':25,'l_hand':8,'r_hand':3,'l_foot':4,'r_foot':7}.items():self.assertLess(q['regions'][region]['meanErrorPx'],maximum,region)
        self.assertFalse(next(c for c in q['fit']['regionalChanges'] if c['region']=='l_arm')['worsened'])
    def test_independent_projection_counts_and_missing_coverage(self):
        p=self.results['g8f']['poses'][0];q=p['quality'];camera=p['referenceCamera'];points,_=target_points(p);k=np.array(camera['intrinsics']);matched=0
        for marker in q['markers']:
            x,y,z=np.array(points[marker['name']])+camera['originCm'];self.assertLess(z,0)
            projected=np.array([k[0,0]*x/-z+k[0,2],k[1,1]*-y/-z+k[1,2]])
            error=float(np.linalg.norm(projected-marker['xy']));self.assertAlmostEqual(error,marker['errorPx'],places=8)
            matched+=error<=q['regions'][marker['region']]['tolerancePx']
        self.assertGreaterEqual(matched,37);self.assertAlmostEqual(q['visible']['matched'],matched/60)
        s=copy.deepcopy(self.source)
        for item in s['measurements']:
            if item['region']=='r_hand':item['known']=False
        missing=quality(s,p,camera);self.assertEqual(missing['coverage'],dict(observed=39,expected=60));self.assertIsNone(missing['regions']['r_hand']['matched'])
        self.assertEqual(quality(self.source,p,camera)['regions'],q['regions'])
    def test_camera_recentering_and_rig_export_are_exact(self):
        for rig_id,result in self.results.items():
            p=result['poses'][0];self.assertEqual(p['rig'],self.initial[rig_id]['rig'])
            points,_=target_points(p);shift=np.array([12.,-23.,31.]);moved=copy.deepcopy(p);moved['translation']=(np.array(p['translation'])-shift).tolist();camera=dict(p['referenceCamera'],originCm=(np.array(p['referenceCamera']['originCm'])+shift).tolist());after,_=target_points(moved)
            for name in points:np.testing.assert_allclose(project_target(points[name],p['referenceCamera']),project_target(after[name],camera),atol=1e-9)
            exported={r['url']:r['keys'][0][1] for r in duf(p,'floor')['scene']['animations']}
            for bone,angles in p['rotations'].items():
                for axis,angle in zip('xyz',angles):
                    key=f'name://@selection/{bone}:?rotation/{axis}/value'
                    if key in exported:self.assertLess(abs(exported[key]-angle),.1)
    def test_repeat_fit_keeps_immutable_posture_and_reference_camera(self):
        p=self.results['g8f']['poses'][0];anchor=copy.deepcopy(p)
        for _ in range(2):
            result=fit_targets([self.source],[p],warm_start=True,preserve=True,anchors=[anchor]);p=result['poses'][0]
            self.assertTrue(result['diagnostics']['accepted']);self.assertEqual(p['referenceCamera'],anchor['referenceCamera']);self.assertLess(drift(p,anchor)['coreRotationDegrees'],1e-6)
            self.assertGreaterEqual(p['quality']['visible']['matched'],anchor['quality']['visible']['matched']-.05)
            self.assertEqual(p['rig'],anchor['rig'])

if __name__=='__main__':unittest.main()
