import { describe,expect,it } from 'vitest';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

function face(actions:Record<string,number>,x=.5){
  return {faceLandmarks:[Array.from({length:478},(_,i)=>({x:x+(i%2?-.12:.12),y:i%2?.35:.65,z:.02}))],faceBlendshapes:[{categories:Object.entries(actions).map(([categoryName,score])=>({categoryName,score}))}],facialTransformationMatrixes:[{data:[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]}]};
}
function worker(results:ReturnType<typeof face>[]){
  const messages:any[]=[],draws:any[]=[],options:any[]=[];
  let closed=false,calls=0;
  class Canvas {
    constructor(public width:number,public height:number){}
    getContext(){return {fillStyle:'',fillRect(){},translate(){},rotate(){},scale(){},getImageData(){return {width:768,height:768,data:new Uint8ClampedArray(768*768*4)};},drawImage(...args:any[]){draws.push(args);}};}
  }
  const context:any={self:{},OffscreenCanvas:Canvas,postMessage:(message:any)=>messages.push(message)};
  context.importScripts=(path:string)=>{
    if(path==='/expression-evidence.js')vm.runInNewContext(readFileSync('public/expression-evidence.js','utf8'),context);
    else context.Vision={FilesetResolver:{forVisionTasks:async()=>({})},FaceLandmarker:{createFromOptions:async(_:unknown,value:any)=>{options.push(value);return {detect:()=>results[calls++]};}}};
  };
  vm.runInNewContext(readFileSync('public/expression-worker.js','utf8'),context);
  const bitmap={width:1000,height:800,close(){closed=true;}};
  return {messages,draws,options,get closed(){return closed;},get calls(){return calls;},async run(type='extract'){if(type==='detect')bitmap.width=800;await context.self.onmessage({data:{type,jobId:'face-test',base:'local',bitmap,box:[200,150,600,550],faceId:2}});return messages.at(-1);}};
}

describe('facial worker crop and evidence pipeline',()=>{
  it('uses local CPU assets and maps selected original pixels back correctly',async()=>{
    const f=worker([face({eyeBlinkLeft:.9,eyeBlinkRight:.1}),face({eyeBlinkLeft:.1,eyeBlinkRight:.9})]);
    const result=await f.run();expect(result.type).toBe('result');expect(result.face.id).toBe(2);
    expect(result.face.actions.eyeBlinkLeft).toBe(.9);expect(result.face.actions.eyeBlinkRight).toBe(.1);
    expect(result.face.landmarks[0][0]).toBeCloseTo(453.76);expect(result.face.landmarks[0][1]).toBeCloseTo(417.2);
    expect(result.face.evidence.passes).toBe(2);expect(f.options[0].baseOptions).toEqual({modelAssetPath:'local/model',delegate:'CPU'});
    f.draws[0].slice(1,5).forEach((value:number,i:number)=>expect(value).toBeCloseTo([176,126,448,448][i]));expect(f.closed).toBe(true);
  });
  it('adds context only for conflicting evidence and keeps one measured candidate',async()=>{
    const f=worker([face({eyeBlinkLeft:.9,eyeBlinkRight:.1}),face({eyeBlinkLeft:.9,eyeBlinkRight:.1}),face({eyeBlinkLeft:.7,eyeBlinkRight:.2}),face({eyeBlinkLeft:.2,eyeBlinkRight:.7})]);
    const result=await f.run();expect(result.face.actions).toMatchObject({eyeBlinkLeft:.7,eyeBlinkRight:.2});expect(result.face.evidence.passes).toBe(4);expect(result.face.evidence.consistency.eyes).toBe(0);expect(f.calls).toBe(4);expect(f.closed).toBe(true);
  });
  it('rejects a neighboring face and releases the transferred bitmap',async()=>{
    const f=worker([face({jawOpen:.4},.95)]);const result=await f.run();expect(result.type).toBe('error');expect(result.message).toContain('ambiguously');expect(result.jobId).toBe('face-test');expect(f.closed).toBe(true);
  });
  it('detects all faces with stable left-to-right labels in original coordinates',async()=>{
    const right=face({jawOpen:.4},.75),left=face({jawOpen:.1},.25);
    right.faceLandmarks.push(left.faceLandmarks[0]);right.faceBlendshapes.push(left.faceBlendshapes[0]);right.facialTransformationMatrixes.push(left.facialTransformationMatrixes[0]);
    const f=worker([right]);const result=await f.run('detect');expect(result.faces.map((v:any)=>v.id)).toEqual([1,2]);expect(result.faces[0].actions.jawOpen).toBe(.1);expect(result.faces[1].actions.jawOpen).toBe(.4);expect(result.faces[0].box[0]).toBeCloseTo(51.2);expect(f.closed).toBe(true);
  });
});
