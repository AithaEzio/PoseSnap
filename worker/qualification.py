"""Per-workflow evidence, deliberately independent of engine loading/health."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GROUPS={
    'pose':('Body composition',('textpose','pose_design','soma','kimodo_generation','body_contacts','textsolve','contact_geometry','textconstraints','instructions','hand_design')),
    'floor':('Seating and floor support',('soma','body_contacts','pose_design','kimodo_generation')),
    'interaction':('Partner contacts',('textsolve','contact_geometry','hand_design','textconstraints','instructions','measurements')),
    'clue-body':('Body uncertainty',('body_uncertainty','inference')),
    'relative-spacing':('Refine spacing',('camera_depth','spacing','measurements','segmentation','posture')),
}


def signature(capability, root=ROOT):
    if capability not in GROUPS:raise ValueError('Unknown qualification capability')
    shared=('textpose','textconstraints','instructions','rigs','retarget','studio','measurements') if capability not in ('clue-body','relative-spacing') else ()
    paths=[root/'worker'/(p+'.py') for p in dict.fromkeys((*GROUPS[capability][1],*shared))]
    if capability not in ('clue-body','relative-spacing'):
        paths += [root/'worker'/(p+'.py') for p in ('text_settings','runtime_process','body_profiles','kimodo_runtime')]
        paths += [root/'worker/kimodo-components.json']
    paths += [root/'assets.lock.json']
    if capability=='clue-body':
        paths += [root/'licenses/clue/source.json',root/'worker/diagnostic-components.json',root/'models/diagnostics/clue/sam3dbody_clue.safetensors']
        paths += sorted((root/'worker/sam3dbody_clue').rglob('*.py'))
    values=[(p.relative_to(root).as_posix(),hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None) for p in paths]
    return hashlib.sha256(json.dumps([1,values],sort_keys=True).encode()).hexdigest()


def records(root=ROOT):
    from storage import read_json
    evidence=read_json(root/'worker/capability-qualification.json',{}).get('capabilities',{})
    result=[]
    for key,(label,_) in GROUPS.items():
        value=evidence.get(key,{})
        compatible=value.get('componentSignature')==signature(key,root)
        status=value.get('status','experimental') if compatible else 'experimental'
        if status not in ('qualified','experimental','unavailable'):status='experimental'
        result.append(dict(id=key,label=label,status=status,compatible=compatible,componentSignature=signature(key,root),
                           evidenceRevision=value.get('evidenceRevision'),scope=value.get('scope','Qualification pending for this workflow.'),
                           limits=value.get('limits',[]) if compatible else ['Changed components need fresh evidence before promotion.'],
                           recordedStatus=value.get('status','unreviewed')))
    return result


def generation_signature():
    return hashlib.sha256(json.dumps([signature(k) for k in ('pose','floor','interaction')],sort_keys=True).encode()).hexdigest()
