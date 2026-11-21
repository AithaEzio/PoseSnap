"""Exercise the actual PowerShell launcher without opening a GUI or user data."""
import hashlib
import gzip
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'scripts/test-desktop.ps1'
APP=ROOT/'src-tauri/target/release/PoseSnap.exe'
spec=importlib.util.spec_from_file_location('prepare_test_engines',ROOT/'scripts/prepare-test-engines.py')
reuse=importlib.util.module_from_spec(spec);spec.loader.exec_module(reuse)


def ps(value):
    return "'"+str(value).replace("'","''")+"'"


@unittest.skipUnless(os.name=='nt' and APP.is_file(),'Windows release executable required; no GUI is launched')
class DesktopLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='launcher Ω ')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.version=json.loads((ROOT/'package.json').read_text())['version']
        (self.root/'package.json').write_text(json.dumps(dict(version=self.version)))
        (self.root/'release').mkdir()
        model=self.root/'models/body/fixture.pt';model.parent.mkdir(parents=True)
        model.write_bytes(b'only an isolated engine fixture')
        self.catalogue=dict(version=1,components=[dict(id='body',label='Fixture body',required=True,
            files=[dict(path='models/body/fixture.pt',size=model.stat().st_size,sha256=hashlib.sha256(model.read_bytes()).hexdigest())])])

    def candidate(self,label,date):
        folder=self.root/'release'/f'PoseSnap-{self.version}-{label}-Windows-x64'
        (folder/'worker').mkdir(parents=True)
        (folder/'manifests').mkdir()
        shutil.copyfile(APP,folder/'PoseSnap.exe')
        (folder/'worker/main.py').write_text('# isolated, never run\n')
        receipt=dict(applicationVersion=self.version,source=dict(sha256='a'*64),
                     executableSha256=hashlib.sha256((folder/'PoseSnap.exe').read_bytes()).hexdigest())
        (folder/'manifests/build-receipt.json').write_text(json.dumps(receipt))
        (folder/'manifests/engine-catalogue.json.gz').write_bytes(gzip.compress(json.dumps(self.catalogue).encode()))
        self.manifest(folder,label,date)
        return folder

    def manifest(self,folder,label,date):
        files={file.relative_to(folder).as_posix():dict(size=file.stat().st_size,sha256=hashlib.sha256(file.read_bytes()).hexdigest())
               for file in folder.rglob('*') if file.is_file() and file.name!='manifest.json'}
        value=dict(schema=2,channel='development',kind='portable-core',version=self.version,created=date,candidate=label,sourceSha256='a'*64,files=files)
        (folder/'manifest.json').write_text(json.dumps(value))

    def run_launcher(self,launch=False,running=False,exit_code=0):
        setup='[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); '
        if launch:
            output=self.root/'launch.json'
            setup+=f"function global:Get-Process {{ param($Name,$ErrorAction) {'[pscustomobject]@{Id=123}' if running else ''} }}; "
            setup+=f"function global:Start-Process {{ param($FilePath,$WorkingDirectory,$WindowStyle,[switch]$PassThru) @{{app=$FilePath;cwd=$WorkingDirectory;style=$WindowStyle}} | ConvertTo-Json | Set-Content -LiteralPath {ps(output)} -Encoding UTF8; $stubProcess=[pscustomobject]@{{ExitCode={exit_code}}}; $stubProcess | Add-Member -MemberType ScriptMethod -Name WaitForExit -Value {{}}; return $stubProcess }}; "
        command=setup+f'& {ps(SCRIPT)} -ProjectRoot {ps(self.root)}'+('' if launch else ' -CheckOnly')
        return subprocess.run(['powershell.exe','-NoLogo','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-Command',command],
                              capture_output=True,text=True,encoding='utf-8',timeout=35)

    def test_latest_manifest_date_wins_over_directory_modification_time(self):
        older=self.candidate('older','2026-11-14T00:00:00Z')
        newest=self.candidate('newer','2026-11-15T00:00:00Z')
        os.utime(older,None)
        result=self.run_launcher()
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('Selected: '+str(newest/'PoseSnap.exe'),result.stdout)
        self.assertIn('No application was launched',result.stdout)

    def test_corrupt_newest_never_falls_back(self):
        self.candidate('older','2026-11-14T00:00:00Z')
        newest=self.candidate('newer','2026-11-15T00:00:00Z')
        (newest/'worker/main.py').write_text('corrupt')
        result=self.run_launcher()
        self.assertEqual(result.returncode,1)
        self.assertIn('checksum failed',result.stdout)
        self.assertNotIn('Selected:',result.stdout)

    def test_missing_file_stops(self):
        folder=self.candidate('missing','2026-11-15T00:00:00Z')
        (folder/'worker/main.py').unlink()
        self.assertIn('Build file is missing',self.run_launcher().stdout)

    def test_build_receipt_mismatch_stops_even_with_matching_file_hashes(self):
        folder=self.candidate('mismatch','2026-11-15T00:00:00Z')
        receipt=folder/'manifests/build-receipt.json'
        value=json.loads(receipt.read_text());value['source']['sha256']='b'*64
        receipt.write_text(json.dumps(value));self.manifest(folder,'mismatch','2026-11-15T00:00:00Z')
        self.assertIn('build receipt disagree',self.run_launcher().stdout)

    def test_escaping_manifest_path_stops(self):
        folder=self.candidate('escape','2026-11-15T00:00:00Z')
        manifest=folder/'manifest.json';value=json.loads(manifest.read_text())
        value['files']['../outside']={};manifest.write_text(json.dumps(value))
        self.assertIn('Invalid build file path',self.run_launcher().stdout)

    def test_source_version_without_a_matching_package_does_not_run_old_version(self):
        self.candidate('old-version','2026-11-15T00:00:00Z')
        (self.root/'package.json').write_text('{"version":"99.0.0"}')
        self.assertIn('No packaged v99.0.0 build',self.run_launcher().stdout)

    def test_launch_uses_the_selected_folder_after_relocation(self):
        folder=self.candidate('relocated','2026-11-15T00:00:00Z')
        result=self.run_launcher(launch=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        launched=json.loads((self.root/'launch.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(launched['app'],str(folder/'PoseSnap.exe'))
        self.assertEqual(launched['cwd'],str(folder))
        self.assertEqual(launched['style'],'Normal')

    def test_existing_app_is_left_running(self):
        self.candidate('running','2026-11-15T00:00:00Z')
        result=self.run_launcher(launch=True,running=True)
        self.assertEqual(result.returncode,1)
        self.assertIn('Close existing PoseSnap',result.stdout)
        self.assertFalse((self.root/'launch.json').exists())

    def test_application_failure_is_reported(self):
        self.candidate('failed','2026-11-15T00:00:00Z')
        result=self.run_launcher(launch=True,exit_code=7)
        self.assertEqual(result.returncode,1)
        self.assertIn('exited with code 7',result.stdout)

    def test_engine_reuse_links_verified_bytes_without_copying_or_user_data(self):
        folder=self.candidate('engines','2026-11-15T00:00:00Z')
        (self.root/'data').mkdir();(self.root/'data/settings.json').write_text('{"theme":"neon"}')
        report=reuse.prepare(self.root,folder,lambda *_,**__:None)
        self.assertTrue(report['requiredAvailable']);self.assertEqual(report['linkedFiles'],1)
        self.assertTrue(os.path.samefile(self.root/'models/body/fixture.pt',folder/'models/body/fixture.pt'))
        self.assertEqual(report['weightCopies'],0);self.assertEqual(report['downloads'],0)
        self.assertFalse((folder/'data/settings.json').exists())
        self.assertEqual(reuse.prepare(self.root,folder,lambda *_,**__:None)['linkedFiles'],0)

    def test_incompatible_existing_engine_is_kept(self):
        folder=self.candidate('keep-engine','2026-11-15T00:00:00Z')
        model=folder/'models/body/fixture.pt';model.parent.mkdir(parents=True);model.write_bytes(b'keep existing bytes')
        report=reuse.prepare(self.root,folder,lambda *_,**__:None)
        self.assertFalse(report['requiredAvailable']);self.assertEqual(model.read_bytes(),b'keep existing bytes')
        self.assertEqual(report['linkedFiles'],0)

    def test_changed_source_invalidates_hash_cache_for_a_future_build(self):
        folder=self.candidate('source-cache','2026-11-15T00:00:00Z')
        reuse.prepare(self.root,folder,lambda *_,**__:None)
        model=self.root/'models/body/fixture.pt';model.write_bytes(b'x'*model.stat().st_size)
        future=self.candidate('future','2026-11-16T00:00:00Z')
        report=reuse.prepare(self.root,future,lambda *_,**__:None)
        self.assertFalse(report['requiredAvailable']);self.assertFalse((future/'models/body/fixture.pt').exists())

    def test_production_installation_is_not_hydrated(self):
        folder=self.candidate('stable','2026-11-15T00:00:00Z')
        path=folder/'manifest.json';manifest=json.loads(path.read_text());manifest['channel']='stable';path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError,'development candidates'):
            reuse.prepare(self.root,folder,lambda *_,**__:None)
        self.assertFalse((folder/'models').exists())

    def test_engine_catalogue_cannot_write_outside_component_roots(self):
        folder=self.candidate('bad-catalogue','2026-11-15T00:00:00Z')
        self.catalogue['components'][0]['files'][0]['path']='data/settings.json'
        (folder/'manifests/engine-catalogue.json.gz').write_bytes(gzip.compress(json.dumps(self.catalogue).encode()))
        self.manifest(folder,'bad-catalogue','2026-11-15T00:00:00Z')
        with self.assertRaisesRegex(ValueError,'component inventory'):
            reuse.prepare(self.root,folder,lambda *_,**__:None)
        self.assertFalse((folder/'data/settings.json').exists())


if __name__=='__main__':
    unittest.main()
