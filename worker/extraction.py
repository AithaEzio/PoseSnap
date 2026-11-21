"""Extraction policy and cache partitioning; safe to import before neural runtimes."""
import hashlib, json
from storage import read_json

PURE_VERSION = 1

def method(value='smart'):
    if value not in ('pure','smart'):raise ValueError('Choose Pure or Genesis Smart Fit extraction.')
    return value

def preference(value='auto'):
    if value not in ('auto','pure','smart'):raise ValueError('Choose Auto, Pure or Genesis Smart Fit extraction.')
    return value

def selected(root,payload,interaction=False):
    context=payload.get('extractionContext','single')
    if context not in ('single','interaction'):raise ValueError('Unknown extraction context.')
    choice=preference(payload.get('extractionMethod',read_json(root/'data/settings.json',{}).get('extractionMethod','auto')))
    return ('smart' if interaction or context=='interaction' else 'pure') if choice=='auto' else choice

def result_path(folder,kind,choice='smart'):
    return folder/(f'{kind}-pure.json' if method(choice)=='pure' else f'{kind}.json')

def pure_signature(root):
    from cache_provenance import provenance
    return provenance(root)

def cache_matches(source,choice):
    return source.get('extractionMethod','smart')==method(choice) and (choice!='pure' or source.get('pureVersion')==PURE_VERSION)

def extraction_pose(source,pose):
    """Add provenance and a shared reference camera, without optimizing channels."""
    import numpy as np
    from interaction import geometry,camera_translation
    from retarget import source_map
    from measurements import reference_camera
    pose['extractionMethod']=source.get('extractionMethod','smart')
    if source.get('sourceGuidance'):pose['sourceGuidance']=dict(source['sourceGuidance'])
    if source.get('referenceEvidence'):
        import copy
        pose['referenceEvidence']=copy.deepcopy(source['referenceEvidence'])
        pose['warnings']=list(dict.fromkeys([*pose['warnings'],*source['referenceEvidence'].get('notes',[])]))
    if source.get('sourceDiagnostics'):
        import copy
        from body_uncertainty import note
        pose['sourceDiagnostics']=copy.deepcopy(source['sourceDiagnostics'])
        pose['warnings']=list(dict.fromkeys([*pose['warnings'],*(note(d) for d in pose['sourceDiagnostics'])]))
    if pose['extractionMethod']!='pure':return pose
    positions,_,height=geometry(pose)
    scale=height/max(60.,float(np.ptp(np.asarray(source['restPositions'])[:,1]))*100)
    hip=np.asarray(source['positions'][source_map(source['names'])['hip']])*100*scale
    camera_root=camera_translation(source['cameraTranslation'])*scale+hip-positions['hip' if 'hip' in positions else 'pelvis']
    pose['referenceCamera']=reference_camera(source,camera_root-np.asarray(pose['translation']))
    # The sparse detector score is source-stage agreement, never final 2D fit.
    visible=source.get('quality',{}).get('visible',{})
    count=visible.get('count',0)
    box=source.get('personBox',[0,0,0,source['imageSize'][1]])
    height=max(24.,box[3]-box[1])
    body=dict(matched=visible.get('matched'),count=count,expected=12,tolerancePx=visible.get('threshold',.05)*height,
              meanErrorPx=visible['meanError']*height if visible.get('meanError') is not None else None)
    pose['quality']=dict(source.get('quality',{}),stage='source',regions={'body':body},coverage=dict(observed=count,expected=12),
                         handAcceptance=source.get('handAcceptance'),depth='SAM-only depth estimate; inspect the side view.')
    return pose
