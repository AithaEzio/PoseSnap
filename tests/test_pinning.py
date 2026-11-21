import copy, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from scipy.spatial.transform import Rotation
from daz import validate_pose, duf
from editor import new_pose, operation, reach
from studio import convert_pose
from retarget import fk
from test_interaction import fixture
from test_studio import target_rig

def pin(pose,bone,position=True,rotation=True):
    root=next(n['id'] for n in pose['rig']['nodes'] if not n['parent'])
    frames,positions=fk(pose['rig'],{**pose['rotations'],root:pose.get('rootRotation',[0,0,0])},pose['translation'])
    value={}
    if position:value['position']=positions[bone].tolist()
    if rotation:value['rotation']=Rotation.from_matrix(frames[bone]).as_quat().tolist()
    pose.setdefault('pins',{})[bone]=value
    return pose

class PinningTests(unittest.TestCase):
    def test_pin_targets_survive_portable_draft_and_do_not_add_export_channels(self):
        _,original=fixture(1,0)
        with tempfile.TemporaryDirectory() as folder,patch('editor.profile',return_value=original['rig']):
            root=Path(folder);pose=pin(new_pose(root,'g8m'),'lHand')
            operation(root,dict(editorOperation='save_draft',imageId=pose['imageId'],poses=[pose]),lambda *_:None)
            loaded=operation(root,dict(editorOperation='load_draft',imageId=pose['imageId']),lambda *_:None)['poses'][0]
            self.assertEqual(loaded['pins'],pose['pins'])
            without=copy.deepcopy(pose);without.pop('pins')
            self.assertEqual(duf(pose,'floor'),duf(without,'floor'))
    def test_pin_metadata_rejects_unknown_bones_nonfinite_targets_and_invalid_quaternions(self):
        _,pose=fixture(1,0)
        for value in ([],{'missing':{'position':[0,0,0]}},{'lHand':{}},{'lHand':{'position':[0,1,float('nan')]}},{'lHand':{'rotation':[0,0,0,2]}},{'lHand':{'position':[True,0,0]}},{'lHand':{'mode':'on'}}):
            with self.subTest(value=value),self.assertRaises(ValueError):validate_pose(dict(pose,pins=value))
    def test_direct_reach_requires_unpinning_position_and_preserves_other_pins(self):
        _,pose=fixture(1,0);pose=pin(pose,'lHand')
        with self.assertRaisesRegex(ValueError,'Unpin Position'):reach(pose,'lHand',[0,0,0])
        pose=pin(pose,'rFoot');del pose['pins']['lHand']['position']
        _,positions=fk(pose['rig'],pose['rotations'],pose['translation']);target=positions['lHand']+[-1,.3,1]
        fitted=reach(pose,'lHand',target)
        self.assertEqual(fitted['pose']['pins'],pose['pins'])
        frames,positions=fk(pose['rig'],fitted['pose']['rotations'],pose['translation'])
        angle=np.degrees(Rotation.from_matrix(frames['lHand']@Rotation.from_quat(pose['pins']['lHand']['rotation']).as_matrix().T).magnitude())
        self.assertLess(angle,2)
        self.assertLess(np.linalg.norm(positions['rFoot']-pose['pins']['rFoot']['position']),1e-7)
    def test_generation_conversion_recaptures_semantic_pins_without_changing_target_rig(self):
        _,pose=fixture(1,0);pose=pin(pose,'lHand');target=target_rig();before=copy.deepcopy(target)
        converted=convert_pose(pose,target);validate_pose(converted)
        self.assertEqual(target,before);self.assertEqual(set(converted['pins']),{'l_hand'})
        root=next(n['id'] for n in target['nodes'] if not n['parent'])
        frames,positions=fk(target,{**converted['rotations'],root:converted['rootRotation']},converted['translation'])
        np.testing.assert_allclose(converted['pins']['l_hand']['position'],positions['l_hand'])
        self.assertTrue(any('pins recaptured' in warning for warning in converted['warnings']))
