import copy,json,tempfile,unittest
from pathlib import Path
import numpy as np
from unittest.mock import patch
from spacing import torso_surface,fit,torso_samples
from textpose import neutral,frame
from studio import semantics
from storage import atomic_json

ROOT=Path(__file__).resolve().parents[1]


class SpacingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'temp');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        atomic_json(self.root/'data/rigs/g9.json',json.loads((ROOT/'tests/fixtures/target-fit/g9.json').read_text()))

    def pair(self):
        poses=[neutral(self.root,'g9','pose-'+'0'*32,i+1) for i in range(2)]
        camera=dict(version=1,intrinsics=[[800,0,400],[0,800,400],[0,0,1]],imageSize=[800,800],originCm=[0,-90,-500])
        for i,p in enumerate(poses):p['translation'][0]=(-25 if i==0 else 25);p['referenceCamera']=copy.deepcopy(camera)
        samples=[]
        from measurements import target_points,project_target
        for i,p in enumerate(poses):
            points,_=target_points(p);center=project_target(points['torso'],camera)
            xy=np.array([center+[x,y] for x in np.linspace(-12,12,8) for y in np.linspace(-15,15,8)])
            truth=copy.deepcopy(p);truth['translation'][2]+=12 if i==0 else -12
            depth=torso_surface(truth,xy)
            self.assertTrue(np.isfinite(depth).all())
            samples.append(dict(xy=xy,depthCm=depth))
        return poses,samples

    def test_bounded_relative_surface_fit_preserves_raw_rig_and_floor(self):
        poses,samples=self.pair();original=copy.deepcopy(poses);result,d=fit(poses,samples)
        self.assertEqual(poses,original);self.assertTrue(d['changed']);self.assertLess(d['afterResidualCm'],d['beforeResidualCm']*.8)
        for before,after in zip(original,result):
            for key in ('rig','rotations','rootRotation'):self.assertEqual(before[key],after[key])
            self.assertEqual(before['translation'][:2],after['translation'][:2]);self.assertLessEqual(abs(before['translation'][2]-after['translation'][2]),25.)

    def test_conflicting_pins_and_confirmed_contacts_keep_layout(self):
        poses,samples=self.pair();original=copy.deepcopy(poses)
        contacts=[dict(enabled=True,confirmed=True,personId=1,otherId=2)]
        result,d=fit(poses,samples,contacts);self.assertFalse(d['changed']);self.assertEqual(result,original)
        for p in poses:
            name=semantics(p['rig'])['r_hand'];p['pins']={name:dict(position=frame(p)[1][name].tolist())}
        result,d=fit(poses,samples);self.assertFalse(d['changed']);self.assertEqual(result,poses)

    def test_boundary_background_and_other_actor_samples_are_excluded(self):
        person=dict(keypoints=[[0,0,0] for _ in range(17)])
        for i,xy in zip((5,6,11,12),((25,20),(75,20),(30,80),(70,80))):person['keypoints'][i]=[*xy,.95]
        depth=np.full((100,100),2.,np.float32);mask=np.zeros((100,100),bool);mask[15:85,20:80]=True
        depth[~mask]=100.;other=np.zeros_like(mask);other[:,60:]=True
        value=torso_samples(person,mask,[other],depth,np.ones_like(mask),[100,100])
        self.assertTrue(np.all(value['depthCm']==200));self.assertTrue(np.all(value['xy'][:,0]<57))
        with self.assertRaises(ValueError):torso_samples(person,mask,[mask],depth,np.ones_like(mask),[100,100])

    def transaction_fixture(self):
        from PIL import Image
        from camera_depth import save
        poses,samples=self.pair();image_id='a'*24
        folder=self.root/'data/history'/image_id;folder.mkdir(parents=True)
        image=np.zeros((800,800,3),np.uint8);Image.fromarray(image).save(folder/'source.png')
        people=[dict(id=i+1,box=[0,0,800,800],keypoints=[]) for i in range(2)]
        atomic_json(folder/'people.json',people)
        for pose in poses:pose.update(imageId=image_id,origin=None)
        save(self.root,folder,image,poses[0]['referenceCamera']['intrinsics'],np.full((800,800),5.,np.float32),np.ones((800,800),bool))
        payload=dict(imageId=image_id,currentPoses=poses,contacts=[],action='preview')
        return folder,payload,samples

    def test_preview_cancel_apply_and_stale_evidence_are_transactional(self):
        from spacing import transaction
        from storage import read_json
        folder,payload,samples=self.transaction_fixture();original=copy.deepcopy(payload)
        # This transaction test supplies independently controlled observations;
        # extraction/segmentation accuracy is deliberately outside its scope.
        with patch('editor.checked_poses',return_value=(folder,['one','two'])),patch('segmentation.selected_mask',return_value=np.ones((1,800,800,1),np.uint8)):
            with patch('spacing.torso_samples',side_effect=samples):preview=transaction(self.root,payload,lambda *_:None)
            self.assertTrue(preview['diagnostics']['spacing']['changed'])
            self.assertFalse((folder/'editor-draft.json').exists());self.assertFalse((folder/'spacing.json').exists())
            self.assertEqual(payload,original)
            self.assertTrue(transaction(self.root,dict(payload,action='cancel',previewId=preview['previewId']),lambda *_:None)['cancelled'])
            with self.assertRaisesRegex(ValueError,'expired'):
                transaction(self.root,dict(payload,action='apply',previewId=preview['previewId']),lambda *_:None)
            with patch('spacing.torso_samples',side_effect=samples):preview=transaction(self.root,payload,lambda *_:None)
            changed=copy.deepcopy(payload);changed['currentPoses'][0]['translation'][0]+=.1
            with self.assertRaisesRegex(ValueError,'evidence changed'):
                transaction(self.root,dict(changed,action='apply',previewId=preview['previewId']),lambda *_:None)
            changed=copy.deepcopy(payload);changed['currentPoses'][0]['pins']={'l_hand':dict(position=[0.,0.,0.])}
            with self.assertRaisesRegex(ValueError,'evidence changed'):
                transaction(self.root,dict(changed,action='apply',previewId=preview['previewId']),lambda *_:None)
            self.assertFalse((folder/'editor-draft.json').exists())
            result=transaction(self.root,dict(payload,action='apply',previewId=preview['previewId']),lambda *_:None)
            self.assertEqual(read_json(folder/'editor-draft.json')['poses'],result['poses'])
            self.assertEqual(read_json(folder/'editor-draft.json')['spacing'],result)
            for before,after in zip(payload['currentPoses'],result['poses']):
                self.assertEqual(before['rig'],after['rig']);self.assertEqual(before['rotations'],after['rotations'])

    def test_failed_apply_keeps_the_prior_draft_and_retryable_preview(self):
        from spacing import transaction
        from storage import atomic_json,read_json
        folder,payload,samples=self.transaction_fixture()
        accepted=dict(version=1,poses=copy.deepcopy(payload['currentPoses']))
        atomic_json(folder/'editor-draft.json',accepted)
        with patch('editor.checked_poses',return_value=(folder,['one','two'])),patch('segmentation.selected_mask',return_value=np.ones((1,800,800,1),np.uint8)):
            with patch('spacing.torso_samples',side_effect=samples):preview=transaction(self.root,payload,lambda *_:None)
            with patch('spacing.atomic_json',side_effect=OSError('Disk unavailable')):
                with self.assertRaises(OSError):transaction(self.root,dict(payload,action='apply',previewId=preview['previewId']),lambda *_:None)
            self.assertEqual(read_json(folder/'editor-draft.json'),accepted)
            self.assertTrue((self.root/'temp/spacing-previews'/(preview['previewId']+'.json')).exists())
            result=transaction(self.root,dict(payload,action='apply',previewId=preview['previewId']),lambda *_:None)
            self.assertEqual(read_json(folder/'editor-draft.json')['spacing'],result)

    def test_changed_mask_or_depth_cannot_apply_an_old_preview(self):
        from spacing import transaction
        from instances import identity
        from storage import read_json
        folder,payload,samples=self.transaction_fixture()
        with patch('editor.checked_poses',return_value=(folder,['one','two'])),patch('segmentation.selected_mask',return_value=np.ones((1,800,800,1),np.uint8)):
            with patch('spacing.torso_samples',side_effect=samples):preview=transaction(self.root,payload,lambda *_:None)
            person=read_json(folder/'people.json')[0]
            (folder/('mask-'+identity(person)+'.json')).write_text('{}')
            with self.assertRaisesRegex(ValueError,'evidence changed'):
                transaction(self.root,dict(payload,action='apply',previewId=preview['previewId']),lambda *_:None)
            with patch('spacing.torso_samples',side_effect=samples):preview=transaction(self.root,payload,lambda *_:None)
            (folder/'camera-depth.npz').write_bytes(b'incomplete')
            with self.assertRaisesRegex(ValueError,'evidence changed'):
                transaction(self.root,dict(payload,action='apply',previewId=preview['previewId']),lambda *_:None)
            self.assertFalse((folder/'editor-draft.json').exists())


if __name__=='__main__':unittest.main()
