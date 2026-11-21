import copy, unittest, tempfile
from pathlib import Path
from unittest.mock import patch
import numpy as np
from test_interaction import fixture
from editor import reach, checked_poses, new_pose, operation, pose_history, session_folder, same_profile
from storage import atomic_json
from daz import duf
from retarget import fk

class EditorTests(unittest.TestCase):
    def test_profile_rounding_noise_is_not_a_reconnection(self):
        _,pose=fixture(1,0);transport=copy.deepcopy(pose['rig']);transport['nodes'][1]['center'][0]+=1e-13
        self.assertTrue(same_profile(transport,pose['rig']))
        with patch('editor.profile',return_value=pose['rig']):checked_poses(Path('temp'),'pose-'+'0'*32,[{**pose,'origin':'editor','imageId':'pose-'+'0'*32,'rig':transport}])
        for field in ('center','orientation'):
            changed=copy.deepcopy(pose['rig']);changed['nodes'][1][field][0]+=.0001
            self.assertFalse(same_profile(changed,pose['rig']))
        changed=copy.deepcopy(pose['rig']);changed['nodes'][1]['order']='ZYX';self.assertFalse(same_profile(changed,pose['rig']))
    def test_photo_editor_draft_has_its_own_history_entry(self):
        _,pose=fixture(1,0);image_id='a'*24;pose['imageId']=image_id
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);atomic_json(root/'data/history'/image_id/'editor-draft.json',dict(version=1,imageId=image_id,poses=[pose]))
            reference=dict(id=image_id,name='Hug.png',thumbnail='local-thumb',created=1,solved=True)
            rows=pose_history(root,[reference]);self.assertEqual(len(rows),1);self.assertEqual(rows[0]['kind'],'pose');self.assertEqual(rows[0]['id'],image_id);self.assertEqual(rows[0]['thumbnail'],'local-thumb');self.assertNotIn('kind',reference)
    def test_new_pose_resets_every_supported_bone_and_exports_without_a_photo(self):
        _,original=fixture(1,0)
        for rig_id in ('g8f','g8m','g9'):
            rig=copy.deepcopy(original['rig']);rig['id']=rig_id;before=copy.deepcopy(rig)
            with tempfile.TemporaryDirectory() as folder,patch('editor.profile',return_value=rig):
                root=Path(folder);pose=new_pose(root,rig_id)
                self.assertEqual(pose['origin'],'editor');self.assertNotIn('quality',pose);self.assertFalse(pose['handRefinement'])
                self.assertEqual(set(pose['rotations']),{n['id'] for n in rig['nodes'] if n['type']=='bone'})
                self.assertTrue(all(v==[0,0,0] for v in pose['rotations'].values()));self.assertEqual(rig,before)
                self.assertTrue(duf(pose,'floor')['scene']['animations']);self.assertFalse((root/'data/history').exists())
                self.assertEqual(checked_poses(root,pose['imageId'],[pose])[0],root/'data/poses'/pose['imageId'])
    def test_manual_draft_roundtrip_history_and_reach(self):
        _,original=fixture(1,0)
        with tempfile.TemporaryDirectory() as folder,patch('editor.profile',return_value=original['rig']):
            root=Path(folder);pose=new_pose(root,'g8m');pose['rotations']['lHand']=[10,20,30]
            progress=lambda *_:None
            operation(root,dict(editorOperation='save_draft',imageId=pose['imageId'],poses=[pose]),progress)
            saved=operation(root,dict(editorOperation='load_draft',imageId=pose['imageId']),progress)
            self.assertEqual(saved['poses'],[pose]);self.assertEqual(pose_history(root)[0]['kind'],'pose')
            target=fk(pose['rig'],pose['rotations'])[1]['lHand']+[-2,1,2]
            fitted=operation(root,dict(editorOperation='reach',pose=pose,poses=[pose],bone='lHand',target=target.tolist()),progress)
            self.assertLess(fitted['distanceCm'],.5)
    def test_manual_session_rejects_invalid_paths_and_changed_rig(self):
        _,original=fixture(1,0)
        with tempfile.TemporaryDirectory() as folder,patch('editor.profile',return_value=original['rig']):
            root=Path(folder);pose=new_pose(root,'g8m')
            for value in ('../outside','pose-../../outside','pose-'+'0'*31):
                with self.assertRaises(ValueError):session_folder(root,value)
            changed=copy.deepcopy(pose);changed['rig']['nodes'][1]['center'][0]+=1
            with self.assertRaises(ValueError):checked_poses(root,pose['imageId'],[changed])
            with self.assertRaises(ValueError):checked_poses(root,pose['imageId'],[{**pose,'personId':2}])
    def test_reach_fits_rotations_without_changing_rig_or_root(self):
        _,pose=fixture(1,0);before=copy.deepcopy(pose);target=fk(pose['rig'],pose['rotations'])[1]['lHand']+[-3,3,4]
        result=reach(pose,'lHand',target)
        self.assertLess(result['distanceCm'],.5);self.assertTrue(result['reached'])
        self.assertEqual(result['pose']['rig'],before['rig']);self.assertEqual(result['pose']['translation'],before['translation']);self.assertEqual(pose,before)
    def test_unreachable_target_reports_residual_and_respects_limits_locks(self):
        _,pose=fixture(1,0)
        for n in pose['rig']['nodes']:
            if n['id'] in ('lShldrBend','lForearmBend'):
                n['limits']={'x':dict(min=-5,max=5,clamped=True),'y':dict(min=-180,max=180,clamped=False,locked=True),'z':dict(min=-180,max=180,clamped=False)};n['driven']=['z']
        result=reach(pose,'lHand',[1000,1000,1000]);self.assertFalse(result['reached']);self.assertGreater(result['distanceCm'],100)
        for name in ('lShldrBend','lForearmBend'):
            self.assertLessEqual(abs(result['pose']['rotations'][name][0]),5.000001);self.assertEqual(result['pose']['rotations'][name][1:], [0,0])
    def test_invalid_or_unsupported_reach_is_rejected(self):
        _,pose=fixture(1,0)
        for target in ([np.nan,0,0],[0,0]):
            with self.assertRaises(ValueError):reach(pose,'lHand',target)
        with self.assertRaises(ValueError):reach(pose,'hip',[0,0,0])
    def test_edited_duf_uses_same_position_and_rotation_channels(self):
        _,pose=fixture(1,0);pose['translation']=[12,3,-9];pose['rootRotation']=[10,20,30];pose['rotations']['lHand']=[11,22,33];pose['edited']=True
        rows=duf(pose,'floor')['scene']['animations'];actual={r['url']:r['keys'][0][1] for r in rows}
        for axis,value in zip('xyz',pose['translation']):self.assertEqual(next(v for k,v in actual.items() if k.endswith('translation/'+axis+'/value')),value)
    def test_draft_rejects_changed_rig_and_changed_extraction(self):
        _,pose=fixture(1,0);person={'id':1,'box':[0,0,100,200],'score':.9}
        with patch('editor.image_dir',return_value=__import__('pathlib').Path('temp')),patch('editor.read_json',return_value=[person]),patch('editor.identity',return_value='key'),patch('editor.profile',return_value=pose['rig']),patch('editor.cached_source',return_value={'version':2}):
            self.assertEqual(checked_poses(None,'same',[pose])[1],['key'])
            changed=copy.deepcopy(pose);changed['rig']['nodes'][1]['center'][0]+=1
            with self.assertRaises(ValueError):checked_poses(None,'same',[changed])
            with patch('editor.cached_source',return_value=None):
                with self.assertRaises(ValueError):checked_poses(None,'same',[pose])
    def test_group_draft_requires_all_layout_participants(self):
        _,pose=fixture(1,0);pose['layout']=dict(version=1,id='group',personIds=[1,2],reference=True);person={'id':1}
        with patch('editor.image_dir',return_value=__import__('pathlib').Path('temp')),patch('editor.read_json',return_value=[person]),patch('editor.identity',return_value='key'),patch('editor.profile',return_value=pose['rig']),patch('editor.cached_source',return_value={'version':2}):
            with self.assertRaises(ValueError):checked_poses(None,'same',[pose])

if __name__=='__main__':unittest.main()
