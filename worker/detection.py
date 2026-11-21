"""Local instance-aware detection. Models are never downloaded by the worker."""
from storage import atomic_json, image_dir, read_json, data_url
from instances import DETECTION_VERSION, identity, anchor, distinct_people

def model_path(root):
    # The checkpoint under .tools is a development experiment, not a release bundle.
    for path in (root/'models/detection/rtmo_body7.onnx', root/'.tools/rtmo/instance-aware.onnx'):
        if path.is_file(): return path, 'rtmo-body7-instance'
    return root/'models/detection/yolox_s.onnx', 'yolox-s'

def detect(root, payload, progress):
    import numpy as np
    import cv2
    import onnxruntime as ort
    from PIL import Image
    folder = image_dir(root, payload['imageId'])
    model, detector = model_path(root)
    stamp = dict(version=DETECTION_VERSION, thumbnails=2, detector=detector, bytes=model.stat().st_size if model.is_file() else 0, modified=model.stat().st_mtime_ns if model.is_file() else 0)
    cached = read_json(folder/'people.json')
    if cached is not None and read_json(folder/'detection.json') == stamp and not payload.get('refresh'):
        return cached
    if not model.is_file(): raise ValueError('The local person detector is missing. Check Settings.')
    progress('Finding individual bodies and visible landmarks' if detector.startswith('rtmo') else 'Finding people with the legacy detector',12)
    options=ort.SessionOptions();options.intra_op_num_threads=4
    session=ort.InferenceSession(str(model),sess_options=options,providers=['CPUExecutionProvider'])
    with Image.open(folder/'source.png') as opened: pil=opened.convert('RGB')
    image=np.array(pil)[:,:,::-1].copy()
    h,w=image.shape[:2];size=640;ratio=min(size/h,size/w)
    padded=np.full((size,size,3),114,dtype=np.uint8)
    padded[:int(h*ratio),:int(w*ratio)]=cv2.resize(image,(int(w*ratio),int(h*ratio)))
    outputs=session.run(None,{session.get_inputs()[0].name:padded.transpose(2,0,1)[None].astype(np.float32)})
    if detector.startswith('rtmo'):
        if len(outputs)!=2 or outputs[1].shape[-2:]!=(17,3): raise ValueError('Unsupported RTMO model outputs; restore the tested body7 checkpoint.')
        candidates=[]
        for row,points in zip(outputs[0][0],outputs[1][0]):
            if not np.isfinite(row).all() or not np.isfinite(points).all():continue
            if row[4]<.3 or sum(points[:,2]>=.55)<5: continue
            box=(row[:4]/ratio).clip([0,0,0,0],[w-1,h-1,w,h]).tolist()
            if box[2]-box[0]<12 or box[3]-box[1]<24: continue
            kp=points.copy();kp[:,:2]/=ratio
            candidates.append(dict(box=box,score=float(row[4]),keypoints=kp.tolist()))
        people=distinct_people(candidates)
    else:
        people=legacy_candidates(outputs[0][0],ratio,w,h)
    for i, person in enumerate(people):person.update(id=i+1,detector=detector,detectionVersion=DETECTION_VERSION)
    context=':'.join(identity(p) for p in people)
    for person in people:
        person['contextKey']=context
        person['anchor']=anchor(person)
        x,y=person['anchor'];height=person['box'][3]-person['box'][1]
        # A head-and-shoulders crop identifies the subject when body boxes overlap.
        crop=(max(0,x-height*.085),max(0,y-height*.095),min(w,x+height*.085),min(h,y+height*.12))
        person['thumbnail']=data_url(pil.crop(crop),(160,180))
        person['personKey']=identity(person)
    atomic_json(folder/'people.json',people)
    atomic_json(folder/'detection.json',stamp)
    progress('People ready — choose one subject' if len(people)>1 else 'Person ready',100)
    return people

def legacy_candidates(output,ratio,w,h):
    import numpy as np
    grids,strides=[],[]
    for stride in (8,16,32):
        y,x=np.meshgrid(np.arange(640//stride),np.arange(640//stride),indexing='ij')
        grid=np.stack((x,y),axis=-1).reshape(-1,2);grids.append(grid);strides.extend([stride]*len(grid))
    stride=np.asarray(strides)[:,None]
    output[:,:2]=(output[:,:2]+np.concatenate(grids))*stride
    output[:,2:4]=np.exp(output[:,2:4])*stride
    scores=output[:,4]*output[:,5];centers=output[:,:2]/ratio;half=output[:,2:4]/(2*ratio)
    boxes=np.concatenate((centers-half,centers+half),axis=1)
    candidates=np.where(scores>=.35)[0];candidates=candidates[np.argsort(scores[candidates])[::-1]]
    kept=[];area=np.maximum(0,boxes[:,2:]-boxes[:,:2]).prod(axis=1)
    while len(candidates):
        i=int(candidates[0]);kept.append(i);others=candidates[1:]
        intersection=np.maximum(0,np.minimum(boxes[i,2:],boxes[others,2:])-np.maximum(boxes[i,:2],boxes[others,:2])).prod(axis=1)
        candidates=others[intersection/(area[i]+area[others]-intersection+1e-9)<.65]
    return [dict(box=boxes[i].clip([0,0,0,0],[w-1,h-1,w,h]).tolist(),score=float(scores[i])) for i in sorted(kept,key=lambda i:boxes[i,0]) if boxes[i,2]-boxes[i,0]>=12 and boxes[i,3]-boxes[i,1]>=24]
