"""Package only pinned engine files into bounded release assets; never publish."""
import argparse
import contextlib
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PART_BYTES = 1536 * 1024**2


class SplitWriter:
    def __init__(self, folder, name, limit=PART_BYTES):
        self.folder, self.name, self.limit = folder, name, limit
        self.parts, self.position, self.stream = [], 0, None
        self.digest = hashlib.sha256()

    def tell(self):
        return self.position

    def seek(self, *_):
        raise OSError('Sequential release output')

    def write(self, data):
        data = memoryview(data)
        size = len(data)
        while data:
            if self.stream is None:
                path = self.folder / f'{self.name}.part-{len(self.parts)+1:03}'
                self.stream = path.open('xb')
                self.part_digest, self.part_size = hashlib.sha256(), 0
            chunk = data[:min(len(data), self.limit-self.part_size)]
            self.stream.write(chunk)
            self.part_digest.update(chunk); self.digest.update(chunk)
            self.position += len(chunk); self.part_size += len(chunk); data = data[len(chunk):]
            if self.part_size == self.limit:
                self.finish_part()
        return size

    def finish_part(self):
        if self.stream is not None:
            name = Path(self.stream.name).name
            self.stream.close(); self.stream = None
            self.parts.append(dict(name=name, size=self.part_size, sha256=self.part_digest.hexdigest()))

    def flush(self):
        if self.stream is not None:
            self.stream.flush()

    def close(self):
        self.finish_part()


class JoinedReader(io.RawIOBase):
    def __init__(self, paths):
        self.files = [p.open('rb') for p in paths]
        self.sizes = [p.stat().st_size for p in paths]
        self.size, self.position = sum(self.sizes), 0

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        position = offset + (0 if whence == 0 else self.position if whence == 1 else self.size)
        if position < 0:
            raise OSError('Negative archive position')
        self.position = position
        return position

    def read(self, length=-1):
        length = max(0, self.size-self.position) if length < 0 else length
        chunks, start = [], 0
        for stream, size in zip(self.files, self.sizes):
            if self.position < start+size and length:
                stream.seek(self.position-start)
                chunk = stream.read(min(length, start+size-self.position))
                chunks.append(chunk); self.position += len(chunk); length -= len(chunk)
            start += size
        return b''.join(chunks)

    def close(self):
        for stream in self.files:
            stream.close()
        super().close()


def digest(stream):
    value = hashlib.sha256()
    while chunk := stream.read(1024**2):
        value.update(chunk)
    return value.hexdigest()


def pack(root, component, folder, base_url, limit=PART_BYTES, check=lambda: None):
    folder.mkdir(parents=True, exist_ok=False)
    writer = SplitWriter(folder, f"PoseSnap-{component['id']}-{component['version'].split(' / ')[0].replace(' ', '-')}.zip", limit)
    expected = {row['path']: row for row in component['files']}
    with contextlib.closing(writer), zipfile.ZipFile(writer, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=4, allowZip64=True) as archive:
        for index, (name, row) in enumerate(sorted(expected.items())):
            source = root/name
            if not source.is_file() or not source.resolve().is_relative_to(root.resolve()) or source.is_symlink():
                raise ValueError('Missing or escaping pinned input: '+name)
            value, size = hashlib.sha256(), 0
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type, info._compresslevel = zipfile.ZIP_DEFLATED, 4
            with source.open('rb') as incoming, archive.open(info, 'w', force_zip64=True) as output:
                while chunk := incoming.read(1024**2):
                    output.write(chunk); value.update(chunk); size += len(chunk)
            if size != row['size'] or value.hexdigest() != row['sha256']:
                raise ValueError('Pinned input changed: '+name)
            if index % 500 == 0:
                print(f"{component['id']}: {index+1}/{len(expected)} files", flush=True); check()
    writer.finish_part(); check()
    paths = [folder/part['name'] for part in writer.parts]
    with JoinedReader(paths) as stream:
        if digest(stream) != writer.digest.hexdigest():
            raise ValueError('Part concatenation changed')
        stream.seek(0)
        with zipfile.ZipFile(stream) as archive:
            if set(archive.namelist()) != set(expected) or len(archive.namelist()) != len(expected):
                raise ValueError('Archive allowlist mismatch')
            for index, info in enumerate(archive.infolist()):
                row = expected[info.filename]
                with archive.open(info) as incoming:
                    if info.file_size != row['size'] or digest(incoming) != row['sha256']:
                        raise ValueError('Archive content changed: '+info.filename)
                if index % 500 == 0:
                    check()
    parts = [dict(size=p['size'], sha256=p['sha256'], urls=[base_url+'/'+p['name']]) for p in writer.parts]
    artifact = dict(kind='zip', size=writer.position, sha256=writer.digest.hexdigest(), urls=[], target=None, mappings=[], parts=parts)
    result = dict(component=component['id'], files=len(expected), expandedBytes=sum(r['size'] for r in expected.values()),
                  artifact=artifact, assets=writer.parts, verified=True)
    (folder/'pack.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    return result


def scan(root, components, *, private_profile=None):
    findings = []
    profile = re.escape(private_profile if private_profile is not None else Path.home().name)
    sensitive = re.compile(
        r'(?:hf_[a-zA-Z0-9]{30,}|gh[pousr]_[a-zA-Z0-9]{30,}|github_pat_[a-zA-Z0-9_]{40,}'
        rf'|[A-Z]:[\\/]+Users[\\/]+{profile}(?=[\\/]|\b))', re.I)
    for component in components:
        for row in component['files']:
            path = root/row['path']
            if path.suffix.lower() in {'.py','.pth','.json','.yaml','.yml','.ini','.cfg','.txt','.md','.toml'} and path.stat().st_size < 8*1024**2:
                if sensitive.search(path.read_text(encoding='utf-8', errors='replace')):
                    findings.append(row['path'])
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--component', action='append', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--budget', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'https://github\.com/AithaEzio/PoseSnap/releases/download/[A-Za-z0-9.-]+', args.base_url):
        raise ValueError('Unexpected publishing destination')
    sys.path.insert(0, str(ROOT/'training'))
    from pilot_budget import Budget
    catalogue = json.loads(gzip.decompress((ROOT/'src-tauri/engine-catalogue.json.gz').read_bytes()))
    components = [next(c for c in catalogue['components'] if c['id'] == id) for id in args.component]
    findings = scan(ROOT, components)
    if findings:
        raise ValueError('Review potential private metadata before packaging: '+repr(findings))
    with Budget(args.budget).session('build verified release component packs', gpu=False) as budget:
        last_check = time.monotonic()
        def check():
            nonlocal last_check
            if time.monotonic()-last_check >= 90:
                budget.check(); last_check = time.monotonic()
        for component in components:
            budget.check()
            if budget.data['additionalBytes'] + sum(f['size'] for f in component['files'])*1.01 > budget.data['storageLimitBytes']:
                raise ValueError('Worst-case archive growth exceeds the authorised storage headroom')
            result = pack(ROOT, component, args.out/component['id'], args.base_url, check=check)
            budget.check()
            print(json.dumps({k:v for k,v in result.items() if k != 'artifact'}), flush=True)


if __name__ == '__main__':
    main()
