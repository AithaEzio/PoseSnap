"""Optional, local-only CLUE diagnostics for the unprompted SAM body prior.

The adapter never writes predictions, disables hand detection, or wraps the full
estimator. Its hook exists only until the initial body output has been copied.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import time

CODE_REVISION = 'df00480954d0fc5d4c2f4165f08da0c886ec3991'
HEAD_REVISION = '947d1d25c55837f723f6f1da49336483a032987d'
HEAD = 'models/diagnostics/clue/sam3dbody_clue.safetensors'
HEAD_BYTES = 5944836
HEAD_SHA256 = 'dd80913b928e0d36f1d30dfdd22cc44c4d20976e8172637aef6910c966c2f71f'


def enabled(root):
    from storage import read_json
    return read_json(root/'data/settings.json',{}).get('clueEnabled',False) is True


def region(name):
    name=name.removeprefix('c_')
    if re.search(r'(?:face|jaw|eye|lip|brow|tongue|teeth|finger|thumb|index|middle|ring|pinky|wrist)', name):return None
    if name.startswith(('l_', 'r_')):
        if re.search(r'clavicle|uparm|lowarm|elbow', name):return name[0]+'_arm'
        if re.search(r'upleg|lowleg|knee|foot|ball', name):return name[0]+'_leg'
    if name.startswith(('spine', 'root', 'hip', 'pelvis')):return 'torso'
    if name.startswith(('neck', 'head')):return 'head'
    return None


def regional_summaries(variance, owners):
    import numpy as np
    value=np.asarray(variance,dtype=np.float32)
    if value.shape!=(18439,3) or not np.isfinite(value).all() or np.any(value<0):
        raise ValueError('CLUE returned invalid body-prior variance')
    sigma=np.sqrt(value.sum(-1))
    return {name:dict(vertices=int(np.count_nonzero(owners==name)),medianCm=float(np.median(sigma[owners==name])),p90Cm=float(np.quantile(sigma[owners==name],.9)))
            for name in ('torso','head','l_arm','r_arm','l_leg','r_leg') if np.any(owners==name)}


def region_owners(model, plugin):
    """Static skin ownership: read-only CPU data for this loaded rig's lifetime."""
    import numpy as np
    import weakref
    rig=model.head_pose.mhr
    cached=model.__dict__.get('_posesnap_clue_regions')
    if cached is not None and cached[0]() is rig:return cached[1]
    names=list(rig.get_joint_names())
    state=plugin.uncertainty.clue.model.scripted_model.state_dict()
    ids=state['character_torch.linear_blend_skinning.skin_indices_flattened'].detach().cpu().numpy()
    vertices=state['character_torch.linear_blend_skinning.vert_indices_flattened'].detach().cpu().numpy()
    weights=state['character_torch.linear_blend_skinning.skin_weights_flattened'].detach().float().cpu().numpy()
    dominant=np.full(18439,-1,dtype=int);best=np.full(18439,-1.,dtype=float)
    for vertex,joint,weight in zip(vertices,ids,weights):
        if weight>best[vertex]:dominant[vertex]=joint;best[vertex]=weight
    owners=np.asarray([region(names[j]) if j>=0 else None for j in dominant],dtype=object)
    owners.flags.writeable=False
    model.__dict__['_posesnap_clue_regions']=(weakref.ref(rig),owners)
    return owners


class BodyPriorDiagnostic:
    def __init__(self, root, model, folder, person, source_signature, box):
        self.root,self.folder,self.person=root,folder,person
        self.source_signature,self.box=source_signature,list(box)
        self.plugin=None;self.started=time.perf_counter();self.error=None;self.result=None
        if not enabled(root):return
        path=root/HEAD
        if not path.is_file():return
        try:
            if path.stat().st_size!=HEAD_BYTES or hashlib.sha256(path.read_bytes()).hexdigest()!=HEAD_SHA256:
                raise ValueError('The optional CLUE head does not match its pinned checksum; import it again.')
            import torch
            from sam3dbody_clue import SAM3DBodyCLUE
            # Upstream's Python-MHR fallback reloads an already-installed rig.
            # A file object keeps Unicode Windows paths supported. It must stay
            # on the original device: moving a shared rig would change SAM.
            original=torch.jit.load
            def load(file,*args,**kwargs):
                if isinstance(file,(str,os.PathLike)):
                    with open(file,'rb') as stream:return original(stream,*args,**kwargs)
                return original(file,*args,**kwargs)
            torch.jit.load=load
            try:
                with torch.random.fork_rng(devices=[next(model.parameters()).device.index or 0]):
                    self.plugin=SAM3DBodyCLUE(model,weights=path)
            finally:torch.jit.load=original
            self.owners=region_owners(model,self.plugin)
        except Exception as error:
            self.error=str(error);self.close()

    def capture(self):
        if self.plugin is None:return
        try:
            import numpy as np
            variance=self.plugin.variance_cm2().detach().float().cpu().numpy().copy()
            if variance.shape!=(1,18439,3):raise ValueError('CLUE body-prior actor count changed')
            variance=variance[0];summaries=regional_summaries(variance,self.owners)
            from instances import identity
            person_key=identity(self.person)
            payload=dict(version=1,provider='CLUE',stage='sam-body-prior',personId=self.person['id'],personKey=person_key,
                         sourceSignature=self.source_signature,sourceBox=self.box,units=dict(variance='cm²',summary='cm'),
                         codeRevision=CODE_REVISION,headRevision=HEAD_REVISION,headSha256=HEAD_SHA256,regions=summaries,
                         limits='Initial unprompted body only. Root rotation/translation, final fitted pose, refined hands and expressions are excluded.')
            token=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()[:24]
            path=self.folder/('clue-prior-'+token+'.npz');temporary=path.with_suffix('.partial')
            with temporary.open('wb') as stream:np.savez_compressed(stream,varianceCm2=variance)
            temporary.replace(path)
            payload['array']=dict(path=path.relative_to(self.root).as_posix(),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),shape=[18439,3],dtype='float32')
            payload['elapsedSeconds']=time.perf_counter()-self.started
            self.result=payload
        except Exception as error:self.error=str(error)
        finally:self.close()

    def close(self):
        if self.plugin is not None:
            self.plugin.remove()
            self.plugin._last=None
            self.plugin=None
        self.owners=None


def note(value):
    labels={'torso':'torso','head':'head','l_arm':'left arm','r_arm':'right arm','l_leg':'left leg','r_leg':'right leg'}
    rows=', '.join(labels[k]+' '+format(v['medianCm'],'.1f')+' cm' for k,v in value['regions'].items())
    return 'Estimated source uncertainty · CLUE: '+rows+'. Regional medians describe the initial body estimate; they are not accuracy percentages or guaranteed error bounds. Final fit, refined hands and global spacing are excluded.'
