"""Version 1 JSON-lines worker. Heavy imports are deferred; idle exit frees CUDA memory."""
import argparse, base64, contextlib, json, os, shutil, sys, time, traceback
from pathlib import Path

# Windows redirected pipes otherwise use the host ANSI code page. UTF-8 is
# required for relocated folders and references with non-ASCII filenames.
for stream in (sys.stdin,sys.stdout,sys.stderr):
    stream.reconfigure(encoding='utf-8')
parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);args=parser.parse_args()
ROOT=Path(args.root).resolve()
for key,relative in {'TEMP':'temp','TMP':'temp','HF_HOME':'data/cache/huggingface','TORCH_HOME':'data/cache/torch','CUDA_CACHE_PATH':'data/cache/cuda','MPLCONFIGDIR':'data/cache/matplotlib','XDG_CACHE_HOME':'data/cache'}.items():
    os.environ[key]=str(ROOT/relative);(ROOT/relative).mkdir(parents=True,exist_ok=True)
os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',MOMENTUM_ENABLED='0',PYTHONNOUSERSITE='1')
if hasattr(os,'add_dll_directory'):
    # Numerical packages register their own private DLL directories on import.
    DLL_HANDLES=[os.add_dll_directory(str(ROOT/'runtime/native'))] if (ROOT/'runtime/native').is_dir() else []
from storage import atomic_json, read_json, import_image, history, image_dir, data_url, current_reference

PIPE=sys.stdout
def send(value):
    PIPE.write(json.dumps(value,ensure_ascii=False,allow_nan=False)+'\n');PIPE.flush()

def status():
    from rigs import available_profiles, connected_profiles
    from detection import model_path
    models={'detector':'detection/yolox_s.onnx','body':'body/model.ckpt','bodyRig':'body/assets/mhr_model.pt','camera':'camera/model.pt','segmentation':'segmentation/sam2.1_hiera_tiny.pt'}
    available={key:(ROOT/'models'/path).is_file() for key,path in models.items()}
    detector_path,detector=model_path(ROOT)
    available['detector']=detector_path.is_file()
    original=read_json(ROOT/'data/settings.json',{})
    from wholebody import available as refinement_available, signature
    acceptance=read_json(ROOT/'data/benchmarks/refinement-acceptance.json',{})
    validated=acceptance.get('passed') is True and acceptance.get('modelSignature')==signature(ROOT) and acceptance.get('referenceCount',0)>=40
    from text_settings import settings as text_settings
    settings=dict(theme=original.get('theme','dark'),motion=original.get('motion','auto'),jointSelector=original.get('jointSelector','buttons'),dazExecutable=original.get('dazExecutable',''),onboarded=original.get('onboarded',False),historyLimit=original.get('historyLimit',40),refinement='accurate',extractionMethod=original.get('extractionMethod','auto'),clueEnabled=original.get('clueEnabled',False) is True,zeroCroppedJoints=original.get('zeroCroppedJoints',True) if type(original.get('zeroCroppedJoints',True)) is bool else True,**text_settings(ROOT))
    from reference_guidance import options as guidance_options
    settings['imageGuidance'] = guidance_options(ROOT)['imageGuidance']
    settings['depthInputType']='metric' if original.get('depthInputType')=='metric' else 'relative'
    available['refinement']=refinement_available(ROOT)
    if settings!=original:atomic_json(ROOT/'data/settings.json',settings)
    build=read_json(ROOT/'manifests/build-receipt.json',{})
    version=build.get('applicationVersion') or read_json(ROOT/'package.json',{}).get('version','unknown')
    return dict(version=version,root=str(ROOT),models=available,detector=detector,ready=all(v for k,v in available.items() if k!='refinement' or settings['extractionMethod']!='pure'),rigs=available_profiles(ROOT),connectedRigs=connected_profiles(ROOT),settings=settings,python=sys.version.split()[0],offline=True,refinement=dict(available=refinement_available(ROOT),validated=validated))

ENGINE=None
KIMODO=None
def dispatch(method,payload,progress):
    global ENGINE,KIMODO
    if method=='reference_depth':
        from reference_depth import settings
        return settings(ROOT,payload)
    if method=='guidance_inspect':
        from reference_guidance import inspection
        return inspection(ROOT,payload,progress)
    if method.startswith('text_'):
        if ENGINE is not None:ENGINE.release();ENGINE=None
        from kimodo_runtime import Runtime as KimodoRuntime
        if KIMODO is None:KIMODO=KimodoRuntime(ROOT)
        def text_status():
            from qualification import records
            from text_settings import settings
            return dict(version=2, settings=settings(ROOT), kimodo=KIMODO.status(), capabilities=records())
        import textpose
        if method=='text_status':return text_status()
        if method=='text_kimodo_load':KIMODO.load(progress);return text_status()
        if method=='text_kimodo_unload':KIMODO.unload();return text_status()
        if method=='text_accept':return textpose.accept(ROOT,payload)
        if method in ('text_read','text_remove'):
            import re
            key=payload.get('id','')
            if not re.fullmatch(r'text-[a-f0-9]{32}',key):raise ValueError('Invalid text history identifier')
            path=ROOT/'data/text'/f'{key}.json'
            if method=='text_remove':path.unlink(missing_ok=True);return True
            value=read_json(path)
            if not value:raise ValueError('The saved text result is unavailable')
            return value
        if method in ('text_export','text_apply'):
            from textoutput import output
            return output(ROOT,payload,progress,apply=method=='text_apply')
        if method in ('text_plan','text_generate'):
            context=textpose.capability(ROOT,payload)
            if method=='text_plan':
                from kimodo_generation import plan
                variation=textpose.variation_source(ROOT,payload)
                intent=variation['intent'] if variation else plan(ROOT,payload,context,None,progress)
                return dict(intent=intent,contextSignature=textpose.signature(context),runtime=text_status(),interpreter='kimodo')
            if payload.get('contextSignature')!=textpose.signature(context):raise ValueError('Actors or generation options changed. Preview this instruction again.')
            from kimodo_generation import generate
            return generate(ROOT,dict(payload,_interpreter='kimodo'),payload['intent'],KIMODO,progress)
        raise ValueError('This Text to Pose operation is no longer available.')
    if method=='health':
        # Exercise the private numerical imports and one CUDA operation, without
        # loading neural weights. A filename check cannot prove engine usability.
        import numpy, scipy, cv2, onnxruntime, torch, torchvision, yaml
        from PIL import Image
        if not torch.cuda.is_available():raise ValueError('No supported NVIDIA GPU is available. Check your graphics driver; PoseSnap does not install it.')
        name=torch.cuda.get_device_name(0)
        torch.ones(1,device='cuda').sum().item()
        return dict(gpu=name,python=sys.version.split()[0])
    if method=='status':return status()
    if method=='settings':
        from text_settings import DEFAULTS, validate as validate_text_settings
        current=status()['settings'];current.update({k:v for k,v in payload.items() if k in ('theme','motion','jointSelector','dazExecutable','onboarded','historyLimit','refinement','extractionMethod','clueEnabled','zeroCroppedJoints','imageGuidance','depthInputType',*DEFAULTS)})
        if current.get('depthInputType') not in ('relative','metric'):raise ValueError('Choose Relative or Metric depth input')
        if current.get('theme') not in ('dark','neon','light'):raise ValueError('Unknown theme')
        if type(current.get('clueEnabled')) is not bool:raise ValueError('Invalid CLUE preference')
        if type(current.get('zeroCroppedJoints')) is not bool:raise ValueError('Invalid zero cropped joints preference')
        if current.get('motion') not in ('auto','reduced'):raise ValueError('Unknown motion preference')
        if current.get('jointSelector') not in ('buttons','map'):raise ValueError('Unknown joint selector')
        # Older clients/preferences are migrated, never a silent weaker solve.
        if current.get('refinement') not in ('standard','accurate'):raise ValueError('Unknown extraction refinement')
        from extraction import preference as extraction_method
        current['extractionMethod']=extraction_method(current.get('extractionMethod','auto'))
        current['refinement']='accurate'
        from reference_guidance import options as guidance_options
        current['imageGuidance'] = guidance_options(ROOT, current)['imageGuidance']
        validate_text_settings(current)
        atomic_json(ROOT/'data/settings.json',current);return current
    if method=='import_image':return import_image(ROOT,payload)
    if method in ('expression_profiles','connect_expression_figure','retarget_expression','save_expression','read_expression','export_expression','apply_expression','zero_expression'):
        # Face work must not extend the lifetime of the previous CUDA pose model.
        if ENGINE is not None:
            ENGINE.release();ENGINE=None
        import expression
        if method=='expression_profiles':return {rig:expression.profile(ROOT,rig) for rig in ('g8f','g8m','g9') if (ROOT/'data/face-profiles'/f'{rig}.json').is_file() and read_json(ROOT/'data/face-profiles'/f'{rig}.json',{}).get('mappingVersion') in (3,4,5,6,7,8,9)}
        if method=='connect_expression_figure':return expression.handoff(ROOT,payload,progress,connect=True)
        if method=='retarget_expression':return expression.retarget(ROOT,payload)
        if method=='save_expression':return expression.save(ROOT,payload)
        if method=='read_expression':return expression.read(ROOT,payload)
        if method=='export_expression':return expression.export(ROOT,payload)
        if method=='apply_expression':return expression.handoff(ROOT,payload,progress)
        if method=='zero_expression':return expression.handoff(ROOT,payload,progress,zero=True)
    if method=='history':
        from editor import pose_history
        from expression import history as expression_history
        references=history(ROOT)
        from textpose import history as text_history
        return sorted(references+pose_history(ROOT,references)+expression_history(ROOT)+text_history(ROOT),key=lambda row:row['created'],reverse=True)
    if method=='read_image':
        from PIL import Image
        folder=image_dir(ROOT,payload['imageId']);meta=read_json(folder/'image.json')
        if not current_reference(meta):raise ValueError('This reference is unavailable in the current build.')
        people=read_json(folder/'people.json',[])
        history_result=None
        if payload.get('restorePose') is True:
            from storage import restore_history
            history_result=restore_history(ROOT,folder,people,payload.get('rigId','g8f'))
        with Image.open(folder/'source.png') as image:
            return dict(meta,url=data_url(image),people=people,historyResult=history_result)
    if method=='remove_history':
        if payload.get('kind')=='expression':
            from expression import remove
            return remove(ROOT,payload)
        from editor import session_folder
        folder=session_folder(ROOT,payload['imageId'])
        if not payload['imageId'].startswith('pose-'):
            meta=read_json(folder/'image.json')
            if meta and not current_reference(meta):
                raise ValueError('This reference is unavailable in the current build.')
        if payload.get('kind')=='pose' and not payload['imageId'].startswith('pose-'):
            (folder/'editor-draft.json').unlink(missing_ok=True)
        elif folder.is_dir():shutil.rmtree(folder)
        return True
    if method=='connect_figure':
        from daz import connect_figure
        return connect_figure(ROOT,payload,progress)
    if method=='detect':
        if KIMODO is not None:KIMODO.release()
        from detection import detect
        if ENGINE is not None:ENGINE.release()
        return detect(ROOT,payload,progress)
    if method=='solve':
        if 'prepareInteraction' in payload and type(payload['prepareInteraction']) is not bool:raise ValueError('Invalid interaction preparation')
        if payload.get('prepareInteraction') and payload.get('extractionContext')!='interaction':raise ValueError('Use interaction context when preparing participants')
        if KIMODO is not None:KIMODO.release()
        if ENGINE is None:
            from inference import Inference
            ENGINE=Inference(ROOT)
        source=ENGINE.solve(payload,lambda label,percent:progress(label,round(percent*.7)))
        if source.get('version') in (2,3) and not source.get('sourceGuidance'):source=dict(source,sourceGuidance=dict(version=1,id='original'))
        if payload.get('prepareInteraction'):
            # These intermediate previews were discarded by the UI. Fit the
            # participants together once, after all sources are ready.
            return dict(personId=source['personId'],sourceReady=True,executionTimings=getattr(ENGINE,'timings',{}),**({'sourceGuidance':source['sourceGuidance']} if source.get('sourceGuidance') else {}))
        from cropped import prepare
        baseline_source=source
        source=prepare(ROOT,source,payload)
        from cropped import adjust_accepted
        adjusted=adjust_accepted(ROOT,image_dir(ROOT,source['imageId']),[baseline_source],[source],payload)
        if adjusted:
            from posture import persist_baseline
            pose=adjusted['poses'][0];pose['executionTimings']=dict(getattr(ENGINE,'timings',{}),**adjusted['executionTimings'])
            folder=image_dir(ROOT,source['imageId'])
            persist_baseline(folder,[baseline_source],[pose])
            from storage import remember_history
            return remember_history(folder,pose,baseline_source,progress)
        from rigs import profile
        from retarget import retarget
        pose=retarget(source,profile(ROOT,payload['rigId']))
        from time import perf_counter
        target_started=perf_counter()
        from coupled import fit_targets
        pose=fit_targets([source],[pose],progress=progress,preserve=True)['poses'][0] if source.get('refinementMode')=='accurate' else pose
        pose['executionTimings']=dict(getattr(ENGINE,'timings',{}),targetFitSeconds=perf_counter()-target_started)
        from posture import persist_baseline
        folder=image_dir(ROOT,source['imageId'])
        persist_baseline(folder,[baseline_source],[pose])
        from storage import remember_history
        return remember_history(folder,pose,baseline_source,progress)
    if method=='refine':
        if KIMODO is not None:KIMODO.release()
        if ENGINE is not None:ENGINE.release()
        if payload.get('operation')=='spacing':
            from spacing import transaction
            if ENGINE is None:
                from inference import Inference
                ENGINE=Inference(ROOT)
            return transaction(ROOT,payload,progress,ENGINE.camera)
        from refinement import refine
        return refine(ROOT,payload,progress)
    if method=='retarget':
        if 'editorOperation' in payload:
            from editor import operation
            return operation(ROOT,payload,progress)
        if 'members' in payload:
            if ENGINE is not None:ENGINE.release()
            from interaction import assemble
            return assemble(ROOT,payload,progress)
        from rigs import profile
        from retarget import retarget
        from instances import cached_source
        folder=image_dir(ROOT,payload['imageId'])
        person=next((p for p in read_json(folder/'people.json',[]) if p['id']==payload['personId']),None)
        from extraction import selected
        choice=selected(ROOT,payload)
        source=cached_source(folder,person,choice,context=payload.get('sourceGuidance')) if person else None
        if source is None:raise ValueError('Extract this selected person again; an older detection result cannot be reused.')
        baseline_source=source
        from refinement import accepted_result
        accepted=accepted_result(ROOT,folder,choice=choice)
        if accepted and (len(accepted.get('poses',[]))!=1 or accepted['poses'][0].get('personId')!=payload['personId'] or len((accepted['poses'][0].get('layout') or {}).get('personIds',[]))>1):accepted=None
        from cropped import prepare, enabled as crop_enabled, SIGNATURE as CROP_SIGNATURE
        if accepted and any(p.get('cropPolicy',{}).get('enabled',False)!=crop_enabled(ROOT,payload,source) or (p.get('cropPolicy',{}).get('enabled') and p['cropPolicy'].get('signature')!=CROP_SIGNATURE) for p in accepted['poses']):accepted=None
        if accepted:
            previous=next((p for p in accepted['poses'] if p['personId']==payload['personId']),None)
            if previous and previous['rigId']==payload['rigId']:
                from storage import remember_history
                return remember_history(folder,previous,baseline_source,progress)
            source=next((s for s in accepted['refinementSources'] if s['personId']==payload['personId']),source)
        if not accepted:source=prepare(ROOT,source,payload,person)
        pose=retarget(source,profile(ROOT,payload['rigId']))
        if source.get('extractionMethod','smart')=='smart' and (accepted or source.get('refinementMode')=='accurate'):
            from coupled import fit_targets
            pose=fit_targets([source],[pose],progress=progress,preserve=True)['poses'][0]
        from posture import persist_baseline
        persist_baseline(folder,[baseline_source],[pose],'converted-current' if accepted else 'extraction')
        from storage import remember_history
        return remember_history(folder,pose,baseline_source,progress)
    if method=='export':
        from daz import export
        return export(ROOT,payload)
    if method=='apply':
        from daz import apply
        return apply(ROOT,payload,progress)
    raise ValueError('Unknown operation')

pending=b''
if os.name=='nt':
    import ctypes, msvcrt
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.PeekNamedPipe.argtypes=[wintypes.HANDLE,ctypes.c_void_p,wintypes.DWORD,ctypes.c_void_p,ctypes.POINTER(wintypes.DWORD),ctypes.c_void_p]
    kernel.PeekNamedPipe.restype=wintypes.BOOL
    kernel.ReadFile.argtypes=[wintypes.HANDLE,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD),ctypes.c_void_p]
    kernel.ReadFile.restype=wintypes.BOOL
    input_handle=msvcrt.get_osfhandle(sys.stdin.fileno())

def next_request():
    """Wait up to 60 seconds without a concurrent stdin reader (NumPy #24290)."""
    global pending
    deadline=time.monotonic()+(180 if KIMODO is not None and KIMODO.encoder is not None else 60)
    if os.name!='nt':
        import select
        if not select.select([sys.stdin],[],[],60)[0]:return None
        return sys.stdin.readline() or None
    available=wintypes.DWORD();count=wintypes.DWORD();buffer=ctypes.create_string_buffer(65536)
    while True:
        if b'\n' in pending:
            line,pending=pending.split(b'\n',1)
            return line.decode('utf-8')
        if not kernel.PeekNamedPipe(input_handle,None,0,None,ctypes.byref(available),None):return None
        if available.value:
            if not kernel.ReadFile(input_handle,buffer,min(len(buffer),available.value),ctypes.byref(count),None):return None
            pending+=buffer.raw[:count.value]
            if len(pending)>16*1024*1024:raise ValueError('Worker request is too large')
        elif time.monotonic()>=deadline:return None
        else:
            if KIMODO is not None:KIMODO.idle()
            time.sleep(.025)

while True:
    line=next_request()
    if line is None:break
    job_id=None
    try:
        request=json.loads(line);job_id=request['jobId']
        if not isinstance(job_id,str) or not job_id or len(job_id)>79 or not job_id.replace('-','').isalnum():raise ValueError('Invalid job identifier')
        if request.get('version')!=1:raise ValueError('Unsupported worker protocol')
        def progress(label,percent):
            if (ROOT/'temp/jobs'/f'{job_id}.cancel').exists():raise InterruptedError('Cancelled. The previous accepted result is preserved.')
            send(dict(version=1,type='progress',jobId=job_id,label=label,percent=percent))
        with contextlib.redirect_stdout(sys.stderr):
            result=dispatch(request['method'],request.get('payload',{}),progress)
        send(dict(version=1,type='result',jobId=job_id,result=result))
    except Exception as error:
        traceback.print_exc(file=sys.stderr)
        message=str(error)
        if 'out of memory' in message.lower():
            message='GPU memory is full. Close other GPU apps, then retry. The image and earlier results are preserved.'
            if ENGINE is not None:ENGINE.release()
        send(dict(version=1,type='error',jobId=job_id,message=message))
