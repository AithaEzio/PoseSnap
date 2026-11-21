"""Local staged inference. No from_pretrained network lookup is used at runtime."""
import copy, gc, json, os
from time import perf_counter
from storage import atomic_json, image_dir, read_json
from instances import identity, cached_source, source_path, SOURCE_VERSION

def fused_checkpoint(source):
    """Retain raw fused parameters before optimization, without another encoder."""
    return dict(version=1,stage='sam-fused',modelSignature=source['refinementSignature'],
                mhr=copy.deepcopy(source['mhr']),cameraTranslation=list(source['cameraTranslation']),
                quality=copy.deepcopy(source['quality']))

class Inference:
    def __init__(self, root):
        self.root=root
        self.model=None
        self.estimator=None
        self.diagnostic=None
        self.timings={}

    def release(self):
        if self.diagnostic is not None:self.diagnostic.close();self.diagnostic=None
        self.model=self.estimator=None
        gc.collect()
        import torch
        if torch.cuda.is_available():torch.cuda.empty_cache()


    def solve(self,payload,progress):
        from reference_guidance import AUTOMATIC_CUES_QUALIFIED, baseline_evidence, options
        settings=options(self.root,payload)
        mode=settings['imageGuidance']
        baseline=copy.deepcopy(self._solve(payload,progress))
        baseline['sourceGuidance']=dict(version=1,id='original')
        if mode=='off':
            return baseline
        if mode=='auto' and not AUTOMATIC_CUES_QUALIFIED:
            baseline['referenceEvidence']=baseline_evidence(settings)
            return baseline
        baseline_timings=dict(self.timings)
        started=perf_counter()
        try:
            result=self.guide_source(payload,baseline,settings,progress)
        except (ValueError,RuntimeError,OSError,ImportError,KeyError) as error:
            baseline['referenceEvidence']=dict(
                version=1,**settings,applied=False,fallback=True,outcome='fallback',
                notes=['Optional image guidance failed: '+str(error)])
            result=baseline
        self.timings=dict(baseline_timings,guidanceSeconds=perf_counter()-started)
        return result

    def guide_source(self,payload,source,settings,progress):
        from measurements import canonical
        from reference_guidance import (candidate_is_better,enrich,measurements,
                                        ordinal_pairs,prepare,prepare_masks,
                                        record,supplemental_measurements)
        image_id=source['imageId']
        mode=settings['imageGuidance']
        is_photo=record(self.root,image_id)['kind']=='photo'
        detailed=mode=='detailed' and is_photo
        summary=prepare(self.root,[image_id],'detailed',progress).get(image_id,{}) if detailed else {}
        summary.setdefault('notes',[])
        if detailed and summary.get('state')!='ready':
            return enrich(self.root,source,settings,summary,allow_cues=False)
        if detailed:
            mask_notes=prepare_masks(self.root,[source],progress,self)
            summary['notes'].extend(mask_notes.get((image_id,source['personKey']),[]))
            points,diagnostic=supplemental_measurements(self.root,source,summary)
            summary['measurementComparison']=diagnostic
        else:
            points=canonical(source)
        evidence=measurements(self.root,image_id,points,source['personKey'],mode,summary)
        sampled,normals,_=evidence
        if detailed and source.get('extractionMethod')=='pure' and not payload.get('_samOnly'):
            new_landmarks=summary['measurementComparison']['added']
            if new_landmarks>=4 or ordinal_pairs(sampled) and len(normals)>=2:
                progress('Comparing one guided body candidate',90)
                candidate=self._solve(dict(payload,_candidateOnly=True,_samOnly=True,_guidanceMask=True,
                                           _guidanceMeasurements=points),progress)
                better,comparison=candidate_is_better(source,candidate,sampled,normals,trusted=canonical(source))
                summary['candidateComparison']=comparison
                if better:
                    source=candidate
        return enrich(self.root,source,settings,summary,evidence=evidence)

    def _solve(self, payload, progress):
        started=perf_counter();timings=dict(cacheHit=False)
        import numpy as np
        import torch
        from PIL import Image
        folder=image_dir(self.root,payload['imageId'])
        people=read_json(folder/'people.json',[])
        person=next((p for p in people if p['id']==payload['personId']),None)
        if person is None:raise ValueError('Select one of the detected people first')
        from extraction import selected, pure_signature, PURE_VERSION
        choice=selected(self.root,payload)
        cache=source_path(folder,person,choice)
        cached=cached_source(folder,person,choice,raw=True)
        if payload.get('_candidateOnly'):cached=None
        if payload.get('refinement','accurate') not in ('standard','accurate'):raise ValueError('Unknown extraction refinement.')
        mode='pure' if choice=='pure' else 'accurate';sam_only=choice=='pure' or payload.get('_samOnly',False)
        if choice=='pure':signature_value=pure_signature(self.root)
        else:
            from wholebody import signature, available
            signature_value=signature(self.root)
            if not available(self.root):raise ValueError('Genesis Smart Fit models are missing. Download the whole-body and hand components, or choose Pure in Settings → Extractions.')
        depth_meta=read_json(folder/'image.json',{})
        if depth_meta.get('inputKind')=='metric-depth':
            from reference_depth import calibrated
            from measurements import stamp
            signature_value+='-'+stamp(calibrated(depth_meta))
        if cached is not None and not payload.get('refresh') and cached.get('refinementSignature')==signature_value:
            self.timings=dict(cacheHit=True,totalSeconds=perf_counter()-started)
            return cached
        if not torch.cuda.is_available():raise ValueError('An NVIDIA CUDA graphics driver is required for pose extraction')
        if torch.cuda.get_device_properties(0).total_memory<7*1024**3:raise ValueError('PoseSnap needs at least 8 GB of GPU memory')
        image=np.array(Image.open(folder/'source.png').convert('RGB'))
        input_meta=read_json(folder/'image.json',{})
        input_kind=input_meta.get('inputKind','photo')
        camera_file,provenance_file,camera_identity=self.camera_spec([image.shape[1],image.shape[0]],payload['imageId'],input_kind)
        camera=read_json(camera_file)
        if read_json(provenance_file)!=camera_identity or payload.get('refresh') and not payload.get('_alternate'):camera=None
        if camera is None:
            self.release()
            if input_kind=='photo':camera=self.camera(image,progress,folder)
            else:
                configured=input_meta.get('referenceDepth',{}).get('camera')
                h,w=image.shape[:2];f=max(w,h)/(2*np.tan(np.deg2rad(22.5)))
                camera=configured['intrinsics'] if configured else [[f,0,w/2],[0,f,h/2],[0,0,1]]
            atomic_json(camera_file,camera);atomic_json(provenance_file,camera_identity)
        overlaps=[p for p in people if p['id']!=person['id'] and self.overlap(person['box'],p['box'])>.05]
        mask=None
        if overlaps or payload.get('_guidanceMask'):
            self.release()
            from segmentation import selected_mask
            mask=selected_mask(self.root,folder,image,person,overlaps,progress)
        measurements=payload.get('_guidanceMeasurements',[]) if choice=='pure' else payload.get('_measurements')
        if measurements is None:
            progress('Checking visible body, hands and feet',40)
            from wholebody import Landmarker
            measurements=Landmarker(self.root).measure(image,person,overlaps,progress)
        progress('Loading body and hand model',42)
        if self.model is None:
            from sam_3d_body import load_sam_3d_body, SAM3DBodyEstimator
            checkpoint=self.root/'models/body/model.ckpt'
            mhr=self.root/'models/body/assets/mhr_model.pt'
            if not checkpoint.is_file() or not mhr.is_file():raise ValueError('SAM 3D Body weights are missing from models/body')
            original_hub_load=torch.hub.load
            original_jit_load=torch.jit.load
            def local_hub(repo,name,*args,**kwargs):
                if repo!='facebookresearch/dinov3':raise ValueError('Runtime model download is disabled')
                kwargs.pop('source',None)
                return original_hub_load(str(self.root/'vendor/dinov3'),name,*args,source='local',**kwargs)
            torch.hub.load=local_hub
            def local_jit(file,*args,**kwargs):
                # PyTorch's C++ filename loader uses narrow fopen on Windows.
                # Its documented file-object API keeps Unicode paths in Python.
                if isinstance(file,(str,os.PathLike)):
                    with open(file,'rb') as stream:return original_jit_load(stream,*args,**kwargs)
                return original_jit_load(file,*args,**kwargs)
            torch.jit.load=local_jit
            try:
                self.model,cfg=load_sam_3d_body(str(checkpoint),device='cuda',mhr_path=str(mhr))
                self.estimator=SAM3DBodyEstimator(self.model,cfg)
            finally:
                torch.hub.load=original_hub_load
                torch.jit.load=original_jit_load
        progress('Extracting the selected body and fingers',60)
        from evidence import landmarks, measured_prompts, conditioned_body, agreement, project
        evidence=landmarks(person,overlaps,mask[0,:,:,0] if mask is not None else None)
        prompts=evidence if choice=='pure' and not payload.get('_guidanceMeasurements') else measured_prompts(measurements,evidence)
        original_step=self.model.forward_step
        from body_uncertainty import BodyPriorDiagnostic,enabled
        prior_signature=__import__('hashlib').sha256(json.dumps([signature_value,payload['imageId'],identity(person),payload.get('_boxOverride',person['box'])],sort_keys=True).encode()).hexdigest()
        self.diagnostic=BodyPriorDiagnostic(self.root,self.model,folder,person,prior_signature,payload.get('_boxOverride',person['box'])) if enabled(self.root) else None
        diagnostic=self.diagnostic
        prompt_count=0;before=None;first_body=True
        def guided_step(batch,*args,**kwargs):
            nonlocal prompt_count,before,first_body
            output=original_step(batch,*args,**kwargs)
            if first_body and kwargs.get('decoder_type')=='body':
                first_body=False
                if diagnostic is not None:diagnostic.capture()
                before=agreement(output['mhr']['pred_keypoints_2d'][0].detach().float().cpu().numpy(),evidence,person['box'][3]-person['box'][1])
                output,prompt_count=conditioned_body(self.model,batch,output,prompts,person['box'][3]-person['box'][1],rounds=2 if choice=='pure' else 4)
            return output
        with torch.inference_mode():
            self.model.forward_step=guided_step
            sam_started=perf_counter()
            try:
                outputs=self.estimator.process_one_image(image,bboxes=np.asarray([payload.get('_boxOverride',person['box'])],dtype=np.float32),
                    masks=mask,cam_int=torch.tensor(camera,device='cuda',dtype=torch.float32)[None],inference_type='full')
            finally:
                self.model.forward_step=original_step
                if diagnostic is not None:diagnostic.close()
                self.diagnostic=None
            timings['samInferenceSeconds']=perf_counter()-sam_started
            if len(outputs)!=1:raise ValueError('The selected-person model returned an unexpected result')
            output=outputs[0]
            progress('Reconstructing refined hand rotations',87)
            head=self.model.head_pose
            def tensor(name):return torch.as_tensor(output[name],device='cuda',dtype=torch.float32).reshape(1,-1)
            # Upstream issue #139: pred_global_rots can refer to the pre-refinement hand pass.
            # Run the final fused parameters through MHR again for ALL export rotations.
            _,keypoints,points,model_params,rotations=head.mhr_forward(global_trans=torch.zeros((1,3),device='cuda'),global_rot=tensor('global_rot'),
                body_pose_params=tensor('body_pose_params'),hand_pose_params=tensor('hand_pose_params'),scale_params=tensor('scale_params'),
                shape_params=tensor('shape_params'),expr_params=tensor('expr_params'),return_keypoints=True,return_joint_coords=True,return_joint_rotations=True,return_model_params=True)
            # Evaluate neutral rig using the same predicted shape/scale, excluding pose and expressions.
            _,rest_points,rest_rotations=head.mhr_forward(global_trans=torch.zeros((1,3),device='cuda'),global_rot=torch.zeros((1,3),device='cuda'),
                body_pose_params=torch.zeros_like(tensor('body_pose_params')),hand_pose_params=None,scale_params=tensor('scale_params'),
                shape_params=tensor('shape_params'),expr_params=torch.zeros_like(tensor('expr_params')),return_joint_coords=True,return_joint_rotations=True)
            names=list(head.mhr.get_joint_names())
            parents=head.mhr.character_torch.skeleton.joint_parents.cpu().numpy().tolist()
            # mhr_forward returns right-handed Y-up transforms, like DSON. The
            # estimator's image-camera Y/Z flips must NOT be applied to this fresh output.
            basis=np.eye(3)
            transform=lambda matrix:(matrix.detach().float().cpu().numpy()[0]@basis.T).tolist()
            camera_points=keypoints.detach().float().cpu().numpy()[0,:70]*[1,-1,-1]
            cam_t=np.asarray(output['pred_cam_t'],dtype=float).reshape(3)
            focal=float(np.asarray(output['focal_length']).reshape(-1)[0]);size=[image.shape[1],image.shape[0]]
            projected=project(camera_points,cam_t,focal,size)
            quality=dict(detection=float(person['score']),visible=agreement(projected,evidence,person['box'][3]-person['box'][1]),before=before,prompts=prompt_count)
            result=dict(version=SOURCE_VERSION,imageId=payload['imageId'],personId=person['id'],personKey=identity(person),names=names,parents=parents,
                positions=transform(points),restPositions=transform(rest_points),
                keypoints3d=transform(keypoints[:,:70]),
                rotations=(basis@rotations.detach().float().cpu().numpy()[0]).tolist(),
                restRotations=(basis@rest_rotations.detach().float().cpu().numpy()[0]).tolist(),
                camera=camera,cameraTranslation=cam_t.tolist(),focalLength=focal,imageSize=size,projectedKeypoints=projected.tolist(),evidence=evidence,contactEvidence=landmarks(person,overlaps),quality=quality,
                personBox=person['box'],refinementMode=mode,refinementSignature=signature_value,extractionMethod=choice,
                detectorKeypoints=person.get('keypoints',[]),
                handAcceptance={side:dict(zip(('accepted','angle','cropSize','insideCrop','wristAgreement'),map(bool,values))) for side,values in zip(('l','r'),output.get('hand_acceptance',np.zeros((2,5))))},
                mhr=dict(modelParams=model_params.detach().float().cpu().numpy()[0].tolist(),shapeParams=np.asarray(output['shape_params']).reshape(-1).tolist(),exprParams=np.asarray(output['expr_params']).reshape(-1).tolist(),
                    keypointMapping=[dict(indices=(row!=0).nonzero()[0].tolist(),weights=row[row!=0].tolist()) for row in head.keypoint_mapping.detach().float().cpu().numpy()[:70]]),
                handRefinement=True,warnings=['Single-image depth and hidden fingers are estimates.'] + (['Touching bodies were masked separately and landmark-guided; inspect occluded limbs and fingers carefully.'] if overlaps else []) + (['This person has lower detection confidence. Verify the selected subject before exporting.'] if person['score']<.6 else []))
            # Parameter arrays are not positions: do not apply the spatial basis transform.
            result['mhr']['modelParams']=model_params.detach().float().cpu().numpy()[0].tolist()
        result['samBaseline']=fused_checkpoint(result)
        if diagnostic is not None and diagnostic.result:result['sourceDiagnostics']=[diagnostic.result]
        elif diagnostic is not None and diagnostic.error:result['warnings'].append('Optional body uncertainty is unavailable. Ordinary extraction is unchanged; verify the CLUE component. '+diagnostic.error[:180])
        if choice=='pure':result['pureVersion']=PURE_VERSION
        else:result['measurements']=measurements
        if not sam_only:
            # Bound methods/closures retain the image encoder after self.model is cleared.
            del original_step,guided_step,head,tensor,outputs,output
            del keypoints,points,model_params,rotations,rest_points,rest_rotations,_
            self.release()
            progress('Fitting the extracted pose to measured details',88)
            if mask is not None:
                plane=mask[0,:,:,0]
                for item in result['measurements']:
                    x,y=map(lambda v:int(round(v)),item['xy'])
                    item['visibleInMask']=bool(0<=y<plane.shape[0] and 0<=x<plane.shape[1] and plane[y,x])
            from refinement import refine_sources
            refine_started=perf_counter()
            result=refine_sources(self.root,[result],[],progress)[0]
            timings['sourceRefinementSeconds']=perf_counter()-refine_started
            result['contextPass']=dict(attempted=False,accepted=False)
            if not payload.get('_alternate') and result.get('sourceRefinement',{}).get('finalImageLoss',0)>1.5:
                # One changed-context inference can add information at crop boundaries.
                # It never overwrites an accepted source before comparison.
                box=np.asarray(person['box'],dtype=float);extent=(box[2:]-box[:2])*.08
                alternate=np.r_[np.maximum(0,box[:2]-extent),np.minimum([image.shape[1],image.shape[0]],box[2:]+extent)].tolist()
                progress('Trying one wider-context candidate for unresolved details',94)
                retry_started=perf_counter()
                candidate=self._solve(dict(payload,refresh=True,_alternate=True,_candidateOnly=True,_samOnly=True,_measurements=measurements,_boxOverride=alternate),lambda label,percent:progress(label,94+round(percent*.03)))
                self.release();candidate['measurements']=result['measurements'];candidate['personBox']=person['box']
                candidate=refine_sources(self.root,[candidate],[],progress,start=97,end=99)[0]
                candidate_fit=candidate.get('sourceRefinement',{})
                better=candidate_fit.get('accepted',False) and candidate_fit.get('finalImageLoss',float('inf'))<result['sourceRefinement']['finalImageLoss'] and candidate_fit.get('finalBodyErrorPx',float('inf'))<=result['sourceRefinement'].get('finalBodyErrorPx',0)*1.05+2
                if better:
                    candidate.update(refinementMode=mode,refinementSignature=signature_value);result=candidate
                result['contextPass']=dict(attempted=True,accepted=better)
                timings['contextRetrySeconds']=perf_counter()-retry_started
        if not payload.get('_candidateOnly'):atomic_json(cache,result)
        progress('Pose extracted',100)
        self.timings=dict(timings,totalSeconds=perf_counter()-started)
        return result


    def camera_spec(self,size,image_id,kind='photo'):
        from cache_provenance import stage_signature
        folder=image_dir(self.root,image_id)
        camera_file=folder/('camera-depth-input.json' if kind!='photo' else 'camera.json')
        files=('worker/inference.py','worker/camera_depth.py','models/camera/model.pt','vendor/MoGe/moge/model/v2.py')
        identity=dict(version=1,imageId=image_id,imageSize=size,signature=stage_signature(self.root,files))
        if kind!='photo':identity.update(inputKind=kind,geometryEngine='moge2')
        if kind=='metric-depth':identity['referenceDepth']=read_json(folder/'image.json',{}).get('referenceDepth')
        return camera_file,camera_file.with_name(camera_file.stem+'-provenance.json'),identity

    def prepare_geometry(self,image_ids,progress):
        from reference_guidance import record
        from PIL import Image
        import numpy as np
        pending=[];rows=[]
        for image_id in dict.fromkeys(image_ids):
            item=record(self.root,image_id)
            if item['kind']!='photo':continue
            path,provenance,identity=self.camera_spec(item['imageSize'],image_id)
            from camera_depth import load_normals
            hit=read_json(provenance)==identity and path.is_file() and load_normals(self.root,path.parent) is not None
            rows.append(dict(imageId=image_id,cacheHit=hit))
            if not hit:pending.append((item,path,provenance,identity))
        if not pending:return rows
        self.release();model=None
        try:
            from moge.model.v2 import MoGeModel
            model=MoGeModel.from_pretrained(str(self.root/'models/camera/model.pt')).to('cuda').eval()
            for index,(item,path,provenance,identity) in enumerate(pending):
                progress('Preparing geometry for view '+str(index+1)+' of '+str(len(pending)),20)
                began=perf_counter()
                with Image.open(self.root/item['source']) as image:pixels=np.asarray(image.convert('RGB'))
                camera=self.camera(pixels,progress,path.parent,model=model)
                atomic_json(path,camera);atomic_json(provenance,identity)
                next(row for row in rows if row['imageId']==item['imageId'])['seconds']=perf_counter()-began
        finally:
            model=None;gc.collect()
            import torch
            if torch.cuda.is_available():torch.cuda.empty_cache()
        return rows

    def camera(self,image,progress,folder=None,model=None):
        import numpy as np
        import torch
        from moge.model.v2 import MoGeModel
        weight=self.root/'models/camera/model.pt'
        if not weight.is_file():raise ValueError('Camera model is missing: '+weight.relative_to(self.root).as_posix())
        progress('Estimating the image camera',20)
        owns_model=model is None
        if model is None:
            model=MoGeModel.from_pretrained(str(weight)).to('cuda').eval()
        try:
            with torch.inference_mode():
                frame=torch.from_numpy(image.copy()).permute(2,0,1).float().cuda()/255
                output=model.infer(frame,resolution_level=5)
                intrinsics=output['intrinsics'].detach().cpu().numpy()
            h,w=image.shape[:2]
            intrinsics[0,:]*=w;intrinsics[1,:]*=h;intrinsics[0,0]=intrinsics[1,1]
            if folder is not None and 'depth' in output:
                from camera_depth import save
                depth=output['depth'].detach().float().cpu().numpy()
                mask=output.get('mask')
                valid=mask.detach().bool().cpu().numpy() if mask is not None else np.isfinite(depth)&(depth>0)
                normal=output.get('normal')
                normal=normal.detach().float().cpu().numpy() if normal is not None else None
                try:save(self.root,folder,image,intrinsics.tolist(),depth,valid,normal)
                except (ValueError,OSError):pass  # Optional spacing evidence must not block extraction.
            return intrinsics.tolist()
        finally:
            model=output=frame=None
            gc.collect()
            if owns_model:torch.cuda.empty_cache()

    @staticmethod
    def overlap(a,b):
        intersection=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
        return intersection/max(1,min((a[2]-a[0])*(a[3]-a[1]),(b[2]-b[0])*(b[3]-b[1])))
