"""Per-reference metric encoding and transaction preservation."""
import json,sys,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'worker'))
from storage import import_image,image_dir,read_json,atomic_json
from reference_depth import settings,calibrated
from reference_guidance import provided_depth, measurements
def calibration(width, height):
    return dict(version=2, projection='perspective', imageSize=[width,height],
                intrinsics=[[30.,0.,width/2],[0.,30.,height/2],[0.,0.,1.]],
                worldToCamera=np.eye(4).tolist(), metricScale=True, provenance='calibrated', locked=True)


class ReferenceDepthTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        (self.root/'data/history').mkdir(parents=True)
        self.source=self.root/'depth.tiff';Image.fromarray(np.full((24,32),1000,dtype=np.float32)).save(self.source)
        self.image=import_image(self.root,dict(path=str(self.source),kind='metric-depth'));self.folder=image_dir(self.root,self.image['id'])
        self.camera=calibration(32,24)
        self.path=self.root/'camera.json';self.path.write_text(json.dumps(self.camera))
    def apply(self,**kwargs):return settings(self.root,dict(imageId=self.image['id'],**kwargs))
    def test_units_do_not_invent_calibration(self):
        self.apply(scaleCm=.1,encoding='camera-z')
        with self.assertRaisesRegex(ValueError,'calibration'):calibrated(read_json(self.folder/'image.json'))
    def test_rejected_values_preserve_reference_metadata(self):
        before=(self.folder/'image.json').read_bytes()
        for scale in (True,0,-1,float('nan'),float('inf'),'1'):
            with self.assertRaises(ValueError):self.apply(scaleCm=scale)
        self.assertEqual(before,(self.folder/'image.json').read_bytes())
    def test_calibration_must_match_input_dimensions(self):
        wrong=calibration(64,48);self.path.write_text(json.dumps(wrong))
        with self.assertRaisesRegex(ValueError,'dimensions'):self.apply(calibrationPath=str(self.path))
    def test_read_restores_explicit_units_and_accepted_history_is_kept(self):
        accepted=self.root/'data/history/accepted.json';accepted.write_text('preserved')
        self.apply(scaleCm=.1,encoding='camera-z',calibrationPath=str(self.path))
        self.assertEqual(self.apply()['scaleCm'],.1);self.assertEqual(accepted.read_text(),'preserved')
        self.assertEqual(calibrated(read_json(self.folder/'image.json'))['camera']['imageSize'],[32,24])
    def test_ray_depth_surface_sample_requires_person_ownership(self):
        orthographic = self.root/'orthographic.json'
        orthographic.write_text(json.dumps(dict(self.camera, projection='orthographic')))
        with self.assertRaisesRegex(ValueError, 'perspective'):
            self.apply(scaleCm=.1, encoding='ray-distance', calibrationPath=str(orthographic))
        self.apply(scaleCm=.1, encoding='ray-distance', calibrationPath=str(self.path))
        point = dict(name='l_wrist', known=True, xy=[16,12])
        args = (self.root, self.image['id'], [point], 'person', 'detailed')
        unowned, _, _ = measurements(*args)
        self.assertNotIn('depthSurfaceValue', unowned[0])
        with patch('reference_guidance.owned_mask', return_value=np.ones((24,32), dtype=bool)):
            owned, _, _ = measurements(*args)
        self.assertEqual(owned[0]['depthConvention'], 'camera-z')
        self.assertEqual(owned[0]['depthScaleCm'], .1)
        expected = np.median([1000./np.sqrt(1+((x-16)/30)**2+((y-12)/30)**2)
                              for y in range(11,14) for x in range(15,18)])
        self.assertAlmostEqual(owned[0]['depthSurfaceValue'], expected, places=6)

    def test_retired_import_and_studio_records_stay_out_of_history(self):
        from editor import pose_history
        from storage import history, trim_history
        retired = image_dir(self.root,'a'*24)
        retired.mkdir()
        marker = retired/'image.json'
        atomic_json(marker,dict(id='a'*24,created=0,multiviewAsset='retired-asset'))
        (retired/'thumb.jpg').write_bytes(b'legacy')
        draft = self.root/'data/poses'/('pose-'+'f'*32)/'editor-draft.json'
        atomic_json(draft,dict(version=1,poses=[dict(origin='editor',multiViewSource={'version':1})]))
        self.assertEqual([row['id'] for row in history(self.root)],[self.image['id']])
        self.assertEqual(pose_history(self.root),[])
        trim_history(self.root,keep=self.image['id'])
        self.assertTrue(marker.is_file())
        self.assertTrue(draft.is_file())

    def test_ray_distance_converts_to_camera_z(self):
        self.apply(scaleCm=.1,encoding='ray-distance',calibrationPath=str(self.path))
        result=provided_depth(self.root,self.image['id'])
        k=np.array(self.camera['intrinsics']);ray=np.linalg.inv(k)@np.array([0.,0.,1.]);expected=1000/np.linalg.norm(ray)
        self.assertAlmostEqual(float(result['values'][0,0]),float(expected),places=3)
        self.assertEqual(float(np.asarray(Image.open(self.source))[0,0]),1000.)
