"""Headless private Kimodo subprocess. No model downloads or CPU motion fallback."""
import argparse
import base64
import contextlib
import json
import os
from pathlib import Path
import sys
import time


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--root', required=True)
    root = Path(parser.parse_args().root).resolve()
    sys.path[:0] = [str(root/'runtime/kimodo/deps'), str(root/'runtime/kimodo/core')]
    os.environ.update(CHECKPOINT_DIR=str(root/'models/kimodo'), HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    dll = os.add_dll_directory(str(root/'runtime/kimodo/encoder')) if hasattr(os, 'add_dll_directory') else None
    pipe = sys.stdout
    def send(value): pipe.write(json.dumps(value, allow_nan=False)+'\n'); pipe.flush()
    model = None; encoder = None
    import numpy as np
    import torch
    torch.set_num_threads(4)
    class Embedding:
        value = None
        def __call__(self, texts):
            if self.value is None: raise ValueError('The CPU embedding is missing.')
            return torch.from_numpy(self.value.copy()).reshape(1, 1, 4096).repeat(len(texts), 1, 1), [1]*len(texts)
    for line in sys.stdin:
        try:
            value = json.loads(line)
            with contextlib.redirect_stdout(sys.stderr):
                if value['method'] == 'load':
                    if not torch.cuda.is_available(): raise ValueError('Kimodo CUDA is unavailable. No CPU motion fallback is enabled.')
                    if not (root/'models/kimodo/Kimodo-SOMA-RP-v1.2/config.yaml').is_file(): raise ValueError('The pinned motion checkpoint is missing.')
                    from kimodo import load_model
                    encoder = Embedding()
                    model = load_model('Kimodo-SOMA-RP-v1.2', device='cuda', text_encoder=encoder)
                    torch.cuda.synchronize()
                    result = dict(loaded=True, device=torch.cuda.get_device_name(0))
                elif value['method'] == 'generate':
                    if model is None: raise ValueError('Load Kimodo before generating.')
                    data = base64.b64decode(value['embedding'], validate=True)
                    if len(data) != 4096*4: raise ValueError('Expected one 4096-value F32 embedding.')
                    encoder.value = np.frombuffer(data, dtype='<f4')
                    if not np.isfinite(encoder.value).all(): raise ValueError('Non-finite embedding.')
                    seeds = value['seeds']
                    if not isinstance(seeds, list) or not 1 <= len(seeds) <= 3 or any(type(s) is not int or not 0 <= s < 2**32 for s in seeds): raise ValueError('Invalid Kimodo sample seeds.')
                    output = Path(value['output']).resolve(); output.relative_to((root/'temp/kimodo').resolve())
                    paths = []; start = time.monotonic(); torch.cuda.reset_peak_memory_stats()
                    for index, seed in enumerate(seeds):
                        torch.manual_seed(seed); torch.cuda.manual_seed_all(seed)
                        def progress(indices):
                            for step, item in enumerate(indices):
                                if step % 5 == 0: send(dict(type='progress', label=f'Kimodo · Motion {index+1} of {len(seeds)} · step {step} of 100', percent=15+int(55*(index+step/100)/len(seeds))))
                                yield item
                        with torch.inference_mode():
                            batch = model([value['prompt']], num_frames=[90], num_denoising_steps=100, cfg_weight=[2., 2.], constraint_lst=[], post_processing=True, return_numpy=True, progress_bar=progress)
                        clip = {key:array[0] for key, array in batch.items()}
                        skeleton = model.output_skeleton
                        path = output/f'clip-{index}.npz'
                        np.savez_compressed(path, **clip, joint_names=np.asarray(skeleton.bone_order_names), rest_joints=skeleton.neutral_joints.detach().cpu().numpy(), parents=skeleton.joint_parents.detach().cpu().numpy(), seed=np.asarray(seed))
                        paths.append(str(path))
                    torch.cuda.synchronize()
                    result = dict(clips=paths, timings=dict(motionSeconds=time.monotonic()-start, peakVramBytes=torch.cuda.max_memory_allocated(), peakReservedVramBytes=torch.cuda.max_memory_reserved()))
                else: raise ValueError('Unknown Kimodo motion operation.')
            send(dict(type='result', result=result))
        except Exception as error:
            import traceback
            traceback.print_exc(file=sys.stderr)
            send(dict(type='error', message=str(error)))
    if dll: dll.close()


if __name__ == '__main__': main()
