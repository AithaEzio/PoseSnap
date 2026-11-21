import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
import numpy as np
from body_uncertainty import BodyPriorDiagnostic,regional_summaries,note,region,region_owners,enabled,HEAD
from camera_depth import save,load,sample


class BodyDiagnosticTests(unittest.TestCase):
    def setUp(self):
        folder=Path(__file__).resolve().parents[1]/'temp';folder.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=folder);self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

    def test_missing_optional_head_does_not_load_or_mutate_model(self):
        from storage import atomic_json
        atomic_json(self.root/'data/settings.json',dict(clueEnabled=True))
        model=Mock();value=BodyPriorDiagnostic(self.root,model,self.root,dict(id=1),'source',[0,0,100,100])
        value.capture();value.close();value.close()
        self.assertIsNone(value.result);self.assertIsNone(value.error);model.assert_not_called()

    def test_disabled_diagnostics_skip_even_an_installed_invalid_head_without_model_access(self):
        from storage import atomic_json
        self.assertFalse(enabled(self.root))
        path=self.root/HEAD;path.parent.mkdir(parents=True);path.write_bytes(b'invalid head must not be read or loaded')
        for preference in ({},dict(clueEnabled=False)):
            atomic_json(self.root/'data/settings.json',preference)
            model=Mock();value=BodyPriorDiagnostic(self.root,model,self.root,dict(id=1),'source',[0,0,100,100])
            value.capture();value.close()
            self.assertFalse(enabled(self.root));self.assertIsNone(value.result);self.assertIsNone(value.error)
            self.assertEqual(model.mock_calls,[])

    def test_toggle_invalidates_derived_sources_without_changing_history_or_unrelated_preferences(self):
        from storage import atomic_json
        from cache_provenance import provenance
        saved=self.root/'data/history/accepted.json';atomic_json(saved,dict(rotations=[1,2,3],notes=['kept']))
        before=saved.read_bytes();original=provenance(self.root)
        atomic_json(self.root/'data/settings.json',dict(clueEnabled=False,theme='dark'))
        off=provenance(self.root);self.assertEqual(original,off)
        atomic_json(self.root/'data/settings.json',dict(clueEnabled=False,theme='light'))
        self.assertEqual(off,provenance(self.root))
        atomic_json(self.root/'data/settings.json',dict(clueEnabled=True))
        self.assertNotEqual(original,provenance(self.root));self.assertTrue(enabled(self.root));self.assertEqual(saved.read_bytes(),before)

    def test_actual_mhr_joint_names_map_to_review_regions(self):
        for name,expected in [('root','torso'),('c_spine3','torso'),('c_head','head'),('c_neck','head'),('l_uparm','l_arm'),('r_lowarm','r_arm'),('l_upleg','l_leg'),('r_ball','r_leg'),('l_wrist',None),('c_jaw',None)]:
            self.assertEqual(region(name),expected)

    def test_static_region_cache_is_read_only_cpu_data_and_follows_the_loaded_rig(self):
        import torch
        import weakref
        model,plugin=Mock(),Mock()
        rig=Mock();rig.get_joint_names.return_value=['root','l_uparm','r_upleg']
        model.head_pose.mhr=rig
        state=plugin.uncertainty.clue.model.scripted_model.state_dict
        state.return_value={
            'character_torch.linear_blend_skinning.skin_indices_flattened':torch.tensor([0,1,2]),
            'character_torch.linear_blend_skinning.vert_indices_flattened':torch.tensor([0,1,2]),
            'character_torch.linear_blend_skinning.skin_weights_flattened':torch.ones(3)}
        owners=region_owners(model,plugin)
        self.assertEqual(owners[:3].tolist(),['torso','l_arm','r_leg'])
        self.assertIs(region_owners(model,plugin),owners);state.assert_called_once()
        self.assertIsInstance(model.__dict__['_posesnap_clue_regions'][0],weakref.ReferenceType)
        self.assertFalse(owners.flags.writeable)
        with self.assertRaises(ValueError):owners[0]='head'
        replacement=Mock();replacement.get_joint_names.return_value=['c_head','l_uparm','r_upleg']
        model.head_pose.mhr=replacement
        rebuilt=region_owners(model,plugin)
        self.assertEqual(rebuilt[0],'head');self.assertIsNot(rebuilt,owners)

    def test_cpu_snapshot_is_actor_owned_and_closes_hook_on_success_and_failure(self):
        import torch
        for invalid in (False,True):
            value=BodyPriorDiagnostic(self.root,None,self.root,dict(id=7,box=[1,2,3,4]),'source',[1,2,3,4])
            plugin=Mock();variance=torch.ones((1,18439,3))
            if invalid:variance[0,0,0]=float('nan')
            plugin.variance_cm2.return_value=variance;value.plugin=plugin;value.owners=np.full(18439,'torso',dtype=object)
            value.capture()
            plugin.remove.assert_called_once();self.assertIsNone(plugin._last);self.assertIsNone(value.plugin)
            if invalid:self.assertIsNone(value.result);self.assertIn('invalid',value.error)
            else:
                result=value.result;self.assertEqual(result['personId'],7);self.assertEqual(result['stage'],'sam-body-prior')
                self.assertEqual(result['sourceSignature'],'source');path=self.root/result['array']['path']
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),result['array']['sha256'])
                self.assertIn('not accuracy',note(result));self.assertNotIn('hand',result['regions'])

    def test_depth_cache_preserves_pixel_frame_dtype_validity_and_invalidation(self):
        image=np.zeros((1000,1500,3),np.uint8);depth=np.full((1000,1500),2.,np.float32);valid=np.ones_like(depth,dtype=bool)
        valid[:400,:400]=False;depth[:400,:400]=np.inf
        save(self.root,self.root,image,[[900,0,750],[0,900,500],[0,0,1]],depth,valid)
        meta,d,v=load(self.root,self.root,image)
        self.assertEqual(d.dtype,np.float32);self.assertEqual(d.shape,(512,768));self.assertEqual(meta['imageSize'],[1500,1000])
        values=sample(d,v,[[900,600],[5,5],[-1,50]],meta['imageSize'])
        self.assertEqual(values[0],2.);self.assertTrue(np.isnan(values[1:] ).all())
        changed=image.copy();changed[0,0,0]=1;self.assertIsNone(load(self.root,self.root,changed))
        (self.root/'camera-depth.npz').write_bytes(b'incomplete');self.assertIsNone(load(self.root,self.root,image))


if __name__=='__main__':unittest.main()
