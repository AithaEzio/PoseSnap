import copy,os,tempfile,unittest
import numpy as np
from pathlib import Path
from unittest.mock import patch
from extraction import method,selected,pure_signature,result_path,extraction_pose,PURE_VERSION
from instances import identity,cached_source,source_path
from storage import atomic_json, remember_history, restore_history
from test_instances import person
from test_interaction import fixture
from inference import Inference
from interaction import coordinate
from refinement import accepted_result,source_signature

class ExtractionModeTests(unittest.TestCase):
    def directory(self):return tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'temp')
    def test_history_restores_exact_preview_independently_of_method_and_models(self):
        with self.directory() as d:
            folder=Path(d)/'reference';p=person()
            _,pose=fixture(p['id'],0)
            pose.update(imageId=folder.name,extractionMethod='pure')
            pose['rotations']['head']=[10.,2.,3.]
            self.assertIs(remember_history(folder,pose,{'personId':p['id'],'personKey':identity(p)},lambda *_:None),pose)
            atomic_json(Path(d)/'data/settings.json',dict(extractionMethod='smart'))
            with patch('retarget.retarget',side_effect=AssertionError('Fitted channels must be restored directly')):
                self.assertEqual(restore_history(Path(d),folder,[p],'g9'),dict(poses=[pose]))
            self.assertEqual(restore_history(Path(d),folder,[dict(p,detector='different')],'g9'),dict(poses=[pose],detached=True))

    def test_history_restores_legacy_solo_and_latest_group_or_refinement(self):
        with self.directory() as d:
            folder=Path(d)/'reference';a=person();b=dict(a,id=2)
            _,one=fixture(a['id'],0);_,two=fixture(b['id'],1)
            one['imageId']=two['imageId']=folder.name
            anchor=folder/'posture-baselines'/'legacy.json'
            atomic_json(anchor,dict(version=1,id='legacy',kind='extraction',poses=[one]))
            os.utime(anchor,ns=(1_000_000_000,1_000_000_000))
            restored=restore_history(Path(d),folder,[a,b],'g9')
            self.assertEqual(restored['poses'][0]['postureBaseline']['id'],'legacy')
            for pose in (one,two):
                pose['layout']=dict(version=3,reference=True,id='layout',personIds=[a['id'],b['id']])
            group=result_path(folder,'interaction','smart')
            atomic_json(group,dict(id='layout',version=3,poses=[one,two],contacts=[]))
            os.utime(group,ns=(2_000_000_000,2_000_000_000))
            self.assertEqual(restore_history(Path(d),folder,[a,b],'g9')['poses'],[one,two])
            refined=result_path(folder,'refinement','pure')
            atomic_json(refined,dict(id='refined',version=3,poses=[one,two],contacts=[],refinementSources=['private']))
            self.assertTrue(restore_history(Path(d),folder,[a,b],'g9')['refined'])
            self.assertNotIn('refinementSources',restore_history(Path(d),folder,[a,b],'g9')['result'])

    def test_source_only_history_recovers_without_running_inference(self):
        with self.directory() as d:
            folder=Path(d)/'reference';p=person();source,pose=fixture(p['id'],0)
            source.update(imageId=folder.name,personKey=identity(p))
            pose['imageId']=folder.name
            atomic_json(source_path(folder,p),source)
            with patch('retarget.retarget',return_value=pose) as cpu:
                self.assertEqual(restore_history(Path(d),folder,[p],'g8m'),dict(poses=[pose]))
            self.assertEqual(cpu.call_count,1)

    def test_explicit_choice_overrides_saved_setting_and_invalid_input_is_rejected(self):
        with self.directory() as d:
            root=Path(d);atomic_json(root/'data/settings.json',dict(extractionMethod='pure'))
            self.assertEqual(selected(root,{}),'pure');self.assertEqual(selected(root,dict(extractionMethod='smart')),'smart')
            with self.assertRaises(ValueError):method('standard')
    def test_auto_resolves_single_person_and_interaction_operations(self):
        with self.directory() as d:
            root=Path(d)
            self.assertEqual(selected(root,{}),'pure')
            self.assertEqual(selected(root,{},interaction=True),'smart')
            self.assertEqual(selected(root,dict(extractionMethod='auto',extractionContext='interaction')),'smart')
            for context in (False,True):
                self.assertEqual(selected(root,dict(extractionMethod='pure'),interaction=context),'pure')
                self.assertEqual(selected(root,dict(extractionMethod='smart'),interaction=context),'smart')
            with self.assertRaises(ValueError):selected(root,dict(extractionContext='crowd'))
            with self.assertRaises(ValueError):result_path(root,'interaction','auto')
    def test_sources_and_accepted_results_are_partitioned_without_reusing_unverified_legacy(self):
        with self.directory() as d:
            root=Path(d);p=person();base=dict(version=3,personKey=identity(p))
            atomic_json(root/'solve-1.json',dict(version=1))
            self.assertIsNone(cached_source(root,p,'pure'))
            smart=dict(base,extractionMethod='smart');pure=dict(base,extractionMethod='pure',pureVersion=PURE_VERSION)
            atomic_json(source_path(root,p),smart);atomic_json(source_path(root,p,'pure'),pure)
            self.assertEqual(cached_source(root,p),smart);self.assertEqual(cached_source(root,p,'pure'),pure)
            self.assertNotEqual(source_signature(pure),source_signature(smart))
            atomic_json(result_path(root,'refinement','smart'),dict(previous=True))
            self.assertIsNone(accepted_result(root,root,choice='pure'))
            pure['pureVersion']=0;atomic_json(source_path(root,p,'pure'),pure)
            self.assertIsNone(cached_source(root,p,'pure'))
    def test_pure_cache_fingerprints_changed_weights(self):
        with self.directory() as d:
            root=Path(d);initial=pure_signature(root);path=root/'models/body/model.ckpt';path.parent.mkdir(parents=True);path.write_bytes(b'weights')
            self.assertNotEqual(initial,pure_signature(root))
    def test_pure_can_use_its_cache_without_loading_independent_models(self):
        with self.directory() as d:
            root=Path(d);p=person();source=dict(version=3,personKey=identity(p),extractionMethod='pure',pureVersion=PURE_VERSION,refinementSignature=pure_signature(root))
            atomic_json(root/'people.json',[p]);atomic_json(source_path(root,p,'pure'),source)
            with patch('inference.image_dir',return_value=root),patch('wholebody.available',return_value=False),patch('wholebody.Landmarker') as measurement,patch('refinement.refine_sources') as refine:
                result=Inference(root).solve(dict(imageId='test',personId=1,extractionMethod='pure'),lambda *_:None)
                self.assertEqual({k:result[k] for k in source},source);self.assertFalse(result['referenceEvidence']['applied']);self.assertEqual(result['sourceGuidance']['id'],'original');measurement.assert_not_called();refine.assert_not_called()
                with self.assertRaisesRegex(ValueError,'Smart Fit models are missing'):Inference(root).solve(dict(imageId='test',personId=1,extractionMethod='smart'),lambda *_:None)
    def test_pure_pose_provenance_and_camera_do_not_change_channels(self):
        source,pose=fixture(1,0);source.update(extractionMethod='pure',quality=dict(detection=.9,visible=dict(matched=1,count=9)))
        before=copy.deepcopy(pose);result=extraction_pose(source,pose)
        self.assertEqual(result['rotations'],before['rotations']);self.assertEqual(result['translation'],before['translation'])
        self.assertEqual(result['extractionMethod'],'pure');self.assertEqual(result['quality']['stage'],'source');self.assertEqual(result['referenceCamera']['intrinsics'],source['camera'])
    def test_pure_contact_placement_never_refits_limbs(self):
        a,pa=fixture(1,-.12);b,pb=fixture(2,.12)
        pa['rotations']['lForearmBend']=[12,0,0];pb['rotations']['rHand']=[0,20,0]
        before=copy.deepcopy([pa,pb]);contacts=[dict(person=0,other=1,wrist=9,node='lHand',weight=1.)]
        with patch('interaction.source_contacts',return_value=contacts):result=coordinate([a,b],[pa,pb],fit_arms=False)
        self.assertEqual([pa,pb],before);self.assertEqual([p['rotations'] for p in result['poses']],[p['rotations'] for p in before])
        self.assertEqual(result['diagnostics']['armAdjustments'],0);self.assertEqual(result['poses'][0]['referenceCamera'],result['poses'][1]['referenceCamera'])
    def test_pure_refinement_reads_only_the_pure_source_even_when_smart_is_selected(self):
        source,pose=fixture(1,0);source['extractionMethod']='pure';pose['extractionMethod']='pure'
        with self.directory() as d:
            root=Path(d);atomic_json(root/'people.json',[dict(id=1)])
            atomic_json(result_path(root,'refinement','pure'),dict(poses=[pose],refinementSources=[source],sourceSignatures={1:source_signature(source)}))
            with patch('refinement.cached_source',return_value=source) as cache,patch('rigs.profile',return_value=pose['rig']):
                self.assertIsNotNone(accepted_result(root,root,choice='pure'));self.assertEqual(cache.call_args.args[-1],'pure')
                self.assertIsNone(accepted_result(root,root,choice='smart'))
    def test_explicit_pure_preview_apply_keeps_smart_history_and_fused_source(self):
        from refinement import refine
        from measurements import reference_camera
        from posture import persist_baseline
        from wholebody import signature
        source,pose=fixture(1,0);source.update(extractionMethod='pure',pureVersion=PURE_VERSION,refinementSignature='sam-only')
        pose.update(extractionMethod='pure',referenceCamera=reference_camera(source,[0,0,0]))
        with self.directory() as d:
            root=Path(d);atomic_json(root/'people.json',[dict(id=1)]);atomic_json(root/'data/settings.json',dict(extractionMethod='smart'))
            atomic_json(root/'refinement.json',dict(previousSmart=True));before=(root/'refinement.json').read_bytes();persist_baseline(root,[source],[pose])
            source_before=copy.deepcopy(source)
            payload=dict(version=2,policyVersion=1,imageId='same',currentPoses=[pose],action='preview')
            def fitted(sources,current,*_,**kwargs):
                result=copy.deepcopy(current);result[0]['rotations']['lHand']=[5,0,0]
                return dict(version=3,poses=result,diagnostics=dict(accepted=True),imageId='same')
            with patch('refinement.image_dir',return_value=root),patch('editor.checked_poses'),patch('refinement.cached_source',return_value=source) as cache,patch('rigs.profile',return_value=pose['rig']),patch('wholebody.Landmarker.measure',return_value=[]),patch('coupled.fit_targets',side_effect=fitted),patch('PIL.Image.open') as image:
                image.return_value.convert.return_value=np.zeros((20,20,3),dtype=np.uint8)
                preview=refine(root,payload,lambda *_:None)
                self.assertEqual(cache.call_args.args[-1],'pure');self.assertEqual(source,source_before)
                self.assertEqual((root/'refinement.json').read_bytes(),before);self.assertFalse((root/'refinement-pure.json').exists())
                result=refine(root,dict(payload,action='apply',previewId=preview['previewId']),lambda *_:None)
                self.assertEqual(result['poses'][0]['extractionMethod'],'pure');self.assertTrue((root/'refinement-pure.json').exists());self.assertEqual((root/'refinement.json').read_bytes(),before)

if __name__=='__main__':unittest.main()
