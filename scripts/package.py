"""Build and verify a fresh portable core; optional engines and personal data never enter it."""
import argparse
from datetime import datetime, timezone
import gzip, hashlib, json, os, re, shutil, tomllib, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE_LIMIT = 1024**3


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def app_version(root):
    package, lock = read(root/'package.json'), read(root/'package-lock.json')
    versions = [package['version'], lock['version'], lock['packages']['']['version'],
                read(root/'src-tauri/tauri.conf.json')['version'],
                tomllib.loads((root/'src-tauri/Cargo.toml').read_text(encoding='utf-8'))['package']['version']]
    if len(set(versions)) != 1 or not re.fullmatch(r'\d+\.\d+\.\d+', versions[0]):
        raise ValueError('Application, lockfile and native versions must agree: '+repr(versions))
    return versions[0]


def safe_file(root, relative):
    if not isinstance(relative, str) or '\\' in relative or ':' in relative:
        raise ValueError('Invalid portable path: '+str(relative))
    path = root/relative
    if not path.is_file() or not path.resolve().is_relative_to(root.resolve()) or '..' in Path(relative).parts:
        raise ValueError('Missing or escaping portable file: '+relative)
    if any(p.is_symlink() or getattr(p, 'is_junction', lambda: False)() for p in [path, *path.parents] if p != root and p.is_relative_to(root)):
        raise ValueError('Linked package input is not allowed: '+relative)
    return path


def source_identity(root):
    inputs = []
    for name in ('src', 'public', 'worker', 'src-tauri/src', 'src-tauri/icons', 'skills'):
        inputs.extend(p for p in (root/name).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc')
    inputs.extend(root/p for p in ('package.json', 'package-lock.json', 'vite.config.ts', 'svelte.config.js', 'tsconfig.json',
                  'src-tauri/Cargo.toml', 'src-tauri/Cargo.lock', 'src-tauri/tauri.conf.json', 'src-tauri/build.rs', 'src-tauri/engine-catalogue.json.gz',
                  'scripts/build.ps1', 'scripts/package.py', 'scripts/core-files.json'))
    records = {p.relative_to(root).as_posix(): digest(p) for p in sorted(set(inputs))}
    signature = hashlib.sha256(json.dumps(records, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'sha256': signature, 'files': records}


def executable_version(path):
    import ctypes
    api = ctypes.windll.version
    size = api.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        raise ValueError('Executable has no Windows version metadata')
    buffer = ctypes.create_string_buffer(size)
    pointer, length = ctypes.c_void_p(), ctypes.c_uint()
    if not api.GetFileVersionInfoW(str(path), 0, size, buffer) or not api.VerQueryValueW(buffer, '\\', ctypes.byref(pointer), ctypes.byref(length)):
        raise ValueError('Cannot inspect executable version')
    values = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint32))
    return '.'.join(str(n) for word in (values[2], values[3]) for n in (word >> 16, word & 0xffff))


def binary_privacy(path, build_root):
    data=Path(path).read_bytes().lower()
    prefixes={str(build_root.resolve()),build_root.resolve().as_posix()}
    if any(prefix.encode(encoding).lower() in data for prefix in prefixes for encoding in ('utf-8','utf-16-le')):
        raise ValueError('Executable contains a local compiler source path; rebuild with path remapping')
    return {'workspacePathMatches':0,'sourcePaths':'workspace-and-cargo-remapped'}


def record_build(root, expected_source):
    binary = safe_file(root, 'src-tauri/target/release/PoseSnap.exe')
    version = app_version(root)
    if executable_version(binary) != version+'.0':
        raise ValueError('Release executable version does not match the source')
    source = source_identity(root)
    if source['sha256'] != expected_source:
        raise ValueError('Source changed while building. Do not label this executable as current.')
    privacy=binary_privacy(binary,root)
    receipt = {'version': 1, 'applicationVersion': version, 'builtAt': datetime.now(timezone.utc).isoformat(),
               'channel':read(root/'package.json').get('releaseChannel','stable'),
               'executableSha256': digest(binary), 'source': source, 'binaryPrivacy': privacy,
               'ui': {p.relative_to(root/'dist').as_posix(): digest(p) for p in (root/'dist').rglob('*') if p.is_file()}}
    if 'index.html' not in receipt['ui']:
        raise ValueError('Production UI is missing')
    (binary.parent/'build-receipt.json').write_text(json.dumps(receipt, indent=2)+'\n', encoding='utf-8')
    return {'applicationVersion': version, 'executableSha256': receipt['executableSha256'], 'sourceSha256': receipt['source']['sha256']}


def core_inputs(root):
    files = {'PoseSnap.exe': safe_file(root, 'src-tauri/target/release/PoseSnap.exe')}
    catalogue = json.loads(gzip.decompress((root/'src-tauri/engine-catalogue.json.gz').read_bytes()))
    browser = next(c for c in catalogue['components'] if c['id'] == 'browser')
    for expected in browser['files']:
        relative = expected['path']
        if not relative.startswith('runtime/webview2/'):
            raise ValueError('Unexpected browser root')
        path = safe_file(root, relative)
        if path.stat().st_size != expected['size'] or digest(path) != expected['sha256']:
            raise ValueError('Private WebView2 does not match its pinned catalogue: '+relative)
        files[relative] = path
    for name in read(root/'scripts/core-files.json')['worker']:
        if Path(name).name != name or Path(name).suffix not in {'.py', '.json', '.dsa', '.txt'}:
            raise ValueError('Invalid explicit worker allowlist entry')
        files['worker/'+name] = safe_file(root, 'worker/'+name)
    for path in (root/'licenses').rglob('*'):
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            files[relative] = safe_file(root, relative)
    files['manifests/core-files.json'] = safe_file(root, 'scripts/core-files.json')
    for relative in ('THIRD_PARTY_NOTICES.md', 'assets.lock.json', 'docs/PORTABLE.md'):
        files['README.md' if relative == 'docs/PORTABLE.md' else relative] = safe_file(root, relative)
    for relative in ('src-tauri/engine-catalogue.json.gz', 'src-tauri/target/release/build-receipt.json'):
        files['manifests/'+Path(relative).name] = safe_file(root, relative)
    return files, catalogue


def copy_or_reuse(source, target, prior=None):
    # Link only from an already verified immutable staging directory, never the
    # mutable workspace. The delivered ZIP expands into independent files.
    if prior and prior.is_file() and prior.stat().st_size == source.stat().st_size and digest(prior) == digest(source):
        os.link(prior, target)
    else:
        shutil.copy2(source, target)


def stage(root, label, archive=False, reuse=None, final=False):
    version = app_version(root)
    channel=read(root/'package.json').get('releaseChannel','stable')
    if final and channel=='development':
        raise ValueError('This branch is development-only. A final release requires separate authorization and a release review.')
    if not final and not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.-]{0,63}', label):
        raise ValueError('Use a simple unique candidate label')
    suffix = '' if final else '-'+label
    destination = root/'release'/f'PoseSnap-{version}{suffix}-Windows-x64'
    output = Path(str(destination)+'.zip')
    if destination.exists() or output.exists() or output.with_suffix('.zip.partial').exists():
        raise ValueError('Candidate already exists. Use a new label; never merge distributions.')
    if reuse is not None:
        reuse = Path(reuse).resolve()
        if reuse.parent != destination.parent.resolve() or reuse == destination.resolve():
            raise ValueError('Reuse only a separate verified staging directory inside release')
        verify(reuse)
    build = read(root/'src-tauri/target/release/build-receipt.json')
    if build['applicationVersion'] != version or build['source'] != source_identity(root) or build['executableSha256'] != digest(root/'src-tauri/target/release/PoseSnap.exe'):
        raise ValueError('Release binary is stale. Rebuild before packaging.')
    files, catalogue = core_inputs(root)
    total = sum(p.stat().st_size for p in files.values())
    if total >= CORE_LIMIT:
        raise ValueError('Core exceeds the 1 GiB target before staging')
    destination.mkdir(parents=True)
    manifest_files = {}
    for relative, source in sorted(files.items()):
        target = destination/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        copy_or_reuse(source, target, reuse/relative if reuse else None)
        manifest_files[relative] = {'size': target.stat().st_size, 'sha256': digest(target)}
        if manifest_files[relative]['sha256'] != digest(source):
            raise ValueError('Copy verification failed: '+relative)
    manifest = {'schema': 2, 'version': version, 'candidate': None if final else label, 'channel': 'development' if channel=='development' else 'stable' if final else 'candidate', 'kind': 'portable-core',
                'created': datetime.now(timezone.utc).isoformat(), 'sourceSha256': build['source']['sha256'],
                'installedBytes': total, 'files': manifest_files, 'binaryPrivacy':build.get('binaryPrivacy'),
                'components': [{'id': c['id'], 'version': c['version'], 'included': c['id'] == 'browser',
                                'installation': 'included' if c['id'] == 'browser' else 'download-or-import' if c['artifacts'] else 'offline-import'} for c in catalogue['components']]}
    (destination/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    verify(destination)
    if build['source'] != source_identity(root) or build['executableSha256'] != digest(root/'src-tauri/target/release/PoseSnap.exe'):
        raise ValueError('Build inputs changed during staging. Retain this partial candidate for inspection.')
    if archive:
        partial = output.with_suffix('.zip.partial')
        with zipfile.ZipFile(partial, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True, strict_timestamps=False) as zipped:
            for path in sorted(destination.rglob('*')):
                if path.is_file():
                    zipped.write(path, destination.name+'/'+path.relative_to(destination).as_posix())
        with zipfile.ZipFile(partial) as zipped:
            if zipped.testzip() is not None:
                raise ValueError('Archive CRC validation failed')
        partial.rename(output)
        output.with_suffix('.zip.sha256').write_text(digest(output)+'  '+output.name+'\n', encoding='ascii')
    return {'root': str(destination), 'installedBytes': total, 'archive': str(output) if archive else None,
            'compressedBytes': output.stat().st_size if archive else None, 'manifestSha256': digest(destination/'manifest.json')}


def verify(root, initialized=False):
    root = root.resolve()
    manifest = read(root/'manifest.json')
    if manifest.get('schema') != 2 or manifest.get('kind') != 'portable-core':
        raise ValueError('Not a current portable-core manifest')
    listed = set(manifest['files'])|{'manifest.json'}
    actual = set()
    for path in root.rglob('*'):
        if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
            raise ValueError('Linked package entry: '+str(path))
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if initialized and Path(relative).parts[0] in ('data', 'temp', 'logs'):
            continue
        safe_file(root, relative)
        actual.add(relative)
    if actual != listed:
        raise ValueError('Unexpected or missing package files: '+repr(sorted(actual ^ listed)))
    for relative, record in manifest['files'].items():
        path = safe_file(root, relative)
        if not (relative in {'PoseSnap.exe', 'README.md', 'THIRD_PARTY_NOTICES.md', 'assets.lock.json', 'manifests/core-files.json', 'manifests/engine-catalogue.json.gz', 'manifests/build-receipt.json'} or relative.startswith(('worker/', 'licenses/', 'runtime/webview2/'))):
            raise ValueError('Private or optional payload in core: '+relative)
        if path.stat().st_size != record['size'] or digest(path) != record['sha256']:
            raise ValueError('Size/checksum mismatch: '+relative)
    if sum(v['size'] for v in manifest['files'].values()) != manifest['installedBytes']:
        raise ValueError('Installed size mismatch')
    if manifest.get('binaryPrivacy'):
        binary_privacy(root/'PoseSnap.exe',ROOT)
    return {'files': len(manifest['files']), 'installedBytes': manifest['installedBytes'], 'version': manifest['version']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zip', action='store_true')
    naming = parser.add_mutually_exclusive_group()
    naming.add_argument('--label', default=datetime.now().strftime('rc-%Y%m%d-%H%M%S'))
    naming.add_argument('--final', action='store_true', help='Use the version-only final folder and archive names; existing outputs are never overwritten')
    parser.add_argument('--record-build', action='store_true')
    parser.add_argument('--source-signature', action='store_true')
    parser.add_argument('--expect-source', help='Source signature captured immediately before the native build')
    parser.add_argument('--verify', type=Path)
    parser.add_argument('--initialized', action='store_true', help='Permit app-created data/temp/logs only during local verification')
    parser.add_argument('--reuse-stage', type=Path, help='Reuse unchanged files from a verified immutable local staging directory; never merges outputs')
    args = parser.parse_args()
    if args.source_signature:
        print(source_identity(ROOT)['sha256'])
        return
    if args.record_build and not args.expect_source:
        parser.error('--record-build requires --expect-source')
    result = record_build(ROOT, args.expect_source) if args.record_build else verify(args.verify, args.initialized) if args.verify else stage(ROOT, args.label, args.zip, args.reuse_stage, args.final)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
