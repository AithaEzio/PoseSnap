"""Bounded local MHR refinement and transactional guided corrections."""
import copy, gc, time
import numpy as np
from storage import image_dir, read_json, atomic_json, bind_people
from instances import cached_source, source_path
from extraction import result_path, selected
from measurements import MHR, canonical, overrides, stamp

def refine_sources(root,sources,contacts,progress=lambda *_:None,start=88,end=94):
    """Freeze identity/scale; fit pose and shared-camera translations, not meshes."""
    import torch
    import roma
    if not all(s.get('mhr') for s in sources):return sources
    device='cuda' if torch.cuda.is_available() else 'cpu'
    with (root/'models/body/assets/mhr_model.pt').open('rb') as stream:model=torch.jit.load(stream,map_location=device).eval()
    for p in model.parameters():p.requires_grad_(False)
    tensor=lambda x:torch.tensor(x,dtype=torch.float32,device=device)
    base=tensor([s['mhr']['modelParams'] for s in sources]);shape=tensor([s['mhr']['shapeParams'] for s in sources]);expr=tensor([s['mhr']['exprParams'] for s in sources])
    angles=base[:,3:136].clone().requires_grad_(True);cam=tensor([s['cameraTranslation'] for s in sources]);shift=torch.zeros_like(cam,requires_grad=True)
    mappings=sources[0]['mhr']['keypointMapping']
    width=18439+len(sources[0]['names']);indices=[];rows=[];weights=[]
    for row,mapping in enumerate(mappings):
        indices.extend(mapping['indices']);rows.extend([row]*len(mapping['indices']));weights.extend(mapping['weights'])
    mapping=torch.sparse_coo_tensor(tensor([rows,indices]).long(),tensor(weights),(70,width)).coalesce()
    selected=[]
    for i,source in enumerate(sources):
        for item in canonical(source):
            if item.get('known',True) and item['name'] in MHR:selected.append((i,MHR[item['name']],item))
    if not selected:return sources
    owner=torch.tensor([s[0] for s in selected],device=device);landmark=torch.tensor([s[1] for s in selected],device=device)
    expected=tensor([s[2]['xy'] for s in selected]);confidence=tensor([s[2]['weight'] for s in selected])
    tolerance=tensor([max(2.,(sources[i].get('personBox',[0,0,0,sources[i]['imageSize'][1]])[3]-sources[i].get('personBox',[0,0,0,0])[1])*(.02 if p['region']=='body' else .006)) for i,_,p in selected])
    k=tensor(sources[0]['camera']);basis=tensor([1,-1,-1]);best=None;best_loss=float('inf');initial_loss=None;initial_body=None
    def body_errors(projected):
        pixel=(projected[owner,landmark]-expected).norm(dim=1)
        return torch.stack([pixel[[k for k,(j,_,p) in enumerate(selected) if i==j and p['region']=='body']].mean() if any(i==j and p['region']=='body' for j,_,p in selected) else pixel.new_tensor(0.) for i in range(len(sources))])
    by_person={s['personId']:i for i,s in enumerate(sources)}
    from retarget import source_map
    semantics=[source_map(s['names']) for s in sources]
    def evaluate():
        params=torch.cat((base[:,:3],angles,base[:,136:]),dim=1)
        vertices,skeleton=model(shape,params,expr);points=skeleton[:,:,:3]/100
        combined=torch.cat((vertices/100,points),dim=1)
        keypoints=torch.stack([torch.sparse.mm(mapping,p) for p in combined])
        camera_points=keypoints*basis+cam[:,None,:]+shift[:,None,:]
        projected=camera_points[:,:,:2]/camera_points[:,:,2:].clamp(min=.1)*torch.stack((k[0,0],k[1,1]))+torch.stack((k[0,2],k[1,2]))
        errors=(projected[owner,landmark]-expected)/tolerance[:,None]
        image_loss=(torch.nn.functional.huber_loss(errors,torch.zeros_like(errors),reduction='none',delta=2).mean(1)*confidence).mean()
        loss=image_loss+((angles-base[:,3:136])**2).mean()*.7+(shift**2).mean()*8
        # Contact proposals constrain partners together without inventing shape/scale.
        for contact in contacts:
            if not contact.get('enabled',True):continue
            i,j=by_person[contact['personId']],by_person[contact['otherId']];side=contact['part'][0]
            own=semantics[i].get('hip' if contact['part']=='torso' else side+'Hand');bottom=semantics[j].get('hip');top=semantics[j].get('chestUpper')
            if own is None or bottom is None or top is None:continue
            p=points[i,own]+(cam[i]+shift[i])*basis;a=points[j,bottom]+(cam[j]+shift[j])*basis;b=points[j,top]+(cam[j]+shift[j])*basis
            if contact['part']=='torso' and semantics[i].get('chestUpper') is not None:p=(p+points[i,semantics[i]['chestUpper']]+(cam[i]+shift[i])*basis)/2
            if contact['part'].endswith('forearm'):
                elbow=semantics[i].get(side+'ForearmBend')
                if elbow is not None:p=(p+points[i,elbow]+(cam[i]+shift[i])*basis)/2
            direction=b-a;t=((p-a)@direction/(direction@direction).clamp(min=1e-6)).clamp(0,1)
            if contact['region']=='shoulder':t=t.clamp(min=.75)
            elif contact['region']=='waist':t=t.clamp(max=.35)
            elif contact['region'] in ('l_palm','r_palm'):
                wrist=semantics[j].get(contact['region'][0]+'Hand')
                if wrist is not None:a=points[j,wrist]+(cam[j]+shift[j])*basis;direction=direction*0;t=t*0
            if contact['region']=='shoulder' and contact.get('targetSide'):
                shoulder=semantics[j].get(contact['targetSide']+'ShldrBend')
                if shoulder is not None:a=points[j,shoulder]+(cam[j]+shift[j])*basis;direction=direction*0;t=t*0
            radius=0. if contact['region'].endswith('palm') else .22 if contact['part']=='torso' else .05 if contact['region']=='shoulder' else .11
            distance=(p-a-direction*t).norm();weight=1. if contact.get('confirmed') else contact['confidence']*.3
            loss=loss+((distance-radius)/.08)**2*weight*.15
        return loss,image_loss,params,points,skeleton,keypoints,projected
    optimizer=torch.optim.Adam([angles,shift],lr=.015)
    progress('Refining 3D pose against visible details and shared contacts',start)
    # Finite budget; retain best checkpoint rather than the last iterate.
    for step in range(55):
        optimizer.zero_grad();loss,image_loss,_,_,_,_,projected=evaluate()
        value=float(loss.detach())
        if not np.isfinite(value):break
        if initial_loss is None:initial_loss=float(image_loss.detach());initial_body=body_errors(projected).detach()
        if value<best_loss and bool((body_errors(projected).detach()<=initial_body*1.05+2).all()):best_loss=value;best=(angles.detach().clone(),shift.detach().clone())
        loss.backward();torch.nn.utils.clip_grad_norm_([angles,shift],5.);optimizer.step()
        with torch.no_grad():angles.copy_(torch.maximum(torch.minimum(angles,base[:,3:136]+.45),base[:,3:136]-.45));shift.clamp_(-.25,.25)
        if step%10==0:progress('Refining visible details · '+str(step+1)+'/55',round(start+(end-start)*(step+1)/55))
    result=copy.deepcopy(sources)
    if best is not None:
        with torch.no_grad():
            angles.copy_(best[0]);shift.copy_(best[1]);loss,image_loss,params,points,skeleton,keypoints,projected=evaluate()
            accepted=float(image_loss)<=initial_loss*1.05+1e-5
            if accepted:
                matrices=roma.unitquat_to_rotmat(skeleton[:,:,3:7])
                for i,source in enumerate(result):
                    source['positions']=points[i].cpu().tolist();source['rotations']=matrices[i].cpu().tolist()
                    source['keypoints3d']=keypoints[i].cpu().tolist()
                    source['cameraTranslation']=(cam[i]+shift[i]).cpu().tolist();source['projectedKeypoints']=projected[i].cpu().tolist();source['mhr']['modelParams']=params[i].cpu().tolist()
                    source['sourceRefinement']=dict(accepted=True,initialImageLoss=initial_loss,finalImageLoss=float(image_loss),initialBodyErrorPx=float(initial_body[i]),finalBodyErrorPx=float(body_errors(projected)[i]),iterations=step+1)
            else:
                for source in result:source['sourceRefinement']=dict(accepted=False,reason='Visible image evidence worsened')
    del model,optimizer;gc.collect()
    if torch.cuda.is_available():torch.cuda.empty_cache()
    return result

def source_signature(source):
    values=[source.get(k) for k in ('personKey','refinementSignature','mhr','measurements','camera','cameraTranslation','positions')]
    if source.get('extractionMethod')=='pure':values.extend(['pure',source.get('pureVersion')])
    return stamp(values)


def target_signature(root):
    from cache_provenance import stage_signature
    return stage_signature(root,('worker/coupled.py','worker/cropped.py','worker/posture.py','worker/measurements.py','worker/retarget.py','worker/refinement.py'))

def accepted_result(root,folder,sources=None,choice='smart'):
    """Never resurrect a correction after a new person, model or rig connection."""
    if sources:choice=sources[0].get('extractionMethod','smart')
    result=read_json(result_path(folder,'refinement',choice))
    if not result or not result.get('sourceSignatures'):return None
    from wholebody import signature
    if result.get('modelSignature') and result['modelSignature']!=signature(root):return None
    from rigs import profile
    people=read_json(folder/'people.json',[])
    try:
        if sources is None:
            sources=[cached_source(folder,next(p for p in people if p['id']==pose['personId']),pose.get('extractionMethod',choice),context=pose.get('sourceGuidance') or dict(version=1,id='original')) for pose in result['poses']]
        saved=result.get('refinementSources',[])
        if len(saved)!=len(sources) or any(s is None for s in sources):return None
        if {s['personId']:source_signature(s) for s in sources}!={int(k):v for k,v in result['sourceSignatures'].items()}:return None
        if any(stamp(p['rig'])!=stamp(profile(root,p['rigId'])) for p in result['poses']):return None
        return result
    except (KeyError,ValueError,StopIteration):return None

def refine(root,payload,progress):
    if payload.get('version',1)==2:return posture_refine(root,payload,progress)
    if payload.get('version',1)!=1:raise ValueError('Unsupported refinement version.')
    folder=image_dir(root,payload['imageId']);people=read_json(folder/'people.json',[])
    members=payload.get('members',[])
    if not 1<=len(members)<=4 or len({m.get('personId') for m in members})!=len(members):raise ValueError('Choose one to four distinct extracted people.')
    sources=[]
    for member in members:
        person=next((p for p in people if p['id']==member['personId']),None);source=cached_source(folder,person,selected(root,payload,interaction=len(members)>1),context=member.get('sourceGuidance')) if person else None
        if source is None:raise ValueError('Extract every selected person first.')
        sources.append(copy.deepcopy(source))
    original_signatures={s['personId']:source_signature(s) for s in sources}
    for source in sources:
        person=next(p for p in people if p['id']==source['personId'])
        if person.get('box'):source.setdefault('personBox',person['box'])
    previous=accepted_result(root,folder,sources)
    if previous:
        saved={s['personId']:s for s in previous['refinementSources']}
        sources=[copy.deepcopy(saved[s['personId']]) for s in sources]
    automatic=payload.get('automatic',False)
    if not isinstance(automatic,bool):raise ValueError('Automatic refinement must be true or false.')
    from wholebody import signature, Landmarker, resolve_ownership
    if automatic:
        if not all(s.get('mhr') for s in sources):raise ValueError('This older extraction lacks fused parameters. Choose Extract again once to enable automatic refinement. Foot support remains available on newer extractions.')
        progress('Checking cached body, hand and foot measurements',18)
        # Model/algorithm changes remeasure original pixels, without loading SAM's encoder.
        stale=[s for s in sources if s.get('refinementSignature')!=signature(root)]
        if stale:
            from PIL import Image
            image=np.array(Image.open(folder/'source.png').convert('RGB'));engine=Landmarker(root)
            for source in stale:
                person=next(p for p in people if p['id']==source['personId'])
                source['measurements']=engine.measure(image,person,[p for p in people if p['id']!=person['id']],progress)
                source['refinementSignature']=signature(root);source['refinementMode']='accurate'
            del engine
    correction=payload.get('corrections',[])
    groups=overrides(resolve_ownership([canonical(s) for s in sources]),correction,sources[0]['imageSize'])
    for source,group in zip(sources,groups):source['measurements']=group;source['correctionSignature']=stamp([correction,payload.get('contacts',[]),payload.get('support',[])])
    from rigs import profile
    from retarget import retarget
    from coupled import fit_targets,contact_graph
    poses=[retarget(s,profile(root,m['rigId'])) for s,m in zip(sources,members)]
    graph=contact_graph(sources,poses,payload.get('contacts',[])) if len(sources)>1 else []
    # Automatic matching always fits observed points; no user annotation required.
    # Older transport clients can still request cached support/contact-only fitting.
    if automatic or correction:
        if not all(s.get('mhr') for s in sources):raise ValueError('This older extraction lacks fused parameters. Extract again to refine image landmarks; contact and support corrections still work.')
        sources=refine_sources(root,sources,graph,progress,start=30,end=68);poses=[retarget(s,profile(root,m['rigId'])) for s,m in zip(sources,members)]
    # Continue the authoritative accepted target layout, including its camera origin.
    warm_start=False
    if previous:
        saved={p['personId']:p for p in previous['poses']}
        if all(m['personId'] in saved and saved[m['personId']]['rigId']==m['rigId'] for m in members):
            poses=[copy.deepcopy(saved[m['personId']]) for m in members];warm_start=True
    result=fit_targets(sources,poses,payload.get('contacts',[]),payload.get('support',[]),progress,warm_start=warm_start)
    if not result['diagnostics']['accepted']:raise ValueError('The automatic fit could not improve this match safely. Your previous pose is preserved. Check foot support or inspect uncertain contacts in Pose studio.')
    # Commit one self-contained result only after success. Original solves/history stay intact.
    result['corrections']=correction;result['refinementSources']=sources;result['sourceSignatures']=original_signatures;result['modelSignature']=signature(root)
    result['automatic']=automatic;result['supportOverrides']=payload.get('support',[])
    result['created']=time.time();progress('Saving the validated match',98);atomic_json(result_path(folder,'refinement',sources[0].get('extractionMethod','smart')),bind_people(result,sources))
    progress('Refined match ready · inspect all views',100)
    return result

def posture_refine(root,payload,progress):
    """Preview/commit transaction using the displayed pose, including after Undo.

    Version-1 clients retain their legacy behavior. This path deliberately keeps
    fused MHR parameters immutable: cached independent evidence fits target
    details directly, without allowing a full-body source refit to undo posture.
    """
    import re,uuid
    from posture import load_baselines,context_key,guidance_options,POLICY_VERSION
    from editor import checked_poses
    from rigs import profile
    from wholebody import signature,Landmarker,resolve_ownership
    action=payload.get('action','preview');folder=image_dir(root,payload['imageId'])
    if payload.get('policyVersion')!=POLICY_VERSION:raise ValueError('Unsupported posture policy. Reopen Refine match.')
    token=payload.get('previewId','')
    if action in ('apply','cancel'):
        if not re.fullmatch(r'[0-9a-f]{32}',token):raise ValueError('Invalid refinement preview. Preview the match again.')
        path=root/'temp/refinement-previews'/f'{token}.json'
        if action=='cancel':path.unlink(missing_ok=True);return dict(cancelled=True)
        pending=read_json(path)
        if not pending or pending['imageId']!=payload['imageId'] or time.time()-pending['created']>1800:raise ValueError('This preview expired. Preview the match again.')
    elif action!='preview':raise ValueError('Unknown refinement action.')
    current=copy.deepcopy(payload.get('currentPoses',[]))
    checked_poses(root,payload['imageId'],current)
    for p in current:
        p['rig']=profile(root,p['rigId'])
        if not p.get('referenceCamera'):raise ValueError('Return to As extracted orientation before refining, so the reference camera is preserved.')
    people=read_json(folder/'people.json',[]);sources=[]
    for p in current:
        person=next((person for person in people if person['id']==p['personId']),None)
        source=cached_source(folder,person,p.get('extractionMethod','smart'),context=p.get('sourceGuidance') or dict(version=1,id='original')) if person else None
        if not source:raise ValueError('Extract every selected person first.')
        source=copy.deepcopy(source)
        if person.get('box'):source.setdefault('personBox',person['box'])
        sources.append(source)
    original_signatures={s['personId']:source_signature(s) for s in sources}
    # Load against original source signatures before updating measurement caches.
    anchors=load_baselines(folder,sources,current)
    current_id=context_key(current)
    if action=='apply':
        if pending.get('targetSignature')!=target_signature(root):raise ValueError('The fitting policy changed. Preview the current match again.')
        if pending['currentId']!=current_id or pending['sourceSignatures']!={str(k):v for k,v in original_signatures.items()} or pending['modelSignature']!=signature(root):
            raise ValueError('The pose, extraction or measurements changed. Preview the current match again.')
        result=pending['result'];progress('Applying the inspected match',100)
        atomic_json(result_path(folder,'refinement',sources[0].get('extractionMethod','smart')),bind_people(result,sources));path.unlink(missing_ok=True)
        return result
    preferences=list(guidance_options(payload.get('guidance',[]),current).values())
    progress('Checking cached measurements and accepted posture',18)
    stale=[s for s in sources if s.get('refinementSignature')!=signature(root)]
    if stale:
        from PIL import Image
        image=np.array(Image.open(folder/'source.png').convert('RGB'));engine=Landmarker(root)
        for source in stale:
            person=next(p for p in people if p['id']==source['personId'])
            source['measurements']=engine.measure(image,person,[p for p in people if p['id']!=person['id']],progress)
            source['refinementSignature']=signature(root)
        del engine
    from cropped import prepare
    sources=[prepare(root,s,dict(zeroCroppedJoints=p.get('cropPolicy',{}).get('enabled',False),contacts=payload.get('contacts',[])),next(person for person in people if person['id']==s['personId'])) for s,p in zip(sources,current)]
    groups=resolve_ownership([canonical(s) for s in sources])
    for s,group in zip(sources,groups):s['measurements']=group
    from coupled import fit_targets
    progress('Protecting the torso; fitting hands, feet and contacts',45)
    result=fit_targets(sources,current,payload.get('contacts',[]),payload.get('support',[]),progress,warm_start=True,anchors=anchors,guidance=preferences,preserve=True)
    if not result['diagnostics']['accepted']:
        reason=result['diagnostics'].get('posture',{}).get('rejection','The bounded fit did not improve the accepted pose.')
        if any(g['preset']!='keep' for g in preferences):raise ValueError('This side preference conflicts with the reference. Try gentler guidance or keep the extracted posture. '+str(reason))
        raise ValueError(str(reason)+' Your accepted pose is preserved.')
    result.update(corrections=[],refinementSources=sources,sourceSignatures=original_signatures,modelSignature=signature(root),automatic=True,supportOverrides=payload.get('support',[]),guidance=preferences,policyVersion=POLICY_VERSION,currentId=current_id,created=time.time())
    for p in result['poses']:
        old=next(v for v in current if v['personId']==p['personId']);p['postureBaseline']=old['postureBaseline']
    token=uuid.uuid4().hex;result['previewId']=token
    progress('Preview ready · inspect Side and Reference before applying',100)
    atomic_json(root/'temp/refinement-previews'/f'{token}.json',dict(imageId=payload['imageId'],currentId=current_id,sourceSignatures=original_signatures,modelSignature=signature(root),targetSignature=target_signature(root),created=time.time(),result=result))
    # Bound transient cache size; no application/history data is removed.
    for old in (root/'temp/refinement-previews').glob('*.json'):
        if time.time()-old.stat().st_mtime>1800:old.unlink(missing_ok=True)
    return result
