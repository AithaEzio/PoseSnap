"""Portable storage. All generated identifiers are validated before path resolution."""
import base64, hashlib, io, json, os, re, time, shutil
from pathlib import Path

def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + '.pending')
    pending.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    # Windows readers and OneDrive watchers can briefly deny replacement.
    # Retain the prior complete file and retry; persistent errors stay visible.
    for attempt in range(7):
        try:
            os.replace(pending, path)
            return
        except PermissionError:
            if os.name!='nt' or attempt==6:raise
            time.sleep(.025*2**attempt)

def read_json(path, default=None):
    return json.loads(Path(path).read_text(encoding='utf-8')) if Path(path).is_file() else default

def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{24}', value):
        raise ValueError('Invalid local image identifier')
    return value

def image_dir(root, image_id):
    return root / 'data/history' / identifier(image_id)

def data_url(image, size=(1400, 1400)):
    image = image.copy()
    image.thumbnail(size)
    buf = io.BytesIO()
    image.convert('RGB').save(buf, 'JPEG', quality=87)
    return 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode('ascii')


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(4*1024**2), b''):
            value.update(block)
    return value.hexdigest()


def signature(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def display_depth(image,metric=False):
    from PIL import Image
    import numpy as np
    alpha=image.getchannel('A') if 'A' in image.getbands() else None
    if image.mode not in ('I','I;16','I;16B','I;16L','F','L'):
        if image.mode in ('RGB','RGBA','P'):
            array=np.asarray(image.convert('RGB'))
            if not np.array_equal(array[...,0],array[...,1]) or not np.array_equal(array[...,1],array[...,2]):
                raise ValueError('Choose a grayscale depth image, or import this image as a photograph.')
        image=image.convert('L')
    def tile(y):
        box=(0,y,image.width,min(image.height,y+128))
        value=np.asarray(image.crop(box),dtype=np.float32)
        valid=np.isfinite(value)
        if alpha is not None:valid&=np.asarray(alpha.crop(box))>0
        if metric:valid&=value>0
        return value,valid
    low,high=float('inf'),float('-inf')
    for y in range(0,image.height,128):
        values,valid=tile(y)
        if valid.any():low=min(low,float(values[valid].min()));high=max(high,float(values[valid].max()))
    if not np.isfinite([low,high]).all():raise ValueError('The depth image has no valid finite depth values.')
    result=Image.new('L',image.size)
    for y in range(0,image.height,128):
        values,valid=tile(y)
        safe=np.where(valid,values,low)
        grey=np.full(values.shape,127.,dtype=np.float32) if high==low else np.clip((safe-low)*(255./(high-low)),0,255)
        if metric:grey=255-grey
        result.paste(Image.fromarray(np.where(valid,grey,0).astype(np.uint8)),(0,y))
    return result.convert('RGB')


def preserve_original(root,source):
    """Content-address exact import bytes; display pixels never replace depth samples."""
    key=digest(source)
    folder=root/'data/reference-assets'/key
    meta=read_json(folder/'asset.json')
    if meta:
        original=folder/meta['file']
        if not original.is_file() or digest(original)!=key:raise ValueError('The stored original reference failed verification')
        return meta
    folder.mkdir(parents=True,exist_ok=True)
    suffix=source.suffix.lower()
    if suffix not in ('.jpg','.jpeg','.png','.webp','.bmp','.tif','.tiff'):raise ValueError('Unsupported reference image format')
    original=folder/('original'+suffix)
    shutil.copyfile(source,original)
    if digest(original)!=key or digest(source)!=key:raise ValueError('The reference changed during import; retry with a stable file')
    meta=dict(version=1,sha256=key,file=original.name)
    atomic_json(folder/'asset.json',meta)
    return meta

def import_image(root, payload):
    from PIL import Image, ImageOps
    source = Path(payload['path'])
    if not source.is_file() or source.stat().st_size > 100 * 1024 * 1024:
        raise ValueError('Choose an image file smaller than 100 MB')
    kind=payload.get('kind','photo')
    if kind not in ('photo','relative-depth','metric-depth'):raise ValueError('Choose Photo, Relative depth or Metric depth')
    if kind!='photo':
        import numpy as np
        with Image.open(source) as depth_image:
            if depth_image.mode in ('RGB','RGBA','P'):
                values=np.asarray(depth_image.convert('RGB'))
                if not np.array_equal(values[...,0],values[...,1]) or not np.array_equal(values[...,1],values[...,2]):
                    raise ValueError('Choose a grayscale depth file. A colour visualization does not preserve numeric depth values.')
    original=preserve_original(root,source)
    with Image.open(source) as opened:
        if opened.width * opened.height > 40_000_000:
            raise ValueError('Images larger than 40 megapixels need to be resized first')
        oriented=ImageOps.exif_transpose(opened)
        original_mode=oriented.mode
        if kind=='photo':image=oriented.convert('RGB')
        else:
            image=display_depth(oriented,metric=kind=='metric-depth')
    image_id = hashlib.sha256(image.tobytes() + f'{image.size}'.encode()).hexdigest()[:24] if kind=='photo' else hashlib.sha256((original['sha256']+kind+'-display-v2').encode()).hexdigest()[:24]
    folder = image_dir(root, image_id)
    folder.mkdir(parents=True, exist_ok=True)
    image.save(folder / 'source.png')
    thumbnail = image.copy()
    thumbnail.thumbnail((240, 180))
    thumbnail.save(folder / 'thumb.jpg', quality=85)
    meta = read_json(folder / 'image.json', {})
    meta.update(id=image_id, name=source.name, width=image.width, height=image.height, created=time.time(),inputKind=kind,depthConvention='white-near' if kind=='relative-depth' else 'camera-z' if kind=='metric-depth' else None,originalSha256=original['sha256'],originalMode=original_mode,referenceOriginal=original['sha256'])
    atomic_json(folder / 'image.json', meta)
    trim_history(root,keep=image_id)
    return dict(meta, url=data_url(image), people=read_json(folder / 'people.json', []))

def current_reference(meta):
    # Ignore retired test imports without mutating their private rollback data.
    return bool(meta) and not meta.get('multiviewAsset')


def current_editor_draft(poses):
    # Drafts in the general Studio folder can carry a retired source reference.
    return not any(isinstance(pose, dict) and pose.get('multiViewSource') for pose in poses)


def trim_history(root,keep=None):
    settings=read_json(root/'data/settings.json',{})
    limit=max(10,min(200,int(settings.get('historyLimit',100))))
    rows=[]
    for folder in (root/'data/history').iterdir():
        if folder.is_dir() and re.fullmatch(r'[a-f0-9]{24}',folder.name):
            meta=read_json(folder/'image.json',{})
            if meta and not current_reference(meta):continue
            rows.append((meta.get('created',0),folder,sum(p.stat().st_size for p in folder.iterdir() if p.is_file())))
    rows.sort(reverse=True);total=0
    for index,(_,folder,size) in enumerate(rows):
        total+=size
        if folder.name!=keep and (index>=limit or total>4*1024**3):shutil.rmtree(folder)

def history(root):
    folders = root/'data/history'
    if not folders.is_dir():
        return []
    candidates = []
    for folder in folders.iterdir():
        if not folder.is_dir() or not re.fullmatch(r'[a-f0-9]{24}', folder.name):
            continue
        try:
            meta = read_json(folder/'image.json')
            if isinstance(meta,dict) and current_reference(meta) and isinstance(meta.get('created'),(int,float)):
                candidates.append((meta['created'], folder, meta))
        except (OSError, ValueError):
            continue
    rows = []
    for _, folder, meta in sorted(candidates, key=lambda item:item[0], reverse=True):
        try:
            meta['thumbnail'] = 'data:image/jpeg;base64,' + base64.b64encode((folder/'thumb.jpg').read_bytes()).decode('ascii')
            meta['solved'] = (folder/'extraction-preview.json').is_file() or any(folder.glob('solve-*.json'))
            rows.append(meta)
            if len(rows) == 100:
                break
        except (OSError, ValueError):
            continue
    return rows


def bind_people(result,sources):
    """Record the scoped detection identities that produced an accepted pose."""
    result['personKeys']={str(s['personId']):s.get('personKey') for s in sources}
    return result


def verified_history_people(folder,saved,poses,people):
    from instances import cached_source, identity
    wanted={str(p['personId']):identity(people[p['personId']]) for p in poses if p['personId'] in people}
    if len(wanted)!=len(poses):
        return False
    if 'personKeys' in saved:
        return saved['personKeys']==wanted
    if len(poses)==1 and saved.get('personKey'):
        return saved['personKey']==next(iter(wanted.values()))
    carried={str(p['personId']):(p.get('cropPolicy') or {}).get('personKey') for p in poses}
    for source in saved.get('refinementSources',[]):
        if source.get('imageId')==folder.name and source.get('personKey'):
            carried[str(source['personId'])]=source['personKey']
    if any(carried.values()):
        if any(key and wanted.get(person)!=key for person,key in carried.items()):
            return False
        if carried==wanted:
            return True
    layout=poses[0].get('layout') or {}
    if len(poses)>1 and layout.get('version')==1:
        # Legacy Pure used the ordered source keys and rig generations for its layout.
        proof=hashlib.sha256(json.dumps([(wanted[str(p['personId'])],p['rigId']) for p in poses]).encode()).hexdigest()[:24]
        if proof==layout.get('id'):
            return True
    signatures=saved.get('sourceSignatures')
    if not signatures:
        anchor=(poses[0].get('postureBaseline') or {}).get('id') or saved.get('id','')
        if re.fullmatch(r'[a-f0-9]{24}',str(anchor)):
            signatures=read_json(folder/'posture-baselines'/f'{anchor}.sources.json',{})
    if not isinstance(signatures,dict) or set(signatures)!=set(wanted):
        return False
    from refinement import source_signature
    for pose in poses:
        source=cached_source(folder,people[pose['personId']],pose.get('extractionMethod','smart'),
                             context=pose.get('sourceGuidance') or dict(version=1,id='original'))
        if not source or source.get('imageId')!=folder.name or signatures[str(pose['personId'])]!=source_signature(source):
            return False
    return True


def remember_history(folder,pose,source,progress):
    """Save the exact preview channels after a successful extraction or retarget."""
    progress('Saving extracted pose',100)
    atomic_json(folder/'extraction-preview.json',
                bind_people(dict(version=1,poses=[pose]),[source]))
    return pose


def restore_history(root,folder,people,rig_id):
    """Read the latest committed pose independently of prospective settings."""
    from daz import validate_pose
    from extraction import result_path
    from instances import cached_source, source_path

    people_by_id={person['id']:person for person in people if isinstance(person,dict) and 'id' in person}
    preview=folder/'extraction-preview.json'
    interactions=[result_path(folder,'interaction',choice) for choice in ('pure','smart')]
    refinements=[result_path(folder,'refinement',choice) for choice in ('pure','smart')]
    # Earlier builds stored the fitted solo channels in their posture anchor.
    anchors=[p for p in (folder/'posture-baselines').glob('*.json') if not p.name.endswith('.sources.json')]
    records=[path for path in (preview,*interactions,*refinements,*anchors) if path.is_file()]
    for path in sorted(records,key=lambda p:p.stat().st_mtime_ns,reverse=True):
        try:
            saved=read_json(path)
            if not isinstance(saved,dict):
                continue
            poses=saved.get('poses')
            if not isinstance(poses,list) or not 1<=len(poses)<=4:
                continue
            ids={pose['personId'] for pose in poses}
            if len(ids)!=len(poses):
                continue
            if path==preview and (saved.get('version')!=1 or len(poses)!=1):
                continue
            for pose in poses:
                validate_pose(pose)
                if pose['imageId']!=folder.name:
                    raise ValueError('Saved pose belongs to another reference')
            if path in anchors:
                if len(poses)!=1 or saved.get('kind') not in ('extraction','converted-current'):
                    continue
                poses[0]['postureBaseline']={key:saved[key] for key in ('version','id','kind')}
            if len(poses)>1:
                layouts=[pose.get('layout') or {} for pose in poses]
                if not all(layout.get('reference') and layout.get('id') and set(layout.get('personIds',[]))==ids for layout in layouts) or len({layout['id'] for layout in layouts})!=1:
                    continue
                if path not in interactions and path not in refinements:
                    continue
            restored=dict(poses=poses)
            try:
                verified=verified_history_people(folder,saved,poses,people_by_id)
            except (OSError,TypeError,ValueError,KeyError,AttributeError):
                verified=False
            if not verified:
                restored['detached']=True
            if path in refinements or path in interactions:
                result={key:value for key,value in saved.items() if key not in ('refinementSources','sourceSignatures','personKeys')}
                restored.update(result=result,refined=path in refinements)
            return restored
        except (OSError,TypeError,ValueError,KeyError,AttributeError):
            continue

    # Old source-only records can still open through the CPU retargeter.
    candidates=[]
    for person in people_by_id.values():
        for choice in ('pure','smart'):
            paths=[source_path(folder,person,choice)]
            if choice=='smart':
                paths.append(folder/f"solve-{person['id']}.json")
            dates=[path.stat().st_mtime_ns for path in paths if path.is_file()]
            if dates:
                candidates.append((max(dates),person,choice))
    for _,person,choice in sorted(candidates,key=lambda row:row[0],reverse=True):
        try:
            source=cached_source(folder,person,choice,raw=True)
            if source is None or source.get('imageId')!=folder.name:
                continue
            from cropped import prepare
            from retarget import retarget
            from rigs import profile
            source=dict(source,sourceGuidance=dict(version=1,id='original'))
            pose=retarget(prepare(root,source,{},person),profile(root,rig_id))
            return dict(poses=[pose])
        except (OSError,TypeError,ValueError,KeyError,AttributeError):
            continue
    return None
