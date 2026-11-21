"""Local SimCC models. No runtime downloads or MMPose/MMCV dependency."""
import hashlib
from functools import lru_cache
from pathlib import Path
import cv2
import numpy as np

MODELS = {'wholebody': 'rtmw-l.onnx', 'hand': 'rtmpose-hand.onnx'}
BODY = {5: 'l_shoulder', 6: 'r_shoulder', 7: 'l_elbow', 8: 'r_elbow', 9: 'l_wrist', 10: 'r_wrist',
        11: 'l_hip', 12: 'r_hip', 13: 'l_knee', 14: 'r_knee', 15: 'l_ankle', 16: 'r_ankle'}
FOOT = ['l_bigtoe', 'l_smalltoe', 'l_heel', 'r_bigtoe', 'r_smalltoe', 'r_heel']
HAND = ['wrist'] + [f'{finger}{part}' for finger in ('thumb', 'index', 'middle', 'ring', 'pinky') for part in (1, 2, 3, 'tip')]
# The face is deliberately excluded; extraction supports body and hands only.
NAMES = {**BODY, **dict(enumerate(FOOT, 17)), **{91+i: 'l_'+v for i,v in enumerate(HAND)}, **{112+i: 'r_'+v for i,v in enumerate(HAND)}}
FLIP = list(range(133))
for a,b in ((5,6),(7,8),(9,10),(11,12),(13,14),(15,16),(17,20),(18,21),(19,22),*[(91+i,112+i) for i in range(21)]):
    FLIP[a],FLIP[b] = b,a

def model_path(root, kind):
    for folder in ('models/refinement', '.tools/refinement'):
        path = root/folder/MODELS[kind]
        if path.is_file(): return path
    return root/'models/refinement'/MODELS[kind]

def available(root):
    return all(model_path(root,k).is_file() for k in MODELS)

@lru_cache(maxsize=12)
def file_digest(path,size,modified):
    digest=hashlib.sha256()
    with open(path,'rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()

def signature(root):
    values = []
    for key in MODELS:
        path = model_path(root,key)
        stat=path.stat() if path.is_file() else None
        values.append((key,file_digest(str(path),stat.st_size,stat.st_mtime_ns)) if stat else (key,None))
    from cache_provenance import provenance,source_functions
    source = provenance(root, ('worker/wholebody.py',))
    values.extend(source_functions(root,(('worker/refinement.py',('refine_sources',)),('worker/retarget.py',('source_map',)),('worker/measurements.py',('canonical',)))))
    return hashlib.sha256(repr(('refinement-v5',source,values)).encode()).hexdigest()[:24]

def affine_crop(image, box, size, padding=1.25):
    """Keep the affine inverse, including out-of-image padding and aspect ratio."""
    width,height = size; x1,y1,x2,y2 = map(float,box)
    if not np.isfinite(box).all() or min(x2-x1,y2-y1)<2: raise ValueError('Invalid landmark crop.')
    center = np.array([(x1+x2)/2,(y1+y2)/2])
    scale = np.array([x2-x1,y2-y1])*padding
    if scale[0]/scale[1]>width/height: scale[1]=scale[0]*height/width
    else: scale[0]=scale[1]*width/height
    matrix = np.array([[width/scale[0],0,width/2-center[0]*width/scale[0]],
                       [0,height/scale[1],height/2-center[1]*height/scale[1]]],np.float32)
    crop = cv2.warpAffine(image,matrix,(width,height),flags=cv2.INTER_LINEAR)
    inverse = cv2.invertAffineTransform(matrix)
    return crop,inverse

def decode_simcc(x,y,inverse,split=2.):
    x,y = np.asarray(x)[0],np.asarray(y)[0]
    points = np.column_stack((x.argmax(-1),y.argmax(-1))).astype(float)/split
    scores = np.minimum(x.max(-1),y.max(-1))
    points = points@inverse[:,:2].T+inverse[:,2]
    return points,scores

class Landmarker:
    def __init__(self,root): self.root=root; self.sessions={}
    def vectors(self,image,box,kind='wholebody',flipped=False):
        import onnxruntime as ort
        if kind not in self.sessions:
            path=model_path(self.root,kind)
            if not path.is_file(): raise ValueError('Accurate extraction needs local refinement weights. Restore the private whole-body and hand models; development uses scripts/prepare-refinement-models.py.')
            options=ort.SessionOptions();options.intra_op_num_threads=4;options.inter_op_num_threads=1;options.log_severity_level=3
            self.sessions[kind]=ort.InferenceSession(str(path),options,providers=['CPUExecutionProvider'])
        session=self.sessions[kind]; inp=session.get_inputs()[0]
        size=(int(inp.shape[3]),int(inp.shape[2]))
        crop,inverse=affine_crop(image,box,size)
        if flipped: crop=crop[:,::-1].copy()
        tensor=((crop.astype(np.float32)-[123.675,116.28,103.53])/[58.395,57.12,57.375]).transpose(2,0,1)[None].astype(np.float32)
        outputs=session.run(None,{inp.name:tensor})
        if len(outputs)<2: raise ValueError('Unsupported SimCC model outputs.')
        return outputs[0],outputs[1],inverse

    def predict(self,image,box,kind='wholebody',flipped=False):
        x,y,inverse=self.vectors(image,box,kind,flipped)
        # SimCC reverses bins, not rounded pixel coordinates (half-pixel bins).
        if flipped:x=x[:,:,::-1]
        return decode_simcc(x,y,inverse)

    def paired(self,image,box,kind='wholebody',fuse=None):
        """Official flip-distribution fusion with independent disagreement retained.

        Conflicting modes are never averaged into invented middle landmarks.
        Whole-body flips swap semantic sides; a hand crop preserves finger order.
        """
        x,y,inverse=self.vectors(image,box,kind)
        flip_x,flip_y,_=self.vectors(image,box,kind,True)
        order=FLIP if kind=='wholebody' else list(range(len(HAND)))
        flip_x=flip_x[:,order,::-1];flip_y=flip_y[:,order]
        original,scores=decode_simcc(x,y,inverse)
        reflected,flip_scores=decode_simcc(flip_x,flip_y,inverse)
        points,combined=decode_simcc((x+flip_x)*.5,(y+flip_y)*.5,inverse) if fuse is not False else (original,scores)
        if fuse is None and kind=='wholebody':
            # Fixed 20-photo validation did not improve body/foot error with fusion.
            # Retain those coordinates, while keeping flip uncertainty.
            points[:23]=original[:23];combined[:23]=scores[:23]
        error=np.linalg.norm(original-reflected,axis=1)
        # Both passes must support the measurement. Score alone is not visibility.
        return points,np.minimum(combined,np.minimum(scores,flip_scores)),error

    def measure(self,image,person,others=(),progress=lambda *_:None):
        box=person['box']; height=max(24.,box[3]-box[1])
        points,scores,flip_errors=self.paired(image,box)
        out=[]
        for index,name in NAMES.items():
            p=points[index]; score=float(np.clip(scores[index],0,1))
            discrepancy=float(flip_errors[index])
            region='body' if index<17 else name[0]+('_foot' if index<23 else '_hand')
            if not np.isfinite(p).all(): continue
            consistent=discrepancy<height*(.035 if region=='body' else .025)
            in_image=bool(np.all(p>=0) and p[0]<image.shape[1] and p[1]<image.shape[0])
            out.append(dict(name=name,xy=p.tolist(),weight=score,region=region,known=score>=.45 and consistent and in_image,
                            provenance='rtmw',flipErrorPx=discrepancy))
        # Sparse RTMO body points anchor person ownership, not a second pose to average.
        body_points=person.get('keypoints',[])
        for item in out:
            coco=next((i for i,n in BODY.items() if n==item['name']),None)
            if coco is not None and len(body_points)>coco and body_points[coco][2]>=.7:
                if np.linalg.norm(np.asarray(item['xy'])-body_points[coco][:2])>height*.1:
                    item['known']=False;item['reason']='Disagrees with person anchor'
        for side in ('l','r'):
            hand=[p for p in out if p['region']==side+'_hand']; wrist=next((p for p in out if p['name']==side+'_wrist' and p['region']=='body'),None)
            if not wrist or not wrist['known']:
                for p in hand:p['known']=False;p['reason']='No reliable owner wrist'
                continue
            # Do not accept the partner's visible hand merely because it is in the crop.
            if hand and np.linalg.norm(np.asarray(hand[0]['xy'])-wrist['xy'])>height*.09:
                for p in hand: p['known']=False;p['reason']='Wrist ownership uncertain'
                continue
            valid=[p for p in hand if p['known']]
            if len(valid)>=8:
                xy=np.asarray([p['xy'] for p in valid]); lo=xy.min(0);hi=xy.max(0)
            else:
                lo=np.asarray(wrist['xy'])-height*.06;hi=np.asarray(wrist['xy'])+height*.06
            diagonal=float(np.linalg.norm(hi-lo))
            if len(valid)<17 or diagonal<height*.14 or any(p['flipErrorPx']>height*.01 for p in hand):
                center=(lo+hi)/2;extent=max(32.,max(hi-lo)*1.6)
                crop_box=[*(center-extent/2),*(center+extent/2)]
                detail,confidence,disagreement=self.paired(image,crop_box,'hand')
                if np.linalg.norm(detail[0]-wrist['xy'])<height*.07:
                    for index,p in enumerate(hand):
                        if confidence[index]>.5 and np.isfinite(detail[index]).all() and disagreement[index]<max(3.,extent*.12) and np.all(detail[index]>=0) and detail[index,0]<image.shape[1] and detail[index,1]<image.shape[0]:
                            p.update(xy=detail[index].tolist(),weight=float(np.clip(confidence[index],0,1)),known=True,provenance='rtmpose-hand',flipErrorPx=float(disagreement[index]))
        feet=[p for p in out if p['region'].endswith('_foot')]
        if feet and any(not p['known'] for p in feet):
            detail,confidence,disagreement=self.paired(image,[box[0],box[1]+height*.4,box[2],box[3]])
            for index in range(17,23):
                item=next(p for p in feet if p['name']==NAMES[index])
                if not item['known'] and confidence[index]>.6 and disagreement[index]<height*.025 and np.linalg.norm(detail[index]-points[index])<height*.06 and np.all(detail[index]>=0) and detail[index,0]<image.shape[1] and detail[index,1]<image.shape[0]:
                    item.update(xy=detail[index].tolist(),weight=float(np.clip(confidence[index],0,1)),known=True,provenance='rtmw-lower-body',flipErrorPx=float(disagreement[index]))
        # Coincident hand landmarks across crops are ambiguous unless forearm ownership agrees.
        for item in out:
            item['personId']=person['id']
        return out

def resolve_ownership(groups):
    """One-to-one hand ownership. Never silently merge two overlapping subjects."""
    from scipy.optimize import linear_sum_assignment
    candidates=[];anchors=[]
    for group in groups:
        for side in ('l','r'):
            hand=[p for p in group if p['region']==side+'_hand']
            wrist=next((p for p in group if p['name']==side+'_wrist' and p['region']=='body' and p['known']),None)
            if hand and wrist:
                anchors.append((group,side,wrist));candidates.append(hand)
    if len(candidates)<2:return groups
    cost=np.array([[np.linalg.norm(np.asarray(a[2]['xy'])-h[0]['xy'])+(0 if a[1]==h[0]['name'][0] else 1e5) for h in candidates] for a in anchors])
    rows,cols=linear_sum_assignment(cost)
    # Keep semantic owner: another crop's hand is evidence, never a reassigned person.
    for row,col in zip(rows,cols):
        if row!=col:
            for p in candidates[row]:p['known']=False;p['reason']='Partner hand ownership unresolved'
    for i,hand in enumerate(candidates):
        for j,other in enumerate(candidates[:i]):
            if hand[0]['personId']!=other[0]['personId'] and np.linalg.norm(np.asarray(hand[0]['xy'])-other[0]['xy'])<5:
                own={p['name'][2:]:p for p in hand if p.get('known',True)};partner={p['name'][2:]:p for p in other if p.get('known',True)}
                common=(own.keys()&partner.keys())-{'wrist'}
                if common and np.mean([np.linalg.norm(np.asarray(own[n]['xy'])-partner[n]['xy'])<5 for n in common])<.8:continue
                if abs(cost[i,i]-cost[j,j])>8:
                    for p in (hand if cost[i,i]>cost[j,j] else other):p['known']=False;p['reason']='Duplicate partner hand'
                else:
                    for p in hand+other:p['known']=False;p['reason']='Partner hand ownership ambiguous'
    return groups
