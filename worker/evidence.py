"""Visible image evidence, separate from detector confidence and 3D accuracy."""
import math
import numpy as np

# COCO17 -> MHR70, verified against upstream metadata/mhr70.py.
# Face estimates on featureless mannequins are not used as body prompts.
BODY_MAP = {5:5, 6:6, 7:7, 8:8, 9:62, 10:41, 11:9, 12:10, 13:11, 14:12, 15:13, 16:14}

def landmarks(person, others=(), mask=None):
    height=max(24., person['box'][3]-person['box'][1]); result=[]
    for coco,mhr in BODY_MAP.items():
        points=person.get('keypoints',[])
        if len(points)<=coco:continue
        point=points[coco]
        if len(point)!=3 or not all(math.isfinite(v) for v in point) or point[2]<.7:continue
        if any(len(p.get('keypoints',[]))>coco and p['keypoints'][coco][2]>=.7 and math.dist(point[:2],p['keypoints'][coco][:2])<height*.025 for p in others):continue
        if mask is not None:
            x,y=map(lambda v:int(round(v)),point[:2]);h,w=mask.shape
            # A small neighbourhood accommodates SAM boundary uncertainty.
            if not (0<=x<w and 0<=y<h) or not mask[max(0,y-3):min(h,y+4),max(0,x-3):min(w,x+4)].any():continue
        result.append(dict(coco=coco,mhr=mhr,xy=point[:2],weight=float(point[2])))
    return result

def agreement(projected, evidence, height):
    projected=np.asarray(projected,dtype=float)
    valid=[p for p in evidence if p['mhr']<len(projected) and np.isfinite(projected[p['mhr'],:2]).all()]
    if len(valid)<4:return dict(matched=None,count=len(valid),threshold=.05,meanError=None)
    errors=np.array([np.linalg.norm(projected[p['mhr'],:2]-p['xy'])/max(24.,height) for p in valid])
    return dict(matched=float(np.mean(errors<=.05)),count=len(valid),threshold=.05,meanError=float(np.mean(errors)))

def measured_prompts(measurements,anchors):
    """Only reliable independently observed points prompt the 3D decoder.

    MHR anatomical indices are shared with fitting; wrists are counted once.
    Fingers crossing the partner silhouette retain their checked wrist owner.
    """
    from measurements import MHR
    result={p['mhr']:dict(p,region='body') for p in anchors}
    for point in measurements:
        if not point.get('known') or point.get('weight',0)<.7 or point['name'] not in MHR:continue
        result[MHR[point['name']]]=dict(mhr=MHR[point['name']],xy=point['xy'],weight=point['weight'],region=point['region'])
    return list(result.values())

def prompt_errors(projected,evidence,height):
    """Balance regions so 40 finger points cannot dominate the body guard."""
    groups={}
    for point in evidence:
        error=float(np.linalg.norm(projected[point['mhr']]-point['xy']))
        groups.setdefault(point.get('region','body'),[]).append(error)
    values={region:float(np.mean(errors)) for region,errors in groups.items()}
    score=np.mean([error/max(2.,height*(.02 if region=='body' else .006)) for region,error in values.items()]) if values else float('inf')
    return float(score),values

def project(points, translation, focal, size):
    """SAM body projection: camera X right/Y down/Z forward, centred image."""
    points=np.asarray(points,dtype=float)+np.asarray(translation,dtype=float)
    if points.shape[-1]!=3 or np.any(points[:,2]<=.01):raise ValueError('The estimated body lies behind its camera. Try another reference.')
    return points[:,:2]/points[:,2,None]*float(focal)+np.asarray(size,dtype=float)/2

def conditioned_body(model, batch, output, evidence, height, rounds=4):
    """At most four checked prompt rounds before upstream hand refinement.

    All operations use upstream crop transforms and decoder APIs. Reject a prompt
    update that worsens mean visible landmark error. No vendor source is modified.
    """
    import torch
    count=0
    if len(evidence)<4:return output,count
    baseline,initial=prompt_errors(output['mhr']['pred_keypoints_2d'][0].detach().float().cpu().numpy(),evidence,height)
    for _ in range(rounds):
        projected=output['mhr']['pred_keypoints_2d'][0].detach().float().cpu().numpy()
        ranked=sorted(evidence,key=lambda p:np.linalg.norm(projected[p['mhr']]-p['xy'])*p['weight']/(.02 if p.get('region','body')=='body' else .006),reverse=True)
        # The checkpoint accepts two clicks per round; do not change that shape.
        points=[p for p in ranked if np.linalg.norm(projected[p['mhr']]-p['xy'])>max(2.,height*(.015 if p.get('region','body')=='body' else .006))][:2]
        if not points:break
        xy=torch.tensor([[p['xy'] for p in points]],device=batch['img'].device,dtype=torch.float32)
        crop=model._full_to_crop(batch,xy)+.5
        valid=((crop>=0)&(crop<=1)).all(dim=-1)[0]
        if not valid.any():break
        ids=torch.tensor([[[p['mhr']] for p in points]],device=crop.device,dtype=crop.dtype)
        prompts=torch.cat((crop,ids),dim=-1)[:,valid]
        # run_keypoint_prompt mutates only the outer dictionary. Retain the
        # earlier tensor dictionary for rejection and subsequent hand crops.
        # The upstream prompting helper discards detector tokens, but full
        # inference needs the resulting hand boxes before cropping hands.
        decoder=model.forward_decoder
        hand_tokens=None
        def capture(*args,**kwargs):
            nonlocal hand_tokens
            tokens,poses=decoder(*args,**kwargs);hand_tokens=tokens
            return tokens,poses
        model.forward_decoder=capture
        try:candidate,_=model.run_keypoint_prompt(batch,dict(output),prompts)
        finally:model.forward_decoder=decoder
        if 'hand_box' in output['mhr']:
            if hand_tokens is not None and hasattr(model,'bbox_embed'):
                candidate['mhr']['hand_box']=model.bbox_embed(hand_tokens).sigmoid()
                candidate['mhr']['hand_logits']=model.hand_cls_embed(hand_tokens)
            else:
                # Versions without detector tokens retain the original crops.
                candidate['mhr']['hand_box']=output['mhr']['hand_box']
        score,regions=prompt_errors(candidate['mhr']['pred_keypoints_2d'][0].detach().float().cpu().numpy(),evidence,height)
        if not math.isfinite(score) or score>=baseline-1e-6 or any(regions.get(r,float('inf'))>error*1.05+2 for r,error in initial.items()):break
        output=candidate;baseline=score;count+=int(valid.sum())
    return output,count
