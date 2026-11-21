import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('component_packs', ROOT/'scripts/pack-components.py')
packs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packs)
catalogue_spec = importlib.util.spec_from_file_location('component_catalogue', ROOT/'scripts/catalogue-engine.py')
catalogue = importlib.util.module_from_spec(catalogue_spec)
catalogue_spec.loader.exec_module(catalogue)


class ComponentPackTests(unittest.TestCase):
    def test_bundled_component_roots_are_disjoint(self):
        import gzip
        import json
        value=json.loads(gzip.decompress((ROOT/'src-tauri/engine-catalogue.json.gz').read_bytes()))
        owned=[]
        for component in value['components']:
            for root in component['roots']:
                normalized=root.lower()
                for owner,previous in owned:
                    self.assertFalse(normalized==previous or normalized.startswith(previous+'/') or previous.startswith(normalized+'/'),
                                     f"{owner}: {previous} overlaps {component['id']}: {root}")
                owned.append((component['id'],normalized))

    def test_legacy_camera_directory_claim_is_narrowed_without_changing_downloads(self):
        from copy import deepcopy
        from unittest.mock import patch
        camera=dict(id='camera',roots=['models/camera'],version='pinned',
                    files=[dict(path='models/camera/model.pt',size=123,sha256='a'*64)],
                    artifacts=[dict(kind='file',target='models/camera/model.pt',sha256='a'*64)])
        expected=deepcopy(camera);expected['roots']=['models/camera/model.pt']
        with tempfile.TemporaryDirectory(dir=ROOT/'temp') as folder:
            with patch.object(catalogue,'ROOT',Path(folder)):
                result=catalogue.apply_published(dict(components=[deepcopy(camera)]))
                self.assertEqual(result['components'],[expected])
                self.assertEqual(catalogue.apply_published(result),result)
                camera['files'].append(dict(path='models/camera/unexpected.pt'))
                with self.assertRaisesRegex(ValueError,'unexpected inventory'):
                    catalogue.apply_published(dict(components=[camera]))

    def test_runtime_helper_survives_test_directory_filter(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(dir=ROOT/'temp') as folder:
            root=Path(folder); name=next(iter(catalogue.RUNTIME_TEST_HELPERS))
            helper=root/name; helper.parent.mkdir(parents=True); helper.write_text('pd_NA = None')
            (helper.parent/'test_unneeded.py').write_text('raise RuntimeError')
            with patch.object(catalogue,'ROOT',root):
                self.assertEqual([row['path'] for row in catalogue.tree('runtime/python')],[name])

    def test_published_supplement_is_bound_to_complete_inventory(self):
        from unittest.mock import patch
        import json
        with tempfile.TemporaryDirectory(dir=ROOT/'temp') as folder:
            root=Path(folder); (root/'scripts').mkdir()
            files=[dict(path='runtime/helper',size=1,sha256='a'*64)]
            signature=hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            release=dict(component='python',inventorySha256=signature,extraFiles=files,artifact={'id':'base'},additionalArtifacts=[{'id':'helper'}],note='Verified')
            (root/'scripts/component-releases.json').write_text(json.dumps(dict(components=[release])))
            with patch.object(catalogue,'ROOT',root):
                result=catalogue.apply_published(dict(components=[dict(id='python',files=[])]))
                self.assertEqual(result['components'][0]['artifacts'],[{'id':'base'},{'id':'helper'}])
                with self.assertRaisesRegex(ValueError,'no longer matches'):
                    catalogue.apply_published(dict(components=[dict(id='python',files=[dict(path='extra',size=2,sha256='b'*64)])]))

    def test_small_parts_keep_zip64_payload_and_directory_readable(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'temp') as folder:
            root=Path(folder); (root/'runtime').mkdir(); data=bytes(range(256))*12
            (root/'runtime/file').write_bytes(data)
            component=dict(id='test', version='1', files=[dict(path='runtime/file',size=len(data),sha256=hashlib.sha256(data).hexdigest())])
            result=packs.pack(root,component,root/'out','https://github.com/AithaEzio/PoseSnap/releases/download/test',limit=37)
            self.assertTrue(result['verified']);self.assertGreater(len(result['assets']),2)
            self.assertTrue(all(0<part['size']<=37 for part in result['assets']))
            self.assertEqual(sum(p['size'] for p in result['assets']),result['artifact']['size'])
            self.assertFalse((root/'out/PoseSnap-test-1.zip').exists())
            with packs.JoinedReader([root/'out'/p['name'] for p in result['assets']]) as joined:
                self.assertEqual(packs.digest(joined),result['artifact']['sha256'])

    def test_changed_input_is_rejected_and_never_changes_original(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'temp') as folder:
            root=Path(folder);(root/'runtime').mkdir();source=root/'runtime/file';source.write_bytes(b'actual')
            component=dict(id='test',version='1',files=[dict(path='runtime/file',size=6,sha256='0'*64)])
            with self.assertRaisesRegex(ValueError,'Pinned input changed'):
                packs.pack(root,component,root/'out','https://github.com/AithaEzio/PoseSnap/releases/download/test')
            self.assertEqual(source.read_bytes(),b'actual');self.assertFalse((root/'out/pack.json').exists())

    def test_privacy_scan_flags_credentials_and_development_paths_without_echoing_values(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'temp') as folder:
            root=Path(folder);(root/'config.json').write_text('C:\\Users\\ReleaseFixture\\private')
            component=dict(files=[dict(path='config.json')])
            self.assertEqual(packs.scan(root,[component],private_profile='ReleaseFixture'),['config.json'])


if __name__=='__main__':unittest.main()
