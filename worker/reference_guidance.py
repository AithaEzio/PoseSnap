"""Versioned image-only evidence, independent of rigs and committed camera placement."""
import base64
import copy
import io
import os
import subprocess
import uuid
import zipfile

import numpy as np
from PIL import Image

from storage import atomic_json, current_reference, digest, image_dir, read_json, signature

VERSION=1
AUTOMATIC_CUES_QUALIFIED=False
DETAILED_CUES_QUALIFIED=False
CACHE_LIMIT=1024**3
MODELS={'auto':'shadenet5-mix-refined.onnx','detailed':'shadenet5-mix.onnx'}
BODY_EDGES=[(side+'_'+a,side+'_'+b) for side in ('l','r') for a,b in
            [('shoulder','elbow'),('elbow','wrist'),('hip','knee'),('knee','ankle')]]


def options(root,payload=None):
    saved=read_json(root/'data/settings.json',{})
    payload=payload or {}
    mode=payload.get('imageGuidance',saved.get('imageGuidance','auto'))
    if mode not in ('off','auto','detailed'):
        if 'imageGuidance' in payload:raise ValueError('Choose Off, Automatic or Detailed image guidance')
        mode='auto'
    if mode=='detailed' and not DETAILED_CUES_QUALIFIED:mode='auto'
    return dict(imageGuidance=mode,geometryEngine='moge2')



def baseline_evidence(settings):
    return dict(version=VERSION,**settings,prepared=False,applied=False,fallback=True,
                outcome='fallback',mapState='unqualified',applicationStage='original-source-retained',
                notes=['Automatic cues have not shown a reliable improvement in held-out pose tests.'])


def record(root,image_id):
    folder=image_dir(root,image_id);meta=read_json(folder/'image.json',{})
    if not current_reference(meta):raise ValueError('The original reference is unavailable')
    return dict(imageId=image_id,source=(folder/'source.png').relative_to(root).as_posix(),
                kind=meta.get('inputKind','photo'),imageSize=[meta['width'],meta['height']],
                originalSha256=meta.get('originalSha256') or digest(folder/'source.png'))


def cache_key(root,item,profile):
    from cache_provenance import stage_signature
    return signature(dict(version=VERSION,image=item['originalSha256'],kind=item['kind'],profile=profile,
                          preprocessing='448-symmetric-letterbox-original-pixel-centres',
                          component=stage_signature(root,('worker/guidance_runtime.py','models/guidance/'+MODELS[profile]))))


def load(root,key):
    if not isinstance(key,str) or len(key)!=64 or any(c not in '0123456789abcdef' for c in key):return None
    folder=root/'data/guidance/maps'
    try:metadata=read_json(folder/(key+'.json'),{})
    except (OSError,ValueError):return None
    relative=metadata.get('path','data/guidance/maps/'+key+'.npz')
    path=(root/relative).resolve()
    if not path.is_relative_to(folder.resolve()) or not path.name.startswith(key+'-') and path.name!=key+'.npz':return None
    if metadata.get('version')!=VERSION or not path.is_file() or metadata.get('sha256')!=digest(path):return None
    try:
        with np.load(path,allow_pickle=False) as data:
            maps,valid=data['maps'].copy(),data['valid'].copy()
        if maps.dtype!=np.float32 or maps.ndim!=3 or maps.shape[0]!=7 or min(maps.shape[1:])<1 or max(maps.shape[1:])>448 or valid.dtype!=bool or valid.shape!=maps.shape[1:] or not np.isfinite(maps).all():return None
    except (OSError,ValueError,KeyError,zipfile.BadZipFile):return None
    return metadata,maps,valid


def prepare(root,image_ids,profile,progress=lambda *_:None):
    if profile=='off':return {}
    if profile not in MODELS:raise ValueError('Unknown image-guidance profile')
    ids=list(dict.fromkeys(image_ids))
    if len(ids)>8:raise ValueError('Prepare at most eight input views')
    model=root/'models/guidance'/MODELS[profile]
    result={};pending=[]
    for image_id in ids:
        item=record(root,image_id)
        if item['kind']!='photo':
            result[image_id]=dict(version=VERSION,state='provided-depth',applied=False,notes=['Original depth values are retained; no inverse-rendering model is run on depth input.'])
            continue
        if not model.is_file():
            result[image_id]=dict(version=VERSION,state='missing',applied=False,notes=['Optional image-guidance files are missing. Original extraction remains available.'])
            continue
        key=cache_key(root,item,profile);saved=load(root,key)
        if saved:
            result[image_id]=dict(saved[0],cacheHit=True)
        else:pending.append(dict(item,key=key,output='data/guidance/maps/'+key+'-'+uuid.uuid4().hex[:8]+'.npz'))
    if not pending:return result
    folder=root/'data/guidance/maps';folder.mkdir(parents=True,exist_ok=True)
    used=sum(p.stat().st_size for p in folder.glob('*.npz'))
    if used+len(pending)*7*448*448*4>CACHE_LIMIT:
        for item in pending:result[item['imageId']]=dict(version=VERSION,state='cache-full',applied=False,notes=['The derived-map cache is full. Original extraction is retained; accepted inputs were not removed.'])
        return result
    job=root/'data/guidance/jobs'/uuid.uuid4().hex;job.mkdir(parents=True)
    atomic_json(job/'request.json',dict(profile=profile,images=pending))
    command=[str(root/'runtime/python/python.exe'),'-I','-B',str(root/'worker/guidance_runtime.py'),'--root',str(root),'--request',str(job/'request.json'),'--response',str(job/'response.json')]
    handle=None;child=None
    try:
        progress('Preparing depth, normals and albedo for '+str(len(pending))+' view'+('s' if len(pending)>1 else ''),12)
        with (job/'runtime.log').open('w',encoding='utf-8') as log:
            child=subprocess.Popen(command,cwd=root,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            from runtime_process import process_job
            handle=process_job(child)
            child.wait(timeout=max(120,len(pending)*60))
        if child.returncode:raise ValueError('Image guidance could not run. See the private guidance runtime log; original extraction is retained.')
        response=read_json(job/'response.json',{})
        rows={row['key']:row for row in response.get('rows',[])}
        for item in pending:
            row=rows.get(item['key'])
            if not row or row.get('path')!=item['output'] or digest(root/item['output'])!=row.get('sha256'):raise ValueError('Image guidance returned an incomplete or invalid batch')
            metadata=dict(row,version=VERSION,provider=response['provider'],revision=response['revision'],modelSha256=response['modelSha256'],
                          profile=profile,normalBasis=response['normalBasis'],depthEncoding=response['depthEncoding'],
                          originalSha256=item['originalSha256'],state='ready',cacheHit=False,applied=False,
                          batchSeconds=response['seconds'],helperMemory=response['memory'],
                          notes=['Derived maps describe the same reference.','ShadeNet depth remains relative; its metric scale and direction are unverified.'])
            atomic_json(folder/(item['key']+'.json'),metadata)
            result[item['imageId']]=metadata
    except (ValueError,OSError,subprocess.TimeoutExpired) as error:
        if child is not None and child.poll() is None:child.kill();child.wait()
        for item in pending:
            result[item['imageId']]=dict(version=VERSION,state='unavailable',applied=False,notes=[str(error)])
    finally:
        if handle:handle[0].CloseHandle(handle[1])
    return result


def sample(values,xy,image_size):
    h,w=values.shape[:2]
    x,y=np.rint((np.asarray(xy)+.5)*[w,h]/image_size-.5).astype(int)
    if not (0<=x<w and 0<=y<h):return None
    patch=values[max(0,y-1):min(h,y+2),max(0,x-1):min(w,x+2)]
    return np.median(patch,axis=(0,1))


def interior_mask(mask,xy,image_size):
    if mask is None:return False
    h,w=mask.shape
    point=(np.asarray(xy)+.5)*[w,h]/image_size-.5
    x,y=np.rint(point).astype(int)
    if not(0<=x<w and 0<=y<h):return False
    # Erosion is defined in original-image pixels, not thumbnail pixels.
    radius=max(1,round(3*min(w/image_size[0],h/image_size[1])))
    return x>=radius and y>=radius and x+radius<w and y+radius<h and bool(mask[y-radius:y+radius+1,x-radius:x+radius+1].all())


def owned_mask(root,image_id,person_key):
    """Only current selected-person evidence may own a surface sample."""
    folder=image_dir(root,image_id)
    with Image.open(folder/'source.png') as image:size=list(image.size)
    people=read_json(folder/'people.json',[])
    from instances import identity,mask_prompts,mask_quality
    person=next((person for person in people if identity(person)==person_key),None)
    if person is None:return None
    others=[value for value in people if value['id']!=person['id']]
    metadata=read_json(folder/('mask-'+person_key+'.json'),{})
    from cache_provenance import stage_signature
    expected=dict(version=2,context=sorted(identity(p) for p in others),personKey=person_key,imageSize=size,
                  signature=stage_signature(root,('worker/segmentation.py','worker/instances.py','models/segmentation/sam2.1_hiera_tiny.pt','vendor/sam2/sam2/configs/sam2.1/sam2.1_hiera_t.yaml')))
    path=folder/('mask-'+person_key+'.png')
    if metadata!=expected or not path.is_file():return None
    try:
        with Image.open(path) as image:mask=np.asarray(image.convert('L'))>0
        positive,negative=mask_prompts(person,others)
        return mask if list(mask.shape[::-1])==size and mask_quality(mask,positive,negative) else None
    except (OSError,ValueError):return None


def prepare_masks(root,groups,progress=lambda *_:None,inference=None):
    """Sequential optional masks. A failure excludes cues, never an actor."""
    notes={}
    for group in groups:
        token=(group['imageId'],group['personKey'])
        if token in notes:continue
        notes[token]=[]
        if owned_mask(root,group['imageId'],group['personKey']) is not None:continue
        folder=image_dir(root,group['imageId']);people=read_json(folder/'people.json',[])
        from instances import identity
        person=next((p for p in people if identity(p)==group['personKey']),None)
        if not person or not person.get('keypoints') or not (root/'models/segmentation/sam2.1_hiera_tiny.pt').is_file():
            notes[token].append('Surface guidance needs a verified person mask. Check the detected person and the segmentation component.')
            continue
        try:
            if inference is not None:inference.release()
            from segmentation import selected_mask
            with Image.open(folder/'source.png') as image:pixels=np.asarray(image.convert('RGB'))
            selected_mask(root,folder,pixels,person,[p for p in people if p['id']!=person['id']],progress)
        except (ValueError,RuntimeError,OSError,ImportError) as error:
            notes[token].append('Surface mask unavailable; original observations retained. '+str(error))
    return notes


def limb_normal(normals,valid,mask,start,end,image_size):
    samples=[]
    for fraction in (.2,.35,.5,.65,.8):
        point=np.asarray(start)*(1-fraction)+np.asarray(end)*fraction
        if not interior_mask(mask,point,image_size):continue
        value=sample(normals,point,image_size);ok=sample(valid.astype(float),point,image_size)
        if value is None or ok is None or ok<.99:continue
        length=np.linalg.norm(value)
        if not np.isfinite(value).all() or length<.8:continue
        samples.append(np.asarray(value)/length)
    if len(samples)<3:return None
    values=np.asarray(samples);centre=np.median(values,axis=0);length=np.linalg.norm(centre)
    if length<.8:return None
    centre/=length
    # Exclude disagreement, boundaries and curved end caps rather than flipping vectors.
    if np.min(values@centre)<np.cos(np.deg2rad(25)):return None
    return centre


def measurements(root,image_id,points,person_key,profile,shade=None):
    """Attach sparse, ownership-checked surface samples; never change 2D points."""
    from camera_depth import load as load_depth,load_normals
    if profile not in ('auto','detailed'):return copy.deepcopy(points),[],[]
    if profile=='auto' and not AUTOMATIC_CUES_QUALIFIED:
        rows=copy.deepcopy(points)
        if record(root,image_id)['kind']!='photo':
            for row in rows:
                for key in list(row):
                    if key.startswith('depth'):row.pop(key)
        return rows,[],['Automatic pose cues did not qualify; original observations were retained.']
    folder=image_dir(root,image_id)
    with Image.open(folder/'source.png') as image:size=list(image.size)
    mask=owned_mask(root,image_id,person_key)
    rows=copy.deepcopy(points);goals=[];notes=[]
    provider='MoGe-2'
    input_kind=record(root,image_id)['kind']
    depth=load_depth(root,folder,provider=provider) if input_kind=='photo' else None
    normal=load_normals(root,folder) if input_kind=='photo' else None
    supplied=provided_depth(root,image_id) if input_kind!='photo' else None
    if supplied and supplied['normal'] is not None:normal=(dict(provider='Provided depth'),supplied['normal'],supplied['normalValid'])
    if input_kind!='photo':
        for point in rows:
            for key in list(point):
                if key.startswith('depth'):point.pop(key)
    if mask is None:return rows,goals,['No verified person mask: surface cues were excluded from pose fitting.']
    reliable=[p for p in rows if p.get('known') and interior_mask(mask,p['xy'],size)]
    if depth:
        metadata,values,valid=depth
        usable=values[valid];span=float(np.percentile(usable,95)-np.percentile(usable,5)) if usable.size else 0.
        for point in reliable:
            value=sample(values,point['xy'],size);accepted=sample(valid.astype(float),point['xy'],size)
            if value is not None and accepted is not None and accepted>.99 and span>1e-5:
                point.update(depthSurfaceValue=float(value),depthConvention='white-far',depthRange=span,depthProvider=metadata['provider'],depthSource='estimated-surface-order')
        by_name={p['name']:p for p in reliable}
        for point in rows:
            if point['name'] in by_name:
                for key,value in by_name[point['name']].items():
                    if key.startswith('depth'):point[key]=value
    if supplied and supplied['convention'] in ('white-near','white-far'):
        import cv2
        values = supplied['values']
        owned = mask
        if owned.shape != values.shape:
            owned = cv2.resize(mask.astype(np.uint8), values.shape[::-1], interpolation=cv2.INTER_NEAREST_EXACT).astype(bool)
        # A small subject can occupy less than the 5th-to-95th percentile range of the frame.
        good = values[supplied['valid'] & owned]
        span = float(np.diff(np.percentile(good, [5, 95]))[0]) if len(good) else 0.
        for point in rows:
            if not point.get('known') or not interior_mask(mask,point['xy'],size) or span<=0:continue
            value=sample(supplied['values'],point['xy'],size);valid_value=sample(supplied['valid'].astype(float),point['xy'],size)
            if value is not None and valid_value is not None and valid_value>.99:
                point.update(depthSurfaceValue=float(value),depthConvention=supplied['convention'],depthRange=span,depthSource='provided-surface-order',depthProvider='Provided depth')
    if supplied and supplied['convention']=='camera-z' and supplied['normal'] is not None:
        import cv2
        values=supplied['values'];scale=float(supplied['scaleCm'])
        owned=cv2.resize(mask.astype(np.uint8),values.shape[::-1],interpolation=cv2.INTER_NEAREST_EXACT).astype(bool) if mask.shape!=values.shape else mask
        interior=values[supplied['normalValid'] & owned]
        metric_span=max(2./.12,float(np.diff(np.percentile(interior,[5,95]))[0])*scale) if len(interior) else 0.
        for point in rows:
            if not point.get('known') or not interior_mask(mask,point['xy'],size):continue
            value=sample(supplied['values'],point['xy'],size)
            continuous=sample(supplied['normalValid'],point['xy'],size)
            if value is not None and continuous:
                point.update(depthSurfaceValue=float(value),depthConvention='camera-z',depthScaleCm=scale,depthRange=metric_span,depthSource='provided-metric-surface',depthProvider='Provided depth')
    if normal:
        metadata,normals,valid=normal
        provider=metadata['provider']
    elif shade and shade.get('key'):
        loaded=load(root,shade['key'])
        if loaded:
            metadata,maps,valid=loaded;normals=np.moveaxis(maps[4:7],0,-1)*[1.,-1.,-1.];provider='ShadeNet-5-35M'
        else:normals=None
    else:normals=None
    by_name={p['name']:p for p in reliable}
    if normals is not None:
        for a,b in BODY_EDGES:
            if a not in by_name or b not in by_name:continue
            n=limb_normal(normals,valid,mask,by_name[a]['xy'],by_name[b]['xy'],size)
            if n is None:continue
            if abs(n[2])<.25:continue
            goals.append(dict(a=a,b=b,normalCamera=n.tolist(),provider=provider,weight=.15))
    notes.append('Surface guidance is in qualification. Surface orientation and depth ordering do not measure hidden joint centres.')
    return rows,goals,notes


def enrich(root,source,settings,summary,points=None,allow_cues=True,evidence=None):
    from measurements import canonical
    result=copy.deepcopy(source)
    if evidence is not None:
        rows,normals,notes=evidence
    elif allow_cues:
        rows,normals,notes=measurements(root,source['imageId'],points if points is not None else canonical(source),source['personKey'],settings['imageGuidance'],summary)
    else:rows,normals,notes=canonical(source),[],[]
    result['measurements']=rows if settings['imageGuidance'] in ('auto','detailed') else result.get('measurements')
    result['guidanceNormals']=normals
    applied=bool(allow_cues and summary.get('candidateComparison',{}).get('accepted'))
    prepared=bool(allow_cues and (normals or any(p.get('depthSource') for p in rows)))
    result['referenceEvidence']=dict(version=VERSION,imageGuidance=settings['imageGuidance'],geometryEngine=settings['geometryEngine'],
                                     mapKey=summary.get('key'),mapState=summary.get('state','off'),candidateComparison=summary.get('candidateComparison'),measurementComparison=summary.get('measurementComparison'),fallback=not allow_cues,
                                     prepared=prepared,applied=applied,
                                     outcome='applied' if applied else 'fallback' if not allow_cues else 'unchanged' if prepared else 'insufficient',
                                     applicationStage='accepted-source-candidate' if allow_cues and summary.get('candidateComparison',{}).get('accepted') else 'evidence-prepared' if allow_cues else 'original-source-retained',
                                     notes=list(dict.fromkeys([*summary.get('notes',[]),*notes])))
    from cache_provenance import stage_signature
    if not prepared and not applied:
        result=copy.deepcopy(source)|{'referenceEvidence':result['referenceEvidence']}
    key=signature(dict(source=source.get('refinementSignature'),person=source['personKey'],mhr=source['mhr'],settings=settings,evidence=result['referenceEvidence'],
                       measurements=result.get('measurements'),normals=normals,implementation=stage_signature(root,('worker/reference_guidance.py','worker/camera_depth.py'))))
    result['sourceGuidance']=dict(version=VERSION,id=key)
    path=image_dir(root,source['imageId'])/('guidance-source-'+key+'.json')
    if path.exists():
        if read_json(path)!=result:raise ValueError('Saved guidance evidence differs; the original extraction is retained')
    else:atomic_json(path,result)
    atomic_json(image_dir(root,source['imageId'])/('guidance-selected-'+source['personKey']+'-'+source.get('extractionMethod','smart')+'.json'),
                dict(version=VERSION,id=key,settings=settings))
    return result


def saved_source(folder,person,choice,context=None):
    from instances import identity
    selected=context
    if selected is None:
        selected=read_json(folder/('guidance-selected-'+identity(person)+'-'+choice+'.json'),{})
        root=folder.parents[2]
        if selected.get('settings')!=options(root):return None
    key=selected.get('id') if isinstance(selected,dict) else None
    if not isinstance(key,str) or len(key)!=64 or any(c not in '0123456789abcdef' for c in key):return None
    value=read_json(folder/('guidance-source-'+key+'.json'))
    if value and value.get('personKey')==identity(person) and value.get('extractionMethod')==choice and value.get('sourceGuidance',{}).get('id')==key:return value
    return None


def inspection(root,payload,progress):
    image_id=payload['imageId']
    map_quality=payload.get('mapQuality','standard')
    if map_quality not in ('standard','detailed'):raise ValueError('Choose standard or detailed image maps')
    provider=payload.get('provider','image');requested=payload.get('map','original')
    if provider not in ('image','geometry') or requested not in ('original','depth','normals','albedo'):raise ValueError('Unknown reference-map display')
    item=record(root,image_id);folder=image_dir(root,image_id)
    result=dict(version=VERSION,imageId=image_id,available=['original'],notes=[],evidence={})
    pixels=None
    if item['kind']!='photo':
        result['available'].append('depth');result['evidence']=dict(state='provided-depth',depthEncoding='provided-relative' if item['kind']=='relative-depth' else 'provided-camera-z')
        supplied=provided_depth(root,image_id)
        if requested=='depth' and supplied:
            values=supplied['values'];valid=supplied['valid'];good=values[valid]
            low,high=np.percentile(good,[2,98]) if len(good) else (0.,1.)
            grey=np.clip((values-low)/max(high-low,1e-6),0,1) if high>low else np.full(values.shape,.5)
            if supplied['convention'] in ('camera-z','white-far') or (supplied['convention']=='unknown' and item['kind']=='metric-depth'):grey=1-grey
            pixels=np.repeat(np.where(valid,grey*255,0)[...,None],3,axis=2)
        if supplied and supplied['normal'] is not None:
            result['available'].append('normals')
            if requested=='normals':pixels=(supplied['normal']*[1,-1,-1]+1)*127.5
        if requested=='normals' and pixels is not None:
            result['message']='Calibrated surface orientation. Hidden joint twist remains uncertain.'
        elif supplied and supplied['convention']=='unknown' and item['kind']=='relative-depth':
            result['message']='Declare whether brighter or darker pixels are nearer in Depth encoding. This preview shows the input intensity.'
        else:
            result['message']='Brighter pixels are nearer. The map describes visible surfaces. Calibrated metric input can also show surface normals.'
    elif provider=='image':
        summary=prepare(root,[image_id],'detailed' if map_quality=='detailed' else 'auto',progress).get(image_id,{})
        result.update(notes=summary.get('notes',[]),evidence=summary)
        loaded=load(root,summary.get('key'))
        if not loaded:result['message']='Optional image maps are unavailable. Your original reference and extraction are kept.'
        if loaded:
            _,maps,_=loaded;result['available']+=['depth','normals','albedo']
            if requested=='normals':pixels=(np.moveaxis(maps[4:7],0,-1)+1)*127.5
            elif requested=='albedo':pixels=(np.moveaxis(maps[:3],0,-1)+1)*127.5
            elif requested=='depth':pixels=np.repeat(((maps[3]+1)*127.5)[...,None],3,axis=2)
    else:
        from camera_depth import load as geometry_depth,load_normals
        name='MoGe-2'
        depth=geometry_depth(root,folder,provider=name);normal=load_normals(root,folder)
        result['evidence']=dict(state='ready' if depth or normal else 'not-prepared',provider=name,depthEncoding='camera-z-estimated-white-far',cacheHit=bool(depth or normal))
        if depth:
            result['available'].append('depth')
            if requested=='depth':
                _,values,valid=depth;good=values[valid]
                low,high=np.percentile(good,[2,98]) if len(good) else (0.,1.)
                grey=np.where(valid,(1-np.clip((values-low)/max(high-low,1e-6),0,1))*255,0)
                pixels=np.repeat(grey[...,None],3,axis=2)
        if normal:
            result['available'].append('normals')
            if requested=='normals':pixels=(normal[1]*[1,-1,-1]+1)*127.5
        if not depth and not normal:result['message']='Geometry maps are not prepared for this input. Extract the photograph first to prepare MoGe-2 maps.'
        elif requested=='depth':result['message']='Predicted camera-Z surface depth: brighter is nearer in this display. Physical scale is estimated.'
    if requested=='original':
        from storage import data_url
        with Image.open(folder/'source.png') as image:result['url']=data_url(image,(1024,1024))
    elif pixels is not None:
        image=Image.fromarray(np.clip(pixels,0,255).astype(np.uint8));image.thumbnail((1024,1024))
        stream=io.BytesIO();image.save(stream,'PNG');result['url']='data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode('ascii')
    elif 'message' not in result:result['message']='This map is unavailable for this input. Original extraction remains available.'
    return result

def normal_error(points,goal,rotation=None):
    axis=np.asarray(points[goal['b']])-points[goal['a']]
    if rotation is None:axis=axis*np.array([1.,-1.,-1.])
    else:axis=np.asarray(rotation)@axis
    return float(np.dot(axis,goal['normalCamera'])/max(np.linalg.norm(axis),1e-9))*goal.get('weight',.15)


def ordinal_pairs(points,maximum=16):
    rows=[p for p in points if p.get('known') and p.get('region')=='body' and p.get('depthRange',0)>0
          and p.get('depthSource') in ('estimated-surface-order','provided-surface-order','provided-metric-surface')]
    pairs=[]
    for index,a in enumerate(rows):
        for b in rows[index+1:]:
            convention=a.get('depthConvention')
            if convention!=b.get('depthConvention') or a.get('depthScaleCm')!=b.get('depthScaleCm'):continue
            difference=(a['depthSurfaceValue']-b['depthSurfaceValue'])*a.get('depthScaleCm',1.)
            threshold=max(a.get('depthRange',0),b.get('depthRange',0))*.12
            if threshold<=0 or abs(difference)<threshold or np.linalg.norm(np.asarray(a['xy'])-b['xy'])<12:continue
            near,far=(a,b) if (difference<0)==(convention in ('white-far','camera-z')) else (b,a)
            pairs.append((near['name'],far['name']))
            if len(pairs)>=maximum:return pairs
    return pairs


def supplemental_measurements(root,source,summary):
    """Reuse existing RGB/hand detectors; albedo is only an alternate 2D hypothesis."""
    from wholebody import Landmarker,available
    from measurements import canonical
    points=canonical(source)
    if not available(root):return points,dict(rgb=False,albedo=False,added=0)
    folder=image_dir(root,source['imageId']);people=read_json(folder/'people.json',[])
    person=next((p for p in people if p['id']==source['personId']),None)
    if person is None:return points,dict(rgb=False,albedo=False,added=0)
    others=[p for p in people if p['id']!=person['id']]
    mask=owned_mask(root,source['imageId'],source['personKey'])
    if mask is None:return points,dict(rgb=False,albedo=False,added=0)
    size=source['imageSize'];height=max(24.,source['personBox'][3]-source['personBox'][1])
    landmarker=Landmarker(root);diagnostic=dict(rgb=False,albedo=False,added=0)
    try:
        with Image.open(folder/'source.png') as image:pixels=np.asarray(image.convert('RGB'))
        measured=landmarker.measure(pixels,person,others,lambda *_:None) if source.get('measurements') is None else copy.deepcopy(source['measurements'])
        diagnostic['rgb']=True
        by_name={p['name']:copy.deepcopy(p) for p in points}
        def merge(candidates,origin):
            owners={p['name']:p for p in candidates if p.get('known')}
            for point in candidates:
                previous=by_name.get(point['name'])
                if previous and (previous.get('known') or previous.get('provenance')=='user'):continue
                if not point.get('known') or point.get('weight',0)<.75 or not interior_mask(mask,point['xy'],size):continue
                if 'hand' in point.get('region',''):
                    wrist=owners.get(point['name'][0]+'_wrist')
                    anchor=by_name.get(point['name'][0]+'_wrist')
                    if not wrist or not anchor or not anchor.get('known') or np.linalg.norm(np.asarray(wrist['xy'])-anchor['xy'])>height*.05:continue
                by_name[point['name']]=dict(point,secondaryImage=origin)
        merge(measured,'original-rgb')
        missing_hands=sum(p.get('known',False) for p in measured if 'hand' in p.get('region',''))<20
        packed=load(root,summary.get('key'))
        if missing_hands and packed:
            _,maps,_=packed
            albedo=np.clip((np.moveaxis(maps[:3],0,-1)+1)*127.5,0,255).astype(np.uint8)
            factor=np.array([albedo.shape[1]/size[0],albedo.shape[0]/size[1]])
            def scaled(p):
                p=copy.deepcopy(p);p['box']=(np.asarray(p['box'])*np.tile(factor,2)).tolist()
                p['keypoints']=[[*((np.asarray(v[:2])+.5)*factor-.5),v[2]] for v in p.get('keypoints',[])]
                return p
            candidates=landmarker.measure(albedo,scaled(person),[scaled(p) for p in others],lambda *_:None)
            for point in candidates:point['xy']=((np.asarray(point['xy'])+.5)/factor-.5).tolist()
            merge(candidates,'albedo');diagnostic['albedo']=True
        rows=list(by_name.values());diagnostic['added']=sum(p.get('known',False) and not next((old.get('known',False) for old in points if old['name']==p['name']),False) for p in rows)
        return rows,diagnostic
    finally:landmarker.sessions.clear()


def source_score(source,points,normals=()):
    from measurements import MHR
    groups={}
    projected=np.asarray(source['projectedKeypoints'])
    for point in points:
        index=MHR.get(point['name'])
        if not point.get('known') or index is None or index>=len(projected):continue
        groups.setdefault(point['region'],[]).append(float(np.linalg.norm(projected[index]-point['xy'])))
    if len(groups.get('body',[]))<4:return dict(score=None,body=None,regions={})
    height=max(24.,source['personBox'][3]-source['personBox'][1])
    regional={name:float(np.mean(values)) for name,values in groups.items()}
    score=float(np.mean([value/max(2.,height*(.02 if name=='body' else .01)) for name,value in regional.items()]))
    camera=np.asarray(source['keypoints3d'])*[1.,-1.,-1.]
    for near,far in ordinal_pairs(points):
        if near in MHR and far in MHR:score+=max(0.,camera[MHR[near],2]-camera[MHR[far],2]-.15)*.1
    for goal in normals:
        if goal['a'] in MHR and goal['b'] in MHR:
            axis=camera[MHR[goal['b']]]-camera[MHR[goal['a']]]
            score+=abs(float(np.dot(axis,goal['normalCamera'])))/max(np.linalg.norm(axis),1e-9)*.05
    return dict(score=score,body=regional['body'],regions=regional)


def candidate_is_better(original,candidate,points,normals=(),trusted=None):
    before,after=source_score(original,points,normals),source_score(candidate,points,normals)
    accepted_hands=all(not values.get('accepted') or candidate.get('handAcceptance',{}).get(side,{}).get('accepted')
                       for side,values in original.get('handAcceptance',{}).items())
    if trusted is None:
        trusted_before,trusted_after=before['regions'],after['regions']
    else:
        trusted_before=source_score(original,trusted)['regions']
        trusted_after=source_score(candidate,trusted)['regions']
    # Compare both candidates to the same trusted observations. New albedo
    # hypotheses cannot hide a regression on a previously measured region.
    preserved_regions=all(region in trusted_after and trusted_after[region]<=error+max(.5,error*.02)
                          for region,error in trusted_before.items())
    better=before['score'] is not None and after['score'] is not None and after['score']<before['score']*.98
    accepted=bool(better and accepted_hands and preserved_regions)
    return accepted,dict(before=before,after=after,accepted=accepted,
                         handAcceptancePreserved=accepted_hands,trustedRegionsPreserved=preserved_regions)


def provided_depth(root,image_id,camera=None,convention=None,scale_cm=None):
    """Keep raw depth values; physical normals require calibrated camera-Z."""
    import cv2
    from PIL import ImageOps
    folder=image_dir(root,image_id);meta=read_json(folder/'image.json',{})
    if current_reference(meta) and meta.get('referenceOriginal'):
        base=root/'data/reference-assets'/meta['referenceOriginal'];asset=read_json(base/'asset.json',{});path=(base/asset.get('file','missing')).resolve()
    else:return None
    if not path.is_relative_to(base.resolve()) or not path.is_file():return None
    reference=meta.get('referenceDepth',{})
    kind=asset.get('kind',meta.get('inputKind'))
    camera=camera or reference.get('camera')
    scale_cm=scale_cm if scale_cm is not None else reference.get('scaleCm')
    convention=convention or reference.get('encoding') or meta.get('depthConvention','unknown')
    with Image.open(path) as opened:
        ImageOps.exif_transpose(opened,in_place=True)
        size=list(opened.size);factor=min(1.,768/max(size));small_size=(max(1,round(size[0]*factor)),max(1,round(size[1]*factor)))
        alpha_image=opened.getchannel('A') if 'A' in opened.getbands() else opened.convert('RGBA').getchannel('A') if 'transparency' in opened.info else None
        alpha=np.asarray(alpha_image.resize(small_size,Image.Resampling.NEAREST))>0 if alpha_image is not None else np.ones(small_size[::-1],dtype=bool)
        image=opened.convert('L') if opened.mode in ('RGB','RGBA','P','LA') else opened
        values=np.asarray(image.resize(small_size,Image.Resampling.NEAREST),dtype=np.float32)
    if convention=='ray-distance':
        if not camera or camera.get('projection')!='perspective' or camera.get('metricScale') is not True or camera.get('provenance')!='calibrated':
            raise ValueError('Ray-distance depth requires a calibrated perspective camera with known scale.')
        convention='camera-z'
        yy,xx=np.indices(values.shape,dtype=float)
        uv=np.stack(((xx+.5)*size[0]/values.shape[1]-.5,(yy+.5)*size[1]/values.shape[0]-.5,np.ones_like(xx)),axis=-1)
        rays=uv@np.linalg.inv(np.asarray(camera['intrinsics'])).T
        values=values/np.linalg.norm(rays,axis=-1)
    valid=np.isfinite(values)&alpha
    if convention=='camera-z' or kind=='metric-depth':valid&=values>0
    normals=None
    if convention=='camera-z' and scale_cm and camera and camera.get('metricScale') is True and camera.get('provenance')=='calibrated' and min(values.shape)>=3:
        yy,xx=np.indices(values.shape,dtype=float)
        uv=np.stack(((xx+.5)*size[0]/values.shape[1]-.5,(yy+.5)*size[1]/values.shape[0]-.5,np.ones_like(xx)),axis=-1)
        rays=uv@np.linalg.inv(np.asarray(camera['intrinsics'])).T
        scale=float(scale_cm)
        if not np.isfinite(scale) or scale<=0:raise ValueError('Metric depth needs a finite positive centimetre scale')
        z=np.where(valid,values*scale,0.)
        points=rays*z[...,None] if camera['projection']=='perspective' else np.dstack((rays[...,:2],z))
        vertical,horizontal=np.gradient(points,axis=(0,1))
        normals=np.cross(horizontal,vertical)
        lengths=np.linalg.norm(normals,axis=-1)
        neighbours=cv2.erode(valid.astype(np.uint8),np.ones((3,3),np.uint8))>0
        extent=cv2.dilate(z,np.ones((3,3),np.uint8))-cv2.erode(z,np.ones((3,3),np.uint8))
        normal_valid=neighbours&(lengths>1e-8)&np.isfinite(normals).all(axis=-1)&(extent<np.maximum(2.,z*.03))
        normal_valid[[0,-1],:]=False;normal_valid[:,[0,-1]]=False
        normals=np.where(normal_valid[...,None],normals/np.maximum(lengths[...,None],1e-8),0)
        normals*=np.where(normals[...,2:3]>0,-1,1)
    return dict(values=values,valid=valid,normal=normals,size=size,convention=convention,
                normalValid=normal_valid if normals is not None else None,provider='Provided depth',scaleCm=scale_cm)
