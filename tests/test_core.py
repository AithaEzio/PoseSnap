import copy, json, tempfile, unittest
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from retarget import align, euler, rotation, fk, source_map
from storage import identifier
from daz import duf, application_script, connection_script
from rigs import evaluated_channels, validate_profile, profile, cache_profile

class PoseMathTests(unittest.TestCase):
    def test_noncommuting_euler_roundtrip_every_order(self):
        for order in ('XYZ','XZY','YXZ','YZX','ZXY','ZYX'):
            matrix=Rotation.from_rotvec([.46,-.7,1.2]).as_matrix()
            np.testing.assert_allclose(rotation(euler(matrix,order),order),matrix,atol=1e-12)
    def test_dson_orientation_sandwich_and_child_center(self):
        nodes=[dict(id='root',parent=None,center=[0,0,0],orientation=[0,0,0],order='XYZ'),
          dict(id='bone',parent='root',center=[0,2,0],orientation=[0,0,90],order='XYZ'),
          dict(id='tip',parent='bone',center=[0,3,0],orientation=[0,0,0],order='XYZ')]
        _,positions=fk({'nodes':nodes},{'bone':[90,0,0]},[1,0,0])
        np.testing.assert_allclose(positions['tip'],[1,3,0],atol=1e-12)
        _,positions=fk({'nodes':nodes},{'bone':[0,90,0]},[1,0,0])
        np.testing.assert_allclose(positions['tip'],[1,2,-1],atol=1e-12)
    def test_antiparallel_alignment_is_proper_rotation(self):
        matrix=align([0,1,0],[0,-1,0])
        np.testing.assert_allclose(matrix@[0,1,0],[0,-1,0],atol=1e-12)
        self.assertAlmostEqual(np.linalg.det(matrix),1)
    def test_mhr_named_body_and_finger_mapping(self):
        mapping=source_map(['root','c_spine0','c_spine1','c_spine2','c_spine3','c_neck','c_head','l_lowarm','l_middle1','l_middle2','l_middle3'])
        self.assertEqual(mapping['head'],6)
        self.assertEqual(mapping['lForearmBend'],7)
        self.assertEqual(mapping['l_mid3'],10)
    def test_path_traversal_rejected(self):
        for value in ('../../hello','..','x'*24,'a'*23,'a'*25):
            with self.assertRaises(ValueError):identifier(value)
    def test_genesis_driven_twist_is_evaluated_once(self):
        rig={'nodes':[{'id':'arm'},{'id':'twist'}],'formulas':[{'output':'twist:#twist?rotation/x','operations':[{'op':'push','url':'arm:#arm?rotation/x'},{'op':'push','val':-.75},{'op':'mult'}]}]}
        actual=evaluated_channels(rig,{'arm':[80,0,0],'twist':[0,0,0]})
        self.assertEqual(actual['twist'],[-60,0,0])
    def test_noncommuting_dson_axes_match_daz_capture(self):
        values=[-27.8230934865061,60.12635187114582,21.88588302929555]
        expected=Rotation.from_euler('YZX',[-values[1],-values[2],-values[0]],degrees=True).as_matrix().T
        np.testing.assert_allclose(rotation(values,'YZX'),expected,atol=1e-12)

class ExportTests(unittest.TestCase):
    def setUp(self):
        self.pose=dict(version=1,rigId='g9',label='Genesis 9',rotations={'hip':[12,34,56]},translation=[0,15,0],rootRotation=[0,90,0],rig={'nodes':[{'id':'hip','type':'bone'}]})
    def test_keep_omits_translation(self):
        output=duf(self.pose,'keep')['scene']['animations']
        self.assertFalse(any('translation' in a['url'] for a in output))
        self.assertEqual(output[0]['url'],'name://@selection/hip:?rotation/x/value')
        self.assertEqual(output[0]['keys'],[[0,12]])
    def test_floor_and_origin_have_distinct_root_values(self):
        floor=duf(self.pose,'floor')['scene']['animations'];origin=duf(self.pose,'origin')['scene']['animations']
        self.assertEqual(floor[-2]['keys'],[[0,15]])
        self.assertEqual(origin[-2]['keys'],[[0,0]])
    def test_facial_or_unknown_channels_rejected(self):
        self.pose['rotations']['alien']=[0,0,0]
        with self.assertRaises(ValueError):duf(self.pose,'keep')
    def test_nonfinite_channels_rejected(self):
        self.pose['rotations']['hip']=[float('nan'),0,0]
        with self.assertRaises(ValueError):duf(self.pose,'keep')
    def test_ack_is_scoped_to_job(self):
        script=application_script(self.pose,'keep',Path('temp/test-ack.json'),'a-job')
        self.assertIn('"jobId": "a-job"',script)
        self.assertIn('acceptUndo("PoseSnap pose")',script)
    def test_generation_errors_use_the_rig_id_without_changing_descriptive_titles(self):
        for rig_id,label in (('g8f','Genesis 8 Female'),('g8m','Genesis 8 Male'),('g9','Genesis 9')):
            pose=copy.deepcopy(self.pose);pose.update(rigId=rig_id,label='Both holding hands')
            pose['rig']['label']='A legacy custom label'
            before=copy.deepcopy(pose)
            script=application_script(pose,'keep',Path('temp/test-ack.json'),'named-pose')
            config=json.loads(script.split('var job = ',1)[1].split(';\n',1)[0])
            self.assertEqual(config['rigLabel'],label)
            self.assertEqual(config['pose']['label'],'Both holding hands')
            self.assertEqual(pose,before)
            self.assertNotIn('job.pose.label',script)
    def test_legacy_passive_zeros_are_omitted_from_both_export_paths(self):
        for name in ('l_pectoral','r_pectoral','l_eye','lowerjaw','tongue01','lLipCorner'):
            self.pose['rig']['nodes'].append(dict(id=name,type='bone'))
            self.pose['rotations'][name]=[0,0,0]
        before=copy.deepcopy(self.pose)
        urls=[a['url'] for a in duf(self.pose,'keep')['scene']['animations']]
        self.assertEqual(len(urls),6)
        script=application_script(self.pose,'keep',Path('temp/test-ack.json'),'legacy')
        config=json.loads(script.split('var job = ',1)[1].split(';\n',1)[0])
        self.assertEqual(config['pose']['rotations'],{'hip':[12,34,56]})
        self.assertEqual(self.pose,before)
        self.assertIn('maximumError>0.1',script)
    def test_shared_layout_preserves_scale_instead_of_requiring_defaults(self):
        pose=dict(self.pose,personId=1,layout=dict(version=1,id='group',personIds=[1,2],reference=True))
        script=application_script(pose,'reference',Path('temp/test-ack.json'),'layout-job')
        self.assertLess(script.index('figure.getNodeParent()'),script.index('beginUndo()'))
        self.assertLess(script.index('var scale=snapshotScale(figure)'),script.index('beginUndo()'))
        self.assertLess(script.index('verifyScale(scale)'),script.index('acceptUndo('))
        self.assertNotIn('Restore the figure',script)
        self.assertIn('scalePreserved:true',script)
    def test_every_placement_exports_only_rotations_and_positions(self):
        pose=dict(self.pose,personId=1,layout=dict(version=2,id='group',personIds=[1,2],reference=True))
        for placement in ('keep','floor','origin','reference'):
            for channel in duf(pose,placement)['scene']['animations']:
                self.assertRegex(channel['url'],r'\?((rotation|translation)/[xyz])/value$')
    def test_duf_does_not_write_formula_driven_channels(self):
        self.pose['rig']['nodes'][0]['driven']=['y']
        urls=[a['url'] for a in duf(self.pose,'keep')['scene']['animations']]
        self.assertNotIn('name://@selection/hip:?rotation/y/value',urls)

class RigConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=Path(__file__).resolve().parents[1]/'temp';self.temp.mkdir(exist_ok=True)
        self.rig=dict(version=4,id='g9',sourceId='Genesis9',nodes=[
            dict(id=name,type='figure' if name=='Genesis9' else 'bone',parent=None if name=='Genesis9' else 'Genesis9',center=[0,0,0],end=[0,1,0],orientation=[0,0,0],order='XYZ',limits={})
            for name in ('Genesis9','hip','l_hand','r_hand','l_upperarm','r_upperarm')],formulas=[])
    def test_legacy_cache_migrates_without_former_asset_access(self):
        with tempfile.TemporaryDirectory(dir=self.temp) as folder:
            root=Path(folder);destination=root/'data/rigs/g9.json';destination.parent.mkdir(parents=True)
            destination.write_text(json.dumps(dict(self.rig,version=3,source='Z:/missing/library/Genesis9.dsf')))
            loaded=profile(root,'g9')
            self.assertEqual(loaded['version'],4)
            self.assertNotIn('source',loaded)
            self.assertEqual(loaded['nodes'],self.rig['nodes'])
    def test_bad_connection_never_replaces_valid_profile(self):
        with tempfile.TemporaryDirectory(dir=self.temp) as folder:
            root=Path(folder);cache_profile(root,self.rig,'g9');broken=copy.deepcopy(self.rig)
            broken['nodes'][1]['parent']='hip'
            with self.assertRaisesRegex(ValueError,'Cyclic'):cache_profile(root,broken,'g9')
            self.assertEqual(profile(root,'g9')['nodes'],self.rig['nodes'])
    def test_wrong_generation_and_nonfinite_rest_rejected(self):
        with self.assertRaises(ValueError):validate_profile(self.rig,'g8f')
        self.rig['nodes'][1]['orientation'][0]=float('nan')
        with self.assertRaisesRegex(ValueError,'rest transform'):validate_profile(self.rig,'g9')
    def test_rotation_controller_scalar_and_addend(self):
        self.rig['formulas']=[dict(output='r_upperarm:#r_upperarm?rotation/x',operations=[dict(op='push',url='l_upperarm:#l_upperarm?rotation/x'),dict(op='push',val=-.75),dict(op='mult'),dict(op='push',val=2.5),dict(op='add')])]
        validate_profile(self.rig,'g9')
        self.assertEqual(evaluated_channels(self.rig,{'l_upperarm':[80,0,0]})['r_upperarm'][0],-57.5)
    def test_connection_script_scope_and_unicode_paths(self):
        script=connection_script('g9',Path('temp/अ/ack.json'),'connection-test',Path('temp/jobs/test.cancel'))
        self.assertIn('"jobId": "connection-test"',script)
        self.assertNotIn('__POSESNAP_CONFIG__',script)
        self.assertNotIn('openFile(',script)
        self.assertNotIn('setValue(',script)
        self.assertIn('getOrigin(true)',script)

if __name__=='__main__':unittest.main()
