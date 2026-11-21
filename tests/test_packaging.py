"""Small packaging fixtures exercise privacy/integrity gates without copying engines."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('release_package', Path(__file__).parents[1]/'scripts/package.py')
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def manifest(self):
        file = self.root/'PoseSnap.exe'
        file.write_bytes(b'isolated-fixture')
        manifest = {'schema': 2, 'version': '1.0.0', 'kind': 'portable-core', 'installedBytes': file.stat().st_size,
                    'files': {'PoseSnap.exe': {'size': file.stat().st_size, 'sha256': package.digest(file)}}}
        (self.root/'manifest.json').write_text(json.dumps(manifest))
        return manifest

    def test_verified_reuse_links_prior_stage_instead_of_mutable_source(self):
        source=self.root/'source'; prior=self.root/'prior'; target=self.root/'new'
        source.write_bytes(b'same'); prior.write_bytes(b'same')
        package.copy_or_reuse(source,target,prior)
        self.assertEqual(target.stat().st_ino,prior.stat().st_ino)
        self.assertNotEqual(target.stat().st_ino,source.stat().st_ino)
        source.write_bytes(b'edit')
        self.assertEqual(target.read_bytes(),b'same')

    def test_changed_file_is_copied_without_changing_prior_stage(self):
        source=self.root/'source'; prior=self.root/'prior'; target=self.root/'new'
        source.write_bytes(b'new'); prior.write_bytes(b'old')
        package.copy_or_reuse(source,target,prior)
        self.assertEqual(target.read_bytes(),b'new')
        self.assertEqual(prior.read_bytes(),b'old')
        self.assertNotEqual(target.stat().st_ino,prior.stat().st_ino)

    def test_reuse_rejects_a_directory_outside_release(self):
        (self.root/'package.json').write_text('{"version":"1.0.1","releaseChannel":"stable"}')
        with patch.object(package,'app_version',return_value='1.0.1'):
            with self.assertRaisesRegex(ValueError,'separate verified staging'):
                package.stage(self.root,'fresh',reuse=self.root/'unverified')

    def test_compiler_paths_are_rejected_in_both_encodings_and_separator_styles(self):
        binary=self.root/'app.exe'
        for prefix in (str(self.root),self.root.as_posix()):
            for encoding in ('utf-8','utf-16-le'):
                binary.write_bytes(b'header'+(prefix+'/dependency/file.rs').encode(encoding))
                with self.assertRaisesRegex(ValueError,'local compiler source path'):
                    package.binary_privacy(binary,self.root)

    def test_remapped_dependency_diagnostics_pass_without_local_paths(self):
        binary=self.root/'app.exe';binary.write_bytes(b'header dependencies/tauri/src/lib.rs')
        self.assertEqual(package.binary_privacy(binary,self.root)['workspacePathMatches'],0)

    def test_extra_personal_file_is_not_silently_ignored(self):
        self.manifest()
        self.assertEqual(package.verify(self.root)['files'], 1)
        (self.root/'personal-photo.jpg').write_bytes(b'not-for-release')
        with self.assertRaisesRegex(ValueError, 'Unexpected'):
            package.verify(self.root)

    def test_runtime_state_requires_explicit_local_verification(self):
        self.manifest()
        (self.root/'data').mkdir()
        (self.root/'data/settings.json').write_text('{}')
        with self.assertRaises(ValueError):
            package.verify(self.root)
        package.verify(self.root, initialized=True)

    def test_corruption_and_manifest_escape_fail(self):
        manifest = self.manifest()
        (self.root/'PoseSnap.exe').write_bytes(b'corrupted')
        with self.assertRaisesRegex(ValueError, 'mismatch'):
            package.verify(self.root)
        for path in ('../secret', 'C:/secret', 'data\\secret'):
            with self.assertRaises(ValueError):
                package.safe_file(self.root, path)

    def test_optional_model_payload_is_rejected_even_if_listed(self):
        manifest = self.manifest()
        (self.root/'models').mkdir()
        file = self.root/'models/weights.gguf'
        file.write_bytes(b'optional')
        manifest['files']['models/weights.gguf'] = {'size': 8, 'sha256': package.digest(file)}
        manifest['installedBytes'] += 8
        (self.root/'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'optional payload'):
            package.verify(self.root)

    def test_versions_must_agree(self):
        (self.root/'src-tauri').mkdir()
        (self.root/'package.json').write_text('{"version":"1.0.0"}')
        (self.root/'package-lock.json').write_text('{"version":"1.0.0","packages":{"":{"version":"1.0.0"}}}')
        (self.root/'src-tauri/tauri.conf.json').write_text('{"version":"1.0.0"}')
        (self.root/'src-tauri/Cargo.toml').write_text('[package]\nversion="1.0.0"\n')
        self.assertEqual(package.app_version(self.root), '1.0.0')
        (self.root/'package.json').write_text('{"version":"0.1.0"}')
        with self.assertRaisesRegex(ValueError, 'must agree'):
            package.app_version(self.root)

    def test_staging_never_merges_an_existing_distribution(self):
        self.test_versions_must_agree()
        (self.root/'package.json').write_text('{"version":"1.0.0"}')
        target = self.root/'release/PoseSnap-1.0.0-fixture-Windows-x64'
        target.mkdir(parents=True)
        (target/'old-user-file').write_text('keep')
        with self.assertRaisesRegex(ValueError, 'never merge'):
            package.stage(self.root, 'fixture')
        self.assertEqual((target/'old-user-file').read_text(), 'keep')

    def test_final_staging_uses_version_only_name_and_never_overwrites(self):
        (self.root/'package.json').write_text('{"version":"1.0.1","releaseChannel":"stable"}')
        target = self.root/'release/PoseSnap-1.0.1-Windows-x64'
        target.mkdir(parents=True)
        (target/'keep').write_bytes(b'previous final')
        with patch.object(package, 'app_version', return_value='1.0.1'):
            with self.assertRaisesRegex(ValueError, 'never merge'):
                package.stage(self.root, 'ignored', final=True)
        self.assertEqual((target/'keep').read_bytes(), b'previous final')

    def test_development_build_cannot_be_packaged_as_final(self):
        (self.root/'package.json').write_text('{"version":"1.1.1","releaseChannel":"development"}')
        with patch.object(package,'app_version',return_value='1.1.1'):
            with self.assertRaisesRegex(ValueError,'development'):
                package.stage(self.root,'ignored',final=True)
        self.assertFalse((self.root/'release').exists())

    def test_bundled_skill_changes_invalidate_build_identity(self):
        skill = self.root/'skills/kimodo-prompt/SKILL.md'
        skill.parent.mkdir(parents=True)
        skill.write_text('first')
        real_digest = package.digest
        with patch.object(package, 'digest', side_effect=lambda p: real_digest(p) if p.is_file() else 'fixture'):
            before = package.source_identity(self.root)['sha256']
            skill.write_text('updated')
            self.assertNotEqual(package.source_identity(self.root)['sha256'], before)

    def test_source_changes_during_build_are_rejected(self):
        binary = self.root/'src-tauri/target/release/PoseSnap.exe'
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b'fixture')
        with patch.object(package, 'app_version', return_value='1.0.0'), patch.object(package, 'executable_version', return_value='1.0.0.0'), patch.object(package, 'source_identity', return_value={'sha256': 'new'}):
            with self.assertRaisesRegex(ValueError, 'changed while building'):
                package.record_build(self.root, 'old')
