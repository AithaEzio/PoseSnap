"""Reuse verified project engines in a local development core without copying weights."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys


def read(path, default=None):
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        return default


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    partial=path.with_name(path.name+f'.{os.getpid()}.partial')
    partial.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    partial.replace(path)


def safe_path(root, relative, checked_dirs=None):
    if not isinstance(relative,str) or not relative or '\\' in relative or ':' in relative or relative.startswith('/') or any(p in ('','..','.') for p in relative.split('/')):
        raise ValueError('Invalid component path: '+str(relative))
    path=root
    for part in relative.split('/'):
        path=path/part
        if checked_dirs is not None and path in checked_dirs:continue
        try:metadata=path.lstat()
        except FileNotFoundError:continue
        if getattr(metadata,'st_file_attributes',0)&0x400:
            raise ValueError('Engine reuse cannot traverse a linked directory or file: '+str(path))
        if checked_dirs is not None and stat.S_ISDIR(metadata.st_mode):checked_dirs.add(path)
    return path


@contextmanager
def preparation_lock(project):
    import msvcrt
    lock=project/'temp/launcher-engine-links/preparation.lock'
    lock.parent.mkdir(parents=True,exist_ok=True)
    with lock.open('a+b') as stream:
        if stream.tell()==0:stream.write(b'0');stream.flush()
        stream.seek(0)
        try:msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        except OSError as error:raise ValueError('Test engines are already being prepared. Wait for the other launcher.') from error
        try:yield
        finally:stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)


def prepare(project, build, progress=print):
    project=project.resolve();build=build.resolve()
    if build.parent!=project/'release' or not build.name.startswith('PoseSnap-'):
        raise ValueError('Choose a packaged test build directly inside this project\'s release folder.')
    if os.name!='nt' or project.stat().st_dev!=build.stat().st_dev:
        raise ValueError('Engine reuse needs the project and test build on the same Windows volume; no large-copy fallback is used.')
    manifest=read(build/'manifest.json',{})
    version=read(project/'package.json',{}).get('version')
    if manifest.get('kind')!='portable-core' or manifest.get('channel') not in ('development','candidate') or manifest.get('version')!=version:
        raise ValueError('Engine reuse is limited to this version\'s local development candidates.')
    checked_dirs=set()  # One preparation owns the lock; immutable parent paths are checked once.
    catalogue_path=safe_path(build,'manifests/engine-catalogue.json.gz',checked_dirs)
    catalogue_bytes=catalogue_path.read_bytes()
    declared=manifest.get('files',{}).get('manifests/engine-catalogue.json.gz',{})
    if hashlib.sha256(catalogue_bytes).hexdigest()!=declared.get('sha256'):
        raise ValueError('The test build\'s engine catalogue checksum does not match its manifest.')
    catalogue=json.loads(gzip.decompress(catalogue_bytes))
    if catalogue.get('version')!=1 or not isinstance(catalogue.get('components'),list):
        raise ValueError('Unsupported engine catalogue.')
    cache_path=project/'temp/launcher-engine-links/hashes.json'
    report=dict(version=1,created=datetime.now(timezone.utc).isoformat(),project=str(project),build=str(build),
                downloads=0,weightCopies=0,components=[],linkedFiles=0,linkedLogicalBytes=0,
                note='Hard links share installed immutable engine bytes. Settings/history are not copied or linked.')
    with preparation_lock(project):
        cached=read(cache_path,{})
        cache=cached.get('hashes',{}) if cached.get('version')==1 else {}
        retained={}
        def matches(path,expected):
            try:metadata=path.stat()
            except FileNotFoundError:return False
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size!=expected['size']:return False
            key=f'{metadata.st_dev}:{metadata.st_ino}:{metadata.st_size}:{metadata.st_mtime_ns}:{metadata.st_ctime_ns}'
            checksum=cache.get(key)
            if not checksum:
                with path.open('rb') as stream:checksum=hashlib.file_digest(stream,'sha256').hexdigest()
            cache[key]=retained[key]=checksum
            return checksum==expected['sha256']
        seen=set()
        try:
            for component in catalogue['components']:
                if component['id']=='browser':continue  # Already part of the verified core.
                expected=component['files']
                if not expected:raise ValueError('Empty engine component inventory.')
                paths=[]
                for item in expected:
                    relative=item['path']
                    if relative in seen or relative in manifest['files'] or not relative.startswith(('runtime/','models/','vendor/')) or relative.startswith('runtime/webview2/') or type(item.get('size')) is not int or item['size']<0 or not re.fullmatch(r'[0-9a-f]{64}',item.get('sha256','')):
                        raise ValueError('Invalid or overlapping engine component inventory: '+relative)
                    seen.add(relative)
                    paths.append((item,safe_path(project,relative,checked_dirs),safe_path(build,relative,checked_dirs)))
                progress('Reusing installed '+component.get('label',component['id'])+'...',flush=True)
                row=dict(id=component['id'],required=component.get('required',False),files=len(paths),linked=0,existing=0)
                conflicts=[item['path'] for item,source,target in paths if target.exists() and not matches(target,item)]
                if conflicts:
                    row.update(state='existing-files-kept',reason='Existing files differ; nothing was overwritten.',filesNeedingReview=conflicts[:8])
                else:
                    missing=[(item,source,target) for item,source,target in paths if not target.exists()]
                    unavailable=[item['path'] for item,source,target in missing if not matches(source,item)]
                    if unavailable:
                        row.update(state='not-available',reason='Compatible files are missing from the project; no download was attempted.',filesNeedingReview=unavailable[:8])
                    else:
                        for item,source,target in missing:
                            target.parent.mkdir(parents=True,exist_ok=True)
                            os.link(source,target)
                            if not os.path.samefile(source,target):raise ValueError('Hard-link identity verification failed: '+item['path'])
                            row['linked']+=1
                            report['linkedFiles']+=1
                            report['linkedLogicalBytes']+=item['size']
                        row.update(state='available',existing=len(paths)-len(missing))
                report['components'].append(row)
            report['requiredAvailable']=all(row['state']=='available' for row in report['components'] if row['required'])
            write(build/'data/engine/test-linked-engines.json',report)
        finally:
            write(cache_path,dict(version=1,hashes=retained))
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--build',type=Path,required=True)
    args=parser.parse_args()
    report=prepare(args.project,args.build)
    print(f"Reused engines: {report['linkedFiles']} new file links; no downloads or weight copies.")
    missing=[row['id'] for row in report['components'] if row['required'] and row['state']!='available']
    if missing:
        print('Required project components need review: '+', '.join(missing)+'. See data/engine/test-linked-engines.json in the test build.',file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,KeyError,TypeError) as error:print('Engine reuse failed: '+str(error),file=sys.stderr);raise SystemExit(1)
