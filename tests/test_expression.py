import copy, json, math, os, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'worker'))
import expression as expr
from storage import atomic_json

class ExpressionTests(unittest.TestCase):
    def setUp(self):
        sandbox=Path(__file__).resolve().parents[1]/'temp/expression-validation';sandbox.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=sandbox);self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.image='0123456789abcdef01234567'
        folder=self.root/'data/history'/self.image;folder.mkdir(parents=True);(folder/'source.png').write_bytes(b'fixture');(folder/'thumb.jpg').write_bytes(b'thumb');atomic_json(folder/'image.json',dict(id=self.image,width=800,height=1000,name='fixture.jpg'))
        self.source=dict(version=1,engine=expr.ENGINE,imageId=self.image,face=dict(id=1,box=[100,100,400,600],actions={a:0. for a in expr.ACTIONS},landmarks=[[100.,200.,0.] for _ in range(478)],matrix=[1.,0,0,0,0,1.,0,0,0,0,1.,0,0,0,0,1.]),unknown=[],warnings=[])
        self.options=dict(strength=1.,regions={r:r!='gaze' for r in expr.REGIONS})
    def profile(self,rig='g9',changed=False):
        names=([expr.aliases(a,rig)[0] for a in expr.ACTIONS if expr.aliases(a,rig)])
        names=list(dict.fromkeys(names));drivers=[dict(id=n,owner='node:'+n.split('.')[0] if '.XRotate' in n or '.YRotate' in n else 'modifier:'+n,property=n.split('.')[1] if '.XRotate' in n or '.YRotate' in n else 'Value',label=n,min=-30 if 'Rotate' in n else -1 if rig!='g9' else 0,max=30 if 'Rotate' in n else 2 if changed else 1,default=0,locked=False,dependencies=[]) for n in names]
        return expr.cache_profile(self.root,dict(version=1,rigId=rig,drivers=drivers),rig)
    def target(self,rig='g9'):
        return expr.retarget(self.root,dict(source=self.source,options=self.options,rigId=rig))
    def test_three_generations_convert_without_mutating_source(self):
        self.source['face']['actions']['jawOpen']=.7;self.source['face']['actions']['eyeBlinkLeft']=.9;self.source['face']['actions']['eyeBlinkRight']=.1
        original=copy.deepcopy(self.source)
        for rig in ('g8f','g8m','g9'):
            self.profile(rig);target=self.target(rig);self.assertTrue(target['channels']);self.assertEqual(target['source'],original);self.assertEqual(target['previewActions']['eyeBlinkLeft'],.9);self.assertEqual(target['previewActions']['eyeBlinkRight'],.1)
        self.assertEqual(self.source,original)
    def test_disabled_unknown_gaze_omitted_not_zeroed(self):
        self.profile();self.source['unknown']=['eyes'];self.options['regions']['mouth']=False
        target=self.target();self.assertFalse(any('Eye' in k or 'Jaw' in k or 'Mouth' in k for k in target['channels']))
        self.assertTrue(any('Brow' in k for k in target['channels']))
    def test_explicit_neutral_overrides_unknown_without_touching_other_regions(self):
        self.profile();self.source['unknown']=['eyes'];self.source['face']['actions']['eyeBlinkLeft']=.9;self.source['face']['actions']['jawOpen']=.6;self.options['neutralRegions']=['eyes'];target=self.target()
        self.assertEqual(target['channels']['facs_bs_EyeBlinkLeft'],0);self.assertEqual(target['channels']['facs_bs_JawOpen'],.6);self.assertNotIn('facs_bs_EyeLookUpLeft',target['channels'])
    def test_limits_strength_signed_opposing_controls(self):
        self.profile('g8f');self.source['face']['actions'].update(jawLeft=.9,jawRight=.1,eyeBlinkLeft=.9);self.options['strength']=1.5
        target=self.target('g8f');self.assertEqual(target['channels']['eCTRLEyesClosedL'],1);self.assertAlmostEqual(target['channels']['eCTRLJawSide-Side'],-1);self.assertEqual(target['previewActions']['jawRight'],0)
    def test_preview_keeps_exaggeration_when_the_connected_driver_allows_it(self):
        self.profile('g9',changed=True);self.source['face']['actions']['jawOpen']=.8;self.options['strength']=1.5
        target=self.target();self.assertAlmostEqual(target['channels']['facs_bs_JawOpen'],1.2);self.assertAlmostEqual(target['previewActions']['jawOpen'],1.2)
    def test_profile_reconnection_invalidates_prior_target(self):
        self.profile();target=self.target();self.profile(changed=True)
        with self.assertRaisesRegex(ValueError,'connection changed'):expr.validated_target(self.root,dict(expression=target))
    def test_controller_enumeration_order_does_not_invalidate_a_profile(self):
        raw=dict(version=1,rigId='g9',drivers=[dict(id='facs_bs_JawOpen',owner='figure',property='facs_bs_JawOpen',min=0,max=1,default=0,locked=False,dependencies=['second','first','second'])])
        before=expr.cache_profile(self.root,raw,'g9');raw['drivers'][0]['dependencies']=['first','second']
        self.assertEqual(before['signature'],expr.cache_profile(self.root,raw,'g9')['signature'])
    def test_tampered_channels_rejected(self):
        self.profile();target=self.target();target['channels']['identity_shape']=1
        with self.assertRaisesRegex(ValueError,'channels changed'):expr.validated_target(self.root,dict(expression=target))
    def test_duf_is_expression_only_and_uses_actual_modifier_uri(self):
        self.profile();self.source['face']['actions']['jawOpen']=.5;target=self.target();doc=expr.duf(self.root,dict(expression=target))
        self.assertTrue(any(a['url']=='name://@selection#facs_bs_JawOpen:?value/value' for a in doc['scene']['animations']))
        text=json.dumps(doc);self.assertNotIn('rotation',text);self.assertNotIn('translation',text);self.assertNotIn('scale',text)
    def test_locked_identity_controls_never_mapped(self):
        raw=dict(version=1,rigId='g9',drivers=[dict(id='facs_bs_JawOpen',owner='modifier:facs_bs_JawOpen',property='Value',min=0,max=1,default=0,locked=False,dependencies=['emotionSmile']),dict(id='facs_bs_EyeBlinkLeft',owner='modifier:facs_bs_EyeBlinkLeft',property='Value',min=0,max=1,default=0,locked=True,dependencies=[])])
        raw['drivers'][0]['locked']=True
        raw['drivers'].append(dict(id='identityShape',owner='modifier:identityShape',property='Value',min=0,max=1,default=0,locked=False,dependencies=[]))
        with self.assertRaisesRegex(ValueError,'No supported'):expr.cache_profile(self.root,raw,'g9')
    def test_g9_split_actions_apply_both_sides_without_count_inflation(self):
        names=['facs_bs_BrowInnerUpLeft','facs_bs_BrowInnerUpRight','facs_bs_MouthSmileLeft','facs_bs_MouthSmileRight']
        raw=dict(version=1,rigId='g9',drivers=[dict(id=n,owner='figure',property=n,min=0,max=1,default=0,locked=False,dependencies=['customCombo']) for n in names])
        expr.cache_profile(self.root,raw,'g9');self.source['face']['actions']['browInnerUp']=.6;target=self.target()
        self.assertEqual(target['channels']['facs_bs_BrowInnerUpLeft'],.6);self.assertEqual(target['channels']['facs_bs_BrowInnerUpRight'],.6);self.assertEqual(target['supported'],3)
    def test_g8_negative_directions_and_no_double_brow_driver(self):
        names=['eCTRLBrowInnerUp-DownL','eCTRLBrowOuterUp-DownL','eCTRLBrowUp-DownL','eCTRLLipBottomUp-DownL']
        expr.cache_profile(self.root,dict(version=1,rigId='g8f',drivers=[dict(id=n,owner='figure',property=n,min=-1,max=1,default=0,locked=False,dependencies=[]) for n in names]),'g8f')
        self.source['face']['actions'].update(browDownLeft=.5,mouthLowerDownLeft=.7);target=self.target('g8f')
        self.assertEqual(target['channels']['eCTRLBrowInnerUp-DownL'],-.5);self.assertEqual(target['channels']['eCTRLLipBottomUp-DownL'],-.7);self.assertNotIn('eCTRLBrowUp-DownL',target['channels'])
    def test_input_schema_fails_closed(self):
        for mutate in [lambda s:s['face']['actions'].update(jawOpen=float('nan')),lambda s:s['face']['landmarks'].pop(),lambda s:s.update(imageId='../escape'),lambda s:s['face'].update(id=33),lambda s:s['face']['actions'].update(identityShape=.5)]:
            bad=copy.deepcopy(self.source);mutate(bad)
            with self.assertRaises(ValueError):expr.source(self.root,bad)
    def test_rounding_only_is_accepted_but_recomputed_values_are_authoritative(self):
        self.profile();self.source['face']['actions']['jawOpen']=.291730119129;target=self.target()
        expected=copy.deepcopy(target);target['channels']={k:math.nextafter(v,math.inf) for k,v in target['channels'].items()}
        self.assertEqual(expr.validated_target(self.root,dict(expression=target)),expected)
        target['channels']['facs_bs_JawOpen']+=1e-6
        with self.assertRaisesRegex(ValueError,'channels changed'):expr.validated_target(self.root,dict(expression=target))
        target['channels']['facs_bs_JawOpen']=float('nan')
        with self.assertRaisesRegex(ValueError,'channels changed'):expr.validated_target(self.root,dict(expression=target))
    def test_shared_drivers_do_not_invent_or_amplify_preview_actions(self):
        self.profile('g8f');self.source['face']['actions']['browInnerUp']=.7
        target=self.target('g8f');self.assertEqual(target['previewActions']['browOuterUpLeft'],0);self.assertEqual(target['previewActions']['browDownLeft'],0)
        self.source['face']['actions']['browDownLeft']=.4;target=self.target('g8f')
        self.assertLessEqual(target['previewActions']['browInnerUp'],.7);self.assertLessEqual(target['previewActions']['browDownLeft'],.4)
    def test_extra_tongue_preserves_legacy_actions_and_face9_history(self):
        self.profile('g9');self.source['face']['id']=9;self.source['face']['rawActions']=copy.deepcopy(self.source['face']['actions']);self.source['face']['extras']={'tongueOut':.8}
        raw=dict(version=1,rigId='g9',drivers=[dict(id='facs_bs_TongueOut',owner='figure',property='facs_bs_TongueOut',min=0,max=1,default=0,locked=False,dependencies=[])])
        expr.cache_profile(self.root,raw,'g9');target=self.target();self.assertEqual(target['channels']['facs_bs_TongueOut'],.8);self.assertEqual(target['previewActions']['tongueOut'],.8)
        self.assertNotIn('tongueOut',target['source']['face']['actions']);self.assertEqual(target['source']['face']['extras']['tongueOut'],.8)
        expr.save(self.root,dict(source=self.source,options=self.options,rigId='g9'));self.assertEqual(expr.history(self.root)[0]['faceId'],9);expr.remove(self.root,dict(imageId=self.image,faceId=9,observationId=expr.history(self.root)[0]['observationId']))
        bad=copy.deepcopy(self.source);bad['face']['extras']['identityShape']=.7
        with self.assertRaisesRegex(ValueError,'Unknown supplemental'):expr.source(self.root,bad)
    def test_g8_tongue_extension_uses_negative_in_out_and_migrates_cached_metadata(self):
        for rig in ('g8f','g8m'):
            name='eCTRLTongueIn-Out'
            raw=dict(version=1,rigId=rig,drivers=[dict(id=name,owner='figure',property=name,min=-1,max=1,default=0,locked=False,dependencies=[])])
            previous=expr.cache_profile(self.root,raw,rig);previous['mappingVersion']=4;previous['mappings'][0]['weight']=1
            atomic_json(self.root/'data/face-profiles'/f'{rig}.json',previous)
            self.source['face']['extras']={'tongueOut':.8}
            target=self.target(rig);self.assertEqual(target['channels'][name],-.8);self.assertEqual(target['previewActions']['tongueOut'],.8)
            self.assertEqual(expr.profile(self.root,rig)['mappingVersion'],9)
    def test_g8_puff_uses_opposite_anatomical_dial_signs_and_migrates_v7(self):
        for rig in ('g8f','g8m'):
            names=['eCTRLCheeksBalloon-SuckInL','eCTRLCheeksBalloon-SuckInR']
            raw=dict(version=1,rigId=rig,drivers=[dict(id=n,owner='figure',property=n,min=-1,max=1,default=0,locked=False,dependencies=[]) for n in names])
            previous=expr.cache_profile(self.root,raw,rig);previous['mappingVersion']=7
            for m in previous['mappings']:m['weight']=1
            atomic_json(self.root/'data/face-profiles'/f'{rig}.json',previous)
            self.source['face']['actions']['cheekPuff']=.7
            target=self.target(rig)
            self.assertEqual(target['channels'][names[0]],.7);self.assertEqual(target['channels'][names[1]],-.7)
            self.assertEqual(target['previewActions']['cheekPuff'],.7)
            self.assertEqual(expr.validated_target(self.root,dict(expression=target)),target)
    def test_old_g8_paired_gaze_averages_measurements_without_doubling_preview(self):
        for rig in ('g8f','g8m'):
            names=['eCTRLEyesSideSide','eCTRLEyesUpDown']
            raw=dict(version=1,rigId=rig,drivers=[dict(id=n,owner='figure',property=n,min=-1,max=1,default=0,locked=False,dependencies=[]) for n in names])
            previous=expr.cache_profile(self.root,raw,rig);previous['mappingVersion']=7;previous['mappings']=[]
            atomic_json(self.root/'data/face-profiles'/f'{rig}.json',previous)
            self.source['face']['actions'].update(eyeLookOutLeft=.8,eyeLookInRight=.6,eyeLookUpLeft=.4,eyeLookDownRight=.2)
            self.options['regions']['gaze']=True;target=self.target(rig)
            self.assertAlmostEqual(target['channels'][names[0]],-.56);self.assertAlmostEqual(target['channels'][names[1]],.075)
            self.assertAlmostEqual(target['previewActions']['eyeLookOutLeft'],.7);self.assertAlmostEqual(target['previewActions']['eyeLookInRight'],.7)
            self.assertAlmostEqual(target['previewActions']['eyeLookUpLeft'],.1);self.assertAlmostEqual(target['previewActions']['eyeLookUpRight'],.1)
            self.assertEqual(target['previewActions']['eyeLookDownRight'],0)
            self.assertEqual(expr.profile(self.root,rig)['pairedGazeAxes'],['horizontal','vertical'])
            self.assertEqual(expr.validated_target(self.root,dict(expression=target)),target)
            self.assertTrue(any('Paired eye direction' in w for w in target['warnings']))
            self.options['regions']['gaze']=False
            with self.assertRaisesRegex(ValueError,'No enabled'):self.target(rig)
    def test_direct_gaze_never_combines_with_paired_controls_on_same_axis(self):
        rig='g8f';previous=self.profile(rig)
        paired=[dict(id=n,owner='figure',property=n,min=-1,max=1,default=0,locked=False,dependencies=[]) for n in ('eCTRLEyesSideSide','eCTRLEyesUpDown')]
        p=expr.cache_profile(self.root,dict(version=1,rigId=rig,drivers=previous['drivers']+paired),rig)
        self.assertEqual(p['pairedGazeAxes'],[])
        self.options['regions']['gaze']=True;self.source['face']['actions']['eyeLookOutLeft']=.8
        target=self.target(rig);self.assertNotIn('eCTRLEyesSideSide',target['channels']);self.assertNotIn('eCTRLEyesUpDown',target['channels'])
        self.assertAlmostEqual(target['channels']['lEye.YRotate'],-12.8)
    def test_each_eyelid_override_preserves_other_eye_and_uses_signed_widen(self):
        for rig in ('g8f','g8m','g9'):
            self.profile(rig);self.source['face']['actions'].update(eyeBlinkRight=.7,eyeSquintRight=.4)
            for action in ('eyeBlinkLeft','eyeSquintLeft','eyeWideLeft'):
                self.options['adjustments']={k:.8 if k==action else 0 for k in ('eyeBlinkLeft','eyeSquintLeft','eyeWideLeft')}
                target=self.target(rig)
                self.assertAlmostEqual(target['previewActions'][action],.8);self.assertAlmostEqual(target['previewActions']['eyeBlinkRight'],.7)
                if rig!='g9' and action=='eyeWideLeft':self.assertAlmostEqual(target['channels']['eCTRLEyesSquint-WidenL'],-.8)
    def test_unknown_and_disabled_mouth_preserve_tongue_and_omit_channels(self):
        self.profile('g9');self.source['face']['extras']={'tongueOut':1};self.source['unknown']=['mouth'];target=self.target()
        self.assertNotIn('facs_bs_TongueOut',target['channels']);self.assertNotIn('tongueOut',target['previewActions'])
    def test_independent_g8_gaze_has_correct_signs_degrees_and_preview_amounts(self):
        for rig in ('g8f','g8m'):
            drivers=[dict(id=node+'.'+axis,owner='node:'+node,property=axis,min=-30,max=30,default=0,locked=False,dependencies=[]) for node in ('lEye','rEye') for axis in ('XRotate','YRotate')]
            expr.cache_profile(self.root,dict(version=1,rigId=rig,drivers=drivers),rig)
            self.source['face']['actions'].update(eyeLookOutLeft=.8,eyeLookInRight=.6,eyeLookUpLeft=.4,eyeLookDownRight=.2)
            self.options['regions']['gaze']=True;target=self.target(rig)
            self.assertAlmostEqual(target['channels']['lEye.YRotate'],-12.8);self.assertAlmostEqual(target['channels']['rEye.YRotate'],-9.6)
            self.assertAlmostEqual(target['channels']['lEye.XRotate'],4.8);self.assertAlmostEqual(target['channels']['rEye.XRotate'],-2.4)
            self.assertAlmostEqual(target['previewActions']['eyeLookOutLeft'],.8)
            self.assertIn('name://@selection/lEye#YRotate:?value/value',[a['url'] for a in expr.duf(self.root,dict(expression=target))['scene']['animations']])
    def test_v8_gaze_profiles_migrate_without_reversing_preview_or_other_regions(self):
        for rig in ('g8f','g8m'):
            old=self.profile(rig);old['mappingVersion']=8
            for mapping in old['mappings']:
                if mapping['region']=='gaze':mapping['weight']*=-1
            atomic_json(self.root/'data/face-profiles'/f'{rig}.json',old)
            self.source['face']['actions'].update(eyeLookOutLeft=.8,eyeLookInRight=.6,jawOpen=.3)
            self.options['regions']['gaze']=True;original=copy.deepcopy(self.source);target=self.target(rig)
            self.assertEqual(expr.profile(self.root,rig)['mappingVersion'],9)
            self.assertAlmostEqual(target['channels']['lEye.YRotate'],-12.8)
            self.assertAlmostEqual(target['channels']['rEye.YRotate'],-9.6)
            self.assertAlmostEqual(target['previewActions']['eyeLookOutLeft'],.8)
            self.assertAlmostEqual(target['channels']['eCTRLMouthOpen'],.3)
            self.assertEqual(self.source,original)
    def test_supplemental_acceptance_survives_serialization_and_rejects_non_boolean(self):
        self.source['face']['evidence']=dict(passes=2,consistency={},supplemental=dict(cheekPuff=dict(value=.6154,agreement=.6406,accepted=True,method='geometry-v1')))
        normalized=expr.source(self.root,json.loads(json.dumps(self.source)))
        self.assertIs(normalized['face']['evidence']['supplemental']['cheekPuff']['accepted'],True)
        self.source['face']['evidence']['supplemental']['cheekPuff']['accepted']='true'
        with self.assertRaisesRegex(ValueError,'acceptance'):expr.source(self.root,self.source)
    def test_explicit_adjustments_replace_uncertain_measurements_without_source_mutation(self):
        self.profile();self.source['unknown']=['mouth'];self.options['adjustments']={'jawOpen':.8}
        original=copy.deepcopy(self.source);target=self.target()
        self.assertEqual(target['channels']['facs_bs_JawOpen'],.8);self.assertEqual(target['previewActions']['jawOpen'],.8)
        self.assertEqual(self.source,original);self.assertEqual(expr.validated_target(self.root,dict(expression=target)),target)
        self.options['adjustments']['identityShape']=.5
        with self.assertRaisesRegex(ValueError,'Unknown expression adjustment'):self.target()
    def test_g9_gaze_drives_rotations_not_derived_facs_outputs(self):
        self.profile('g9');self.options['regions']['gaze']=True
        self.source['face']['actions'].update(eyeLookOutLeft=.75,eyeLookInRight=.5,eyeLookUpLeft=.6)
        target=self.target('g9');self.assertEqual(target['channels']['l_eye.YRotate'],-12)
        self.assertEqual(target['channels']['r_eye.YRotate'],-8);self.assertAlmostEqual(target['channels']['l_eye.XRotate'],7.2)
        self.assertFalse(any('EyeLook' in k for k in target['channels']))
    def test_g9_missing_mouth_is_explicitly_unsupported_and_cached_anatomy_survives_migration(self):
        previous=self.profile('g9');raw=dict(version=1,rigId='g9',drivers=previous['drivers']+[dict(id='facs_bs_TongueOut',owner='figure',property='facs_bs_TongueOut',min=0,max=1,default=0,locked=False,dependencies=[])],anatomy=dict(tongue=False,eyes=False))
        previous=expr.cache_profile(self.root,raw,'g9');previous['mappingVersion']=6;atomic_json(self.root/'data/face-profiles/g9.json',previous)
        self.source['face']['extras']={'tongueOut':1};self.options['regions']['gaze']=True;target=self.target('g9')
        self.assertNotIn('facs_bs_TongueOut',target['channels']);self.assertNotIn('tongueOut',target['previewActions'])
        self.assertIn('tongueOut',expr.profile(self.root,'g9')['unsupported']);self.assertEqual(expr.profile(self.root,'g9')['anatomy'],raw['anatomy'])
        self.assertTrue(any('Mouth attachment' in w for w in target['warnings']));self.assertTrue(any('Eyes attachment' in w for w in target['warnings']))
    def test_gaze_alias_cannot_impersonate_an_anatomical_eye_rotation(self):
        raw=dict(version=1,rigId='g8f',drivers=[dict(id='lEye.YRotate',owner='figure',property='fakeGaze',min=-30,max=30,default=0,locked=False,dependencies=[])])
        with self.assertRaisesRegex(ValueError,'No supported'):expr.cache_profile(self.root,raw,'g8f')
    def test_history_deletion_does_not_delete_pose_or_photo(self):
        folder=self.root/'data/history'/self.image;(folder/'solve-pure-1.json').write_text('{}')
        expr.save(self.root,dict(source=self.source,options=self.options,rigId='g9'));rows=expr.history(self.root);self.assertEqual(len(rows),1);self.assertEqual(rows[0]['kind'],'expression');self.assertEqual(rows[0]['faceId'],1)
        expr.remove(self.root,dict(imageId=self.image,faceId=1,observationId=rows[0]['observationId']));self.assertEqual(expr.history(self.root),[]);self.assertTrue((folder/'source.png').exists());self.assertTrue((folder/'solve-pure-1.json').exists())
    def test_private_worker_expression_transport_without_cuda(self):
        from PIL import Image
        workspace=Path(__file__).resolve().parents[1]
        folder=self.root/'data/history'/self.image
        Image.new('RGB',(800,1000)).save(folder/'source.png')
        Image.new('RGB',(80,100)).save(folder/'thumb.jpg')
        atomic_json(folder/'image.json',dict(id=self.image,width=800,height=1000,name='Expression fixture',created=1))
        pose=folder/'solve-pure-1.json';pose.write_bytes(b'previous body pose')
        for rig in ('g8f','g8m','g9'):self.profile(rig)
        target=self.target('g9')
        tasks=[('retarget_expression',dict(source=self.source,options=self.options,rigId=rig)) for rig in ('g8f','g8m','g9')]
        canonical=expr.source(self.root,self.source)
        canonical['face']['observationId']=expr.observation_id(self.image,canonical['face'])
        address=dict(imageId=self.image,faceId=1,observationId=canonical['face']['observationId'])
        tasks.extend([
            ('save_expression',dict(source=self.source,options=self.options,rigId='g9')),
            ('read_expression',address),
            ('history',{}),
            ('export_expression',dict(expression=target,path=str(self.root/'expression.duf'))),
            ('remove_history',dict(address,kind='expression')),
            ('history',{}),
        ])
        requests=[dict(version=1,jobId='face-'+str(i),method=method,payload=payload) for i,(method,payload) in enumerate(tasks)]
        env=dict(os.environ,CUDA_VISIBLE_DEVICES='',PYTHONPATH=str(self.root/'nonexistent'),PYTHONHOME=str(self.root/'nonexistent'),TEMP=str(self.root/'temp'),TMP=str(self.root/'temp'))
        run=subprocess.run([str(workspace/'runtime/python/python.exe'),'-I','-B','-u',str(workspace/'worker/main.py'),'--root',str(self.root)],input=''.join(json.dumps(r)+'\n' for r in requests),capture_output=True,text=True,encoding='utf-8',env=env,timeout=25,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.assertEqual(run.returncode,0,run.stderr)
        replies=[json.loads(line) for line in run.stdout.splitlines()]
        self.assertEqual([r['jobId'] for r in replies],[r['jobId'] for r in requests])
        self.assertTrue(all(r['type']=='result' for r in replies),run.stdout)
        self.assertEqual([r['result']['rigId'] for r in replies[:3]],['g8f','g8m','g9'])
        self.assertEqual(replies[4]['result']['source'],canonical)
        self.assertTrue(any(r.get('kind')=='expression' for r in replies[5]['result']))
        self.assertFalse(any(r.get('kind')=='expression' for r in replies[-1]['result']))
        self.assertEqual(pose.read_bytes(),b'previous body pose')
        self.assertEqual(json.loads((self.root/'expression.duf').read_text()),expr.duf(self.root,dict(expression=target)))

if __name__=='__main__':unittest.main()
