"""Development metadata only: pin existing files; never create runtime packs."""
import gzip
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'src-tauri/engine-catalogue.json.gz'

# NumPy imports this helper through numpy.testing during ordinary SciPy loading.
# Its directory name is not proof that the file is build/test-only.
RUNTIME_TEST_HELPERS = {'runtime/python/Lib/site-packages/numpy/_core/tests/_natype.py'}


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def record(path, target=None):
    return dict(path=target or path.relative_to(ROOT).as_posix(), size=path.stat().st_size, sha256=digest(path))


def tree(relative):
    files = []
    for path in sorted((ROOT / relative).rglob('*')):
        name = path.relative_to(ROOT).as_posix()
        if path.is_symlink() or not path.is_file():
            continue
        if name not in RUNTIME_TEST_HELPERS and any(p in ('.git', '__pycache__', 'tests', 'test', 'idlelib', 'turtledemo', 'Scripts') for p in path.relative_to(ROOT).parts):
            continue
        if path.suffix != '.pyc':
            files.append(record(path))
    if not files:
        raise ValueError('Missing local component: ' + relative)
    return files


def apply_published(catalogue):
    # Give the current camera checkpoint its own installation root.
    # Migrate the former directory claim only when its exact inventory agrees.
    for component in catalogue['components']:
        if component['id'] == 'camera' and component['roots'] == ['models/camera']:
            if [row['path'] for row in component['files']] != ['models/camera/model.pt']:
                raise ValueError('Cannot narrow camera ownership with an unexpected inventory')
            component['roots'] = ['models/camera/model.pt']
    path = ROOT/'scripts/component-releases.json'
    if not path.exists():
        return catalogue
    for release in json.loads(path.read_text())['components']:
        component = next(c for c in catalogue['components'] if c['id'] == release['component'])
        for row in release.get('extraFiles', []):
            if not any(f['path'] == row['path'] for f in component['files']):
                component['files'].append(row)
        records = sorted(component['files'], key=lambda f: f['path'])
        signature = hashlib.sha256(json.dumps(records, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if signature != release['inventorySha256']:
            raise ValueError('Published pack no longer matches '+component['id']+'; build a new immutable release')
        component['artifacts'] = [release['artifact'], *release.get('additionalArtifacts', [])]
        component['note'] = release['note']
    return catalogue


def main():
    if '--optional-only' in sys.argv:
        previous=json.loads(gzip.decompress(OUT.read_bytes()))
        previous['components']=[c for c in previous['components'] if not c['id'].startswith(('kimodo-','clue-','guidance-'))]
        for name in ('kimodo-components.json','diagnostic-components.json','guidance-components.json'):
            previous['components'].extend(json.loads((ROOT/'worker'/name).read_text(encoding='utf-8'))['components'])
        OUT.write_bytes(gzip.compress(json.dumps(apply_published(previous),separators=(',',':')).encode(),mtime=0))
        print('Updated optional component metadata; existing engine pins preserved.',flush=True)
        return
    components = []
    def component(key, label, version, roots, files, artifacts=None, source=None, required=True, note=''):
        components.append(dict(id=key, label=label, version=version, roots=roots, files=files,
                               artifacts=artifacts or [], source=source, required=required, note=note))
        print(label, len(files), 'files', flush=True)

    component('browser', 'Private WebView2', '154.0.4258.62', ['runtime/webview2'], tree('runtime/webview2'),
              source='https://developer.microsoft.com/en-us/microsoft-edge/webview2/',
              note='A compatible verified runtime pack is not hosted yet. Import its folder from a complete PoseSnap copy.')
    component('python', 'Private Python + CUDA engine', '3.11.9 / Torch 2.8.0 cu128', ['runtime/python', 'runtime/native', 'vendor'],
              tree('runtime/python') + tree('runtime/native') + tree('vendor'),
              source='https://www.python.org/downloads/release/python-3119/',
              note='This includes the tested numerical libraries and model code. Bare Python is insufficient. Import a complete PoseSnap folder until a verified pack is hosted.')
    locked = json.loads((ROOT / 'assets.lock.json').read_text())['files']
    direct = {
        'body': ('SAM 3D Body + MHR', ['models/body'], ['models/body/model.ckpt', 'models/body/model_config.yaml', 'models/body/assets/mhr_model.pt']),
        'camera': ('MoGe shared camera', ['models/camera/model.pt'], ['models/camera/model.pt']),
        'segmentation': ('SAM 2 person masks', ['models/segmentation'], ['models/segmentation/sam2.1_hiera_tiny.pt']),
        'legacy-detector': ('YOLOX fallback detector', ['models/detection/yolox_s.onnx'], ['models/detection/yolox_s.onnx']),
    }
    urls = {
        'models/camera/model.pt': 'https://huggingface.co/Ruicheng/moge-2-vitl-normal/resolve/main/model.pt',
        'models/segmentation/sam2.1_hiera_tiny.pt': 'https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_tiny.pt',
        'models/detection/yolox_s.onnx': 'https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_s.onnx',
    }
    for key, (label, roots, paths) in direct.items():
        files = [dict(path=p, size=locked[p]['size'], sha256=locked[p]['sha256']) for p in paths]
        artifacts = [dict(size=f['size'], sha256=f['sha256'], urls=[urls[f['path']]], kind='file', target=f['path'], mappings=[]) for f in files if f['path'] in urls]
        component(key, label, 'Pinned weights', roots, files, artifacts, locked[paths[0]]['source'], key != 'legacy-detector',
                  'Authorised SAM 3D assets may require accepting upstream access terms. Import the downloaded files or the body folder.' if key == 'body' else '')
    adapted = ROOT / '.tools/rtmo/instance-aware.onnx'
    component('interaction-detector', 'Interaction-aware person detector', 'RTMO body7 / NMS 1.0', ['models/detection/rtmo_body7.onnx'],
              [record(adapted, 'models/detection/rtmo_body7.onnx')],
              source='https://github.com/open-mmlab/mmpose/tree/main/projects/rtmo',
              note='PoseSnap uses an adapted, checksum-pinned graph. Import instance-aware.onnx from this development copy or a verified pack.')
    for key, filename, label in [('wholebody', 'rtmw-l.onnx', 'RTMW whole-body measurements'), ('hands', 'rtmpose-hand.onnx', 'Detailed hand measurements')]:
        path = ROOT / '.tools/refinement' / filename
        target = 'models/refinement/' + filename
        archive = path.with_name(filename + '.zip')
        metadata = next(p for p in json.loads((ROOT / '.tools/refinement/models.json').read_text()) if p['file'] == filename)
        import zipfile
        with zipfile.ZipFile(archive) as bundle:
            entry, = [p for p in bundle.namelist() if p.endswith('.onnx')]
        artifact = dict(kind='zip', size=archive.stat().st_size, sha256=digest(archive), urls=[metadata['url']], target=None,
                        mappings=[dict(entry=entry, target=target)])
        component(key, label, 'Pinned ONNX', ['models/refinement/' + filename], [record(path, target)], [artifact], metadata['url'])
    kimodo_catalogue = ROOT / 'worker/kimodo-components.json'
    if kimodo_catalogue.is_file():
        components.extend(json.loads(kimodo_catalogue.read_text(encoding='utf-8'))['components'])
    components.extend(json.loads((ROOT/'worker/diagnostic-components.json').read_text(encoding='utf-8'))['components'])
    guidance=ROOT/'worker/guidance-components.json'
    if guidance.is_file():components.extend(json.loads(guidance.read_text(encoding='utf-8'))['components'])
    OUT.write_bytes(gzip.compress(json.dumps(apply_published(dict(version=1, components=components)), separators=(',', ':')).encode(), mtime=0))
    print('Catalogue metadata:', OUT.stat().st_size, 'bytes. No packs built.', flush=True)


if __name__ == '__main__':
    main()
