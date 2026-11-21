/* Classic worker: MediaPipe's local Emscripten loaders use importScripts. */
let detector=null,base='';
importScripts('/expression-evidence.js');
async function initialize(url){
  if(detector)return;
  base=url;
  postMessage({type:'progress',label:'Starting local face engine',percent:12});
  importScripts(base+'/vision_bundle.js');
  const files=await Vision.FilesetResolver.forVisionTasks(base+'/wasm');
  detector=await Vision.FaceLandmarker.createFromOptions(files,{
    baseOptions:{modelAssetPath:base+'/model',delegate:'CPU'},runningMode:'IMAGE',
    numFaces:32,minFaceDetectionConfidence:0.5,minFacePresenceConfidence:0.5,
    outputFaceBlendshapes:true,outputFacialTransformationMatrixes:true
  });
}
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
function resultFaces(result,width,height){
  return result.faceLandmarks.map((points,i)=>{
    const minX=Math.min(...points.map(p=>p.x)),maxX=Math.max(...points.map(p=>p.x));
    const minY=Math.min(...points.map(p=>p.y)),maxY=Math.max(...points.map(p=>p.y));
    const pad=(maxY-minY)*.22;
    const box=[clamp((minX-pad)*width,0,width),clamp((minY-pad)*height,0,height),clamp((maxX+pad)*width,0,width),clamp((maxY+pad)*height,0,height)];
    return {id:i+1,box,landmarks:points.map(p=>[p.x*width,p.y*height,p.z*width]),actions:Object.fromEntries((result.faceBlendshapes[i]?.categories??[]).filter(c=>c.categoryName!=='_neutral').map(c=>[c.categoryName,c.score])),matrix:Array.from(result.facialTransformationMatrixes[i]?.data??[])};
  }).sort((a,b)=>a.box[0]-b.box[0]).map((f,i)=>({...f,id:i+1}));
}
self.onmessage=async({data})=>{
  let bitmap=data.bitmap;
  try{
    await initialize(data.base);
    if(data.type==='detect'){
      const windows=FaceEvidence.windows(bitmap.width,bitmap.height),candidates=[];
      for(let i=0;i<windows.length;i++){
        const window=windows[i],scale=Math.min(1,1600/Math.max(window.width,window.height)),canvas=new OffscreenCanvas(Math.round(window.width*scale),Math.round(window.height*scale));
        canvas.getContext('2d').drawImage(bitmap,window.x,window.y,window.width,window.height,0,0,canvas.width,canvas.height);
        const found=resultFaces(detector.detect(canvas),window.width,window.height).map(face=>({...face,box:face.box.map((v,j)=>v+(j%2?window.y:window.x)),landmarks:face.landmarks.map(p=>[p[0]+window.x,p[1]+window.y,p[2]]),resolution:canvas.width/window.width}));
        candidates.push(...found);
        // Quarter-turn recovery handles sideways/upside-down references. Empty
        // tiles only: ordinary portraits need no redundant rotation inference.
        if(!found.length){for(const angle of [Math.PI/2,-Math.PI/2,Math.PI]){
          const side=Math.max(window.width,window.height),size=Math.min(1024,Math.round(side)),rotated=new OffscreenCanvas(size,size),ctx=rotated.getContext('2d');ctx.fillStyle='#808080';ctx.fillRect(0,0,size,size);ctx.translate(size/2,size/2);ctx.rotate(-angle);ctx.drawImage(bitmap,window.x,window.y,window.width,window.height,-window.width/side*size/2,-window.height/side*size/2,window.width/side*size,window.height/side*size);
          const turned=resultFaces(detector.detect(rotated),size,size).map(face=>FaceEvidence.restore(face,{x:window.x-(side-window.width)/2,y:window.y-(side-window.height)/2,width:side,height:side},size,angle));
          candidates.push(...turned.map(face=>({...face,resolution:size/side})));if(turned.length)break;
        }}
        postMessage({type:'progress',label:`Finding faces · crop ${i+1}/${windows.length}`,percent:20+65*(i+1)/windows.length});
      }
      const faces=FaceEvidence.merge(candidates).map(face=>({...face,box:face.box.map((v,i)=>clamp(v,0,i%2?bitmap.height:bitmap.width))}));
      postMessage({type:'result',jobId:data.jobId,faces});
    }else if(data.type==='extract'){
      const box=data.box.map(Number),w=box[2]-box[0],h=box[3]-box[1];
      if(w<24||h<24)throw Error('This face is too small. Use a higher-resolution photograph.');
      postMessage({type:'progress',label:'Reading the selected face',percent:55});
      // Original pixels, aspect-preserving crop; never analyze a UI thumbnail.
      const size=768,cx=(box[0]+box[2])/2,cy=(box[1]+box[3])/2,roll=Number.isFinite(data.roll)?data.roll:0;
      function measure(context){
        const extent=Math.max(w,h)*context,canvas=new OffscreenCanvas(size,size),ctx=canvas.getContext('2d');
        ctx.fillStyle='#808080';ctx.fillRect(0,0,size,size);
        ctx.translate(size/2,size/2);ctx.rotate(-roll);ctx.drawImage(bitmap,cx-extent/2,cy-extent/2,extent,extent,-size/2,-size/2,size,size);
        const face=FaceEvidence.selected(resultFaces(detector.detect(canvas),size,size),size);
        const flip=new OffscreenCanvas(size,size),fctx=flip.getContext('2d');fctx.translate(size,0);fctx.scale(-1,1);fctx.drawImage(canvas,0,0);
        const mirrored=FaceEvidence.selected(resultFaces(detector.detect(flip),size,size),size);
        const differences=FaceEvidence.disagreement(face.actions,FaceEvidence.unflip(mirrored.actions));
        const pixels=canvas.getContext('2d').getImageData(0,0,size,size),flippedPixels=flip.getContext('2d').getImageData(0,0,size,size);
        const detail=FaceEvidence.details(face,pixels),mirroredDetail=FaceEvidence.details(mirrored,flippedPixels);
        return {face,canvas,extent,differences,detail,mirroredDetail,error:Object.values(differences).reduce((a,b)=>a+b,0)};
      }
      postMessage({type:'progress',label:'Checking facial asymmetry and crop consistency',percent:68});
      let measured=measure(1.12),passes=2;
      if(Object.values(measured.differences).some(v=>v>.3)){
        try{const alternative=measure(1.28);passes+=2;if(alternative.error<measured.error)measured=alternative;}catch(_){/* Keep the validated original ownership. */}
      }
      const best=FaceEvidence.restore(measured.face,{x:cx-measured.extent/2,y:cy-measured.extent/2,width:measured.extent,height:measured.extent},size,roll);
      const original=measured.detail,mirrored=measured.mirroredDetail,supplemental={};best.rawActions={...best.actions};best.extras={};
      for(const name of ['cheekPuff','jawOpen','browDownLeft','browDownRight','tongueOut']){
        const opposite=name.endsWith('Left')?name.slice(0,-4)+'Right':name.endsWith('Right')?name.slice(0,-5)+'Left':name;
        const paired=FaceEvidence.pairedDetail(name,original[name],mirrored[opposite]);
        if(name==='tongueOut'||name==='cheekPuff')supplemental[name]={...paired,method:name==='tongueOut'?'mouth-rgb-v1':'geometry-v1'};
        if(paired.accepted){if(name==='tongueOut')best.extras[name]=paired.value;else best.actions[name]=Math.max(best.actions[name]??0,paired.value);}
      }
      best.id=data.faceId;best.box=box;best.evidence={passes,consistency:measured.differences,supplemental,features:{...original.features,...Object.fromEntries(Object.entries(mirrored.features).map(([k,v])=>['mirrored'+k[0].toUpperCase()+k.slice(1),v]))}};
      postMessage({type:'result',jobId:data.jobId,face:best});
    }else throw Error('Unknown facial operation');
  }catch(error){postMessage({type:'error',jobId:data.jobId,message:String(error)});}
  finally{bitmap?.close();}
};
