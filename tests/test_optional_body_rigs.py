"""Fresh installations need no DAZ connection; cached user rigs retain priority."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from daz import duf
from editor import checked_poses, new_pose, same_profile
from retarget import retarget
from rigs import RIG_IDS, available_profiles, cache_profile, connected_profiles, profile

ROOT=Path(__file__).resolve().parents[1]
FIXTURES=ROOT/'tests/fixtures/target-fit'


class OptionalBodyRigTests(unittest.TestCase):
    def test_fresh_installation_has_all_rigs_without_creating_connections(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            self.assertEqual(available_profiles(root),list(RIG_IDS))
            self.assertEqual(connected_profiles(root),[])
            for rig_id in RIG_IDS:
                rig=profile(root,rig_id)
                self.assertEqual(rig['metadataSource'],'bundled-default')
                captured=json.loads((FIXTURES/(rig_id+'.json')).read_text())
                self.assertTrue(same_profile(rig,captured))
                self.assertNotIn('source',rig)
            self.assertEqual(list(root.iterdir()),[])

    def test_each_request_owns_its_rig_and_cannot_mutate_the_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for rig_id in RIG_IDS:
                first=profile(root,rig_id);original=copy.deepcopy(first)
                first['nodes'][0]['center'][0]+=100
                first['formulas'].clear()
                self.assertEqual(profile(root,rig_id),original)

    def test_optional_connection_preserves_custom_rest_geometry_and_limits(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for rig_id in RIG_IDS:
                rig=profile(root,rig_id)
                bone=next(n for n in rig['nodes'] if n['id']=='hip')
                bone['center'][1]+=2.5
                bone['limits']['x']['max']=17
                cached=cache_profile(root,rig,rig_id)
                self.assertEqual(profile(root,rig_id),cached)
            self.assertEqual(connected_profiles(root),list(RIG_IDS))

    def test_recorded_extraction_and_duf_are_numerically_identical_without_connection(self):
        source=json.loads((FIXTURES/'dancing-source.json').read_text())
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for rig_id in RIG_IDS:
                with self.subTest(rig=rig_id):
                    captured=json.loads((FIXTURES/(rig_id+'.json')).read_text())
                    expected=retarget(copy.deepcopy(source),captured)
                    actual=retarget(copy.deepcopy(source),profile(root,rig_id))
                    for key in ('rotations','translation','quality','warnings','extractionMethod'):
                        self.assertEqual(actual.get(key),expected.get(key))
                    self.assertEqual(duf(actual,'keep'),duf(expected,'keep'))

    def test_studio_and_legacy_draft_work_without_a_connection(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for rig_id in RIG_IDS:
                pose=new_pose(root,rig_id)
                pose['rig']['metadataSource']='legacy-cache'
                checked_poses(root,pose['imageId'],[pose])
                self.assertTrue(duf(pose,'keep')['scene']['animations'])
                changed=copy.deepcopy(pose['rig'])
                changed['nodes'][1]['center'][0]+=.1
                self.assertFalse(same_profile(pose['rig'],changed))
            self.assertFalse((root/'data/rigs').exists())

    def test_default_asset_works_when_relocated_without_project_or_user_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);worker=root/'worker';worker.mkdir()
            for name in ('rigs.py','default-rigs.json'):shutil.copy2(ROOT/'worker'/name,worker/name)
            spec=importlib.util.spec_from_file_location('isolated_rig_defaults',worker/'rigs.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            self.assertEqual(module.available_profiles(root),list(RIG_IDS))
            self.assertEqual(module.connected_profiles(root),[])
            self.assertIn('default-rigs.json',json.loads((ROOT/'scripts/core-files.json').read_text())['worker'])


if __name__=='__main__':unittest.main()
