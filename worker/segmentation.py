"""Verified selected-instance masks, loaded before the 3D network."""
import gc, os
from storage import atomic_json, read_json
from instances import identity, mask_prompts, mask_quality

def selected_mask(root, folder, image, person, others, progress):
    import numpy as np
    import torch
    from PIL import Image
    from sam2.build_sam import build_sam2
    from sam2.sam2_image_predictor import SAM2ImagePredictor
    if not person.get('keypoints') or any(not p.get('keypoints') for p in others):
        raise ValueError('Overlapping bodies need the instance-aware detector. Restore the local RTMO checkpoint and Recheck people.')
    key=identity(person)
    context=[identity(p) for p in others]
    metadata=folder/f'mask-{key}.json'; path=folder/f'mask-{key}.png'
    positive, negative=mask_prompts(person,others)
    from cache_provenance import stage_signature
    expected=dict(version=2,context=sorted(context),personKey=key,imageSize=[image.shape[1],image.shape[0]],signature=stage_signature(root,('worker/segmentation.py','worker/instances.py','models/segmentation/sam2.1_hiera_tiny.pt','vendor/sam2/sam2/configs/sam2.1/sam2.1_hiera_t.yaml')))
    if path.is_file() and read_json(metadata)==expected:
        try:
            with Image.open(path) as opened: mask=np.array(opened.convert('L'))>0
            if mask.shape==image.shape[:2] and mask_quality(mask,positive,negative):return mask.astype(np.uint8)[None,...,None]
        except (OSError,ValueError):pass
    weight=root/'models/segmentation/sam2.1_hiera_tiny.pt'
    if not weight.is_file():raise ValueError('Overlapping people need the local SAM 2.1 Tiny model.')
    progress('Separating the selected person from their partner',34)
    model=predictor=None
    try:
        model=build_sam2('configs/sam2.1/sam2.1_hiera_t.yaml',str(weight),device='cuda',apply_postprocessing=False)
        predictor=SAM2ImagePredictor(model)
        with torch.inference_mode():
            predictor.set_image(image)
            masks,scores,_=predictor.predict(box=np.asarray(person['box'],dtype=np.float32),
                point_coords=np.asarray(positive+negative,dtype=np.float32),
                point_labels=np.asarray([1]*len(positive)+[0]*len(negative),dtype=np.int32),multimask_output=True)
        candidates=[i for i,mask in enumerate(masks) if mask_quality(mask,positive,negative)]
        if not candidates:raise ValueError('The touching bodies could not be separated reliably. Use Recheck people or a reference with more visible anatomy; a combined pose was not generated.')
        mask=masks[max(candidates,key=lambda i:float(scores[i]))].astype(np.uint8)
        if mask.sum()<max(32,image.shape[0]*image.shape[1]*.0001):raise ValueError('The selected-person mask is too small. Try a clearer reference.')
        pending=path.with_suffix('.png.pending')
        Image.fromarray(mask*255).save(pending,format='PNG')
        os.replace(pending,path)
        atomic_json(metadata,expected)
        return mask[None,...,None]
    finally:
        del predictor,model
        gc.collect();torch.cuda.empty_cache()
