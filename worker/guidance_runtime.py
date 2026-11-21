"""Short-lived CPU ShadeNet adapter. No training code, Torch import or downloads in balanced mode.

Framing and detailed TTA follow singam96/ShadeNet-5-35M (Apache-2.0),
revision 6f3c1b617ef052ba45453a6287771166f5e6ac59. See THIRD_PARTY_NOTICES.
"""
import argparse
import json
import math
import os
from pathlib import Path
import sys
from time import perf_counter

# Each helper is a new process: the parent's AddDllDirectory handles do not carry over.
_native=Path(__file__).resolve().parents[1]/'runtime/native'
_DLL_HANDLES=[os.add_dll_directory(str(_native))] if os.name=='nt' and _native.is_dir() else []

import numpy as np
from PIL import Image

REVISION = '6f3c1b617ef052ba45453a6287771166f5e6ac59'
MODELS = {
    'auto': ('shadenet5-mix-refined.onnx', 'f273b36084478f6294f9acb7ec6bae50aacf973b4881e97aabdc35ed32ce2b3d'),
    'detailed': ('shadenet5-mix.onnx', '2fc5356d1280aca64ba8d248ae1d11dd8150e1b557604ea2e56931d239552641'),
}


def letterbox(image):
    image = image.convert('RGB')
    w,h=image.size
    scale=448/max(w,h)
    nw,nh=max(1,round(w*scale)),max(1,round(h*scale))
    left,top=(448-nw)//2,(448-nh)//2
    pixels=np.asarray(image.resize((nw,nh),Image.Resampling.BICUBIC))
    square=np.pad(pixels,((top,448-nh-top),(left,448-nw-left),(0,0)),mode='symmetric')
    return square,(left,top,nw,nh)


def rotate_tensor(value,angle,mode='bicubic',padding='reflection'):
    import torch
    import torch.nn.functional as functional
    a=math.radians(angle);c,s=math.cos(a),math.sin(a)
    theta=torch.tensor([[[c,-s,0.],[s,c,0.]]],dtype=torch.float32)
    grid=functional.affine_grid(theta,list(value.shape),align_corners=False)
    return functional.grid_sample(value.float(),grid,mode=mode,padding_mode=padding,align_corners=False)


def detailed(session,input_name,output_name,pixels):
    import torch
    torch.set_num_threads(4)
    x=torch.from_numpy(pixels)
    total=weight=None
    for flip in (False,True):
        for angle in (0.,-4.,4.):
            image=x.flip(-1) if flip else x
            if angle:image=rotate_tensor(image,angle).clamp(-1,1)
            predicted=torch.from_numpy(session.run([output_name],{input_name:image.numpy()})[0]).float()
            valid=torch.ones_like(predicted[:,:1])
            if angle:
                predicted=rotate_tensor(predicted,-angle,'bilinear','zeros')
                valid=rotate_tensor(valid,-angle,'bilinear','zeros')>.999
                a=math.radians(-angle);c,s=math.cos(a),math.sin(a)
                nx,ny=predicted[:,4].clone(),predicted[:,5].clone()
                predicted[:,4]=c*nx-s*ny;predicted[:,5]=s*nx+c*ny
            if flip:
                predicted=predicted.flip(-1).clone();predicted[:,4].neg_();valid=valid.flip(-1)
            valid=valid.float()
            total=predicted*valid if total is None else total+predicted*valid
            weight=valid if weight is None else weight+valid
    return (total/weight.clamp_min(1)).numpy()


def run(root,request):
    import onnxruntime as ort
    from storage import digest
    profile=request.get('profile','auto')
    if profile not in MODELS:raise ValueError('Unknown image-guidance profile')
    model_name,checksum=MODELS[profile]
    path=root/'models/guidance'/model_name
    if not path.is_file() or digest(path)!=checksum:raise ValueError('Image-guidance model is missing or failed verification')
    options=ort.SessionOptions()
    options.intra_op_num_threads=4;options.inter_op_num_threads=1
    options.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
    options.enable_mem_pattern=False
    options.enable_cpu_mem_arena=False
    started=perf_counter()
    session=ort.InferenceSession(str(path),sess_options=options,providers=['CPUExecutionProvider'])
    inputs,outputs=session.get_inputs(),session.get_outputs()
    if len(inputs)!=1 or list(inputs[0].shape)!=[1,3,448,448] or len(outputs)!=1 or list(outputs[0].shape)!=[1,7,448,448]:
        raise ValueError('Unsupported ShadeNet ONNX input/output contract')
    rows=[]
    for item in request['images']:
        image_path=(root/item['source']).resolve();output=(root/item['output']).resolve()
        if not image_path.is_relative_to(root) or not output.is_relative_to(root/'data/guidance') or image_path.suffix.lower() not in ('.png','.jpg','.jpeg'):
            raise ValueError('Invalid private guidance asset')
        if output.exists():raise ValueError('Guidance map output already exists')
        began=perf_counter()
        with Image.open(image_path) as image:
            if image.width*image.height>40_000_000:raise ValueError('Guidance input exceeds the image limit')
            original_size=list(image.size);square,box=letterbox(image)
        x=np.ascontiguousarray(square.transpose(2,0,1)[None].astype(np.float32)/127.5-1.)
        maps=detailed(session,inputs[0].name,outputs[0].name,x) if profile=='detailed' else session.run([outputs[0].name],{inputs[0].name:x})[0]
        if maps.shape!=(1,7,448,448) or not np.isfinite(maps).all():raise ValueError('Invalid ShadeNet output')
        left,top,w,h=box
        maps=np.clip(maps[0,:,top:top+h,left:left+w],-1,1).astype(np.float32)
        normals=maps[4:7];normals/=np.maximum(np.linalg.norm(normals,axis=0,keepdims=True),1e-6)
        output.parent.mkdir(parents=True,exist_ok=True)
        pending=output.with_suffix('.partial')
        with pending.open('xb') as stream:np.savez_compressed(stream,maps=maps,valid=np.ones((h,w),dtype=bool))
        pending.replace(output)
        rows.append(dict(key=item['key'],path=output.relative_to(root).as_posix(),sha256=digest(output),size=[w,h],imageSize=original_size,
                         pixelMapping='(original pixel + 0.5) * mapSize / imageSize - 0.5',letterbox=list(box),seconds=perf_counter()-began))
    from runtime_process import working_memory
    return dict(version=1,provider='ShadeNet-5-35M',revision=REVISION,profile=profile,modelSha256=checksum,
                normalBasis='x-right,y-up,z-toward-viewer',depthEncoding='relative-unverified',rows=rows,
                seconds=perf_counter()-started,memory=working_memory() if os.name=='nt' else {},torchImported='torch' in sys.modules,
                onnxruntime=ort.__version__,providers=session.get_providers())


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--request',type=Path,required=True);parser.add_argument('--response',type=Path,required=True)
    args=parser.parse_args();root=args.root.resolve()
    for path in (args.request.resolve(),args.response.resolve()):
        if not path.is_relative_to(root/'data/guidance'):raise ValueError('Invalid guidance job path')
    request=json.loads(args.request.read_text(encoding='utf-8'))
    from storage import atomic_json
    atomic_json(args.response,run(root,request))


if __name__=='__main__':main()
