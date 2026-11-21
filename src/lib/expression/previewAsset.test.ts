import { existsSync,readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { describe,expect,it,vi,afterEach } from 'vitest';
import * as THREE from 'three';
import { parseFacePreview,boundedFaceActions,coupledFaceActions,deformFacePositions,ExpressionFaceModel,type FacePreviewManifest } from './previewAsset';

function supplied(){
  const manifest=JSON.parse(readFileSync('public/expression-face/manifest.json','utf8'));
  const bytes=readFileSync('public/expression-face/face.bin'),buffer=new Uint8Array(bytes).buffer;
  return {manifest,buffer,asset:parseFacePreview(manifest,buffer)};
}
function fixture(){
  const buffer=new ArrayBuffer(124);
  new Float32Array(buffer,0,9).set([0,0,0,1,0,0,0,1,0]);
  new Float32Array(buffer,36,9).set([0,0,1,0,0,1,0,0,1]);
  new Uint32Array(buffer,72,3).set([0,1,2]);
  new Uint32Array(buffer,84,1).set([1]);new Float32Array(buffer,88,3).set([.2,.1,0]);
  new Uint32Array(buffer,100,3).set([0,1,2]);new Float32Array(buffer,112,3).set([0,0,0]);
  const manifest:FacePreviewManifest={version:1,binary:'face.bin',binaryBytes:124,sha256:'0'.repeat(64),coordinateConvention:'right-handed, Y-up, +Z front, metres',bounds:{min:[-1,-1,-1],max:[1,1,1]},eyes:[],actionLimits:{mouthSmileLeft:1},meshes:[{name:'Skin',positions:{offset:0,count:9,type:'Float32Array'},normals:{offset:36,count:9,type:'Float32Array'},index:{offset:72,count:3,type:'Uint32Array'},groups:[{start:0,count:3,materialIndex:0}],materials:[{name:'skin',color:[.7,.7,.7],roughness:.5}],morphs:{mouthSmileLeft:{indices:{offset:84,count:1,type:'Uint32Array'},deltas:{offset:88,count:3,type:'Float32Array'}}}}]};
  return {manifest,buffer};
}

describe('facial asset bounds and failure handling',()=>{
  it('rejects truncated, misaligned and out-of-bounds binary views',()=>{
    const {manifest,buffer}=fixture();expect(()=>parseFacePreview(manifest,buffer.slice(0,100))).toThrow('unsupported format');
    manifest.meshes[0].positions.offset=1;expect(()=>parseFacePreview(manifest,buffer)).toThrow('positions');
    manifest.meshes[0].positions.offset=120;expect(()=>parseFacePreview(manifest,buffer)).toThrow('positions');
  });
  it('rejects triangle and morph indices before creating a Three mesh',()=>{
    const {manifest,buffer}=fixture();new Uint32Array(buffer,72,3)[1]=3;expect(()=>parseFacePreview(manifest,buffer)).toThrow('triangle index');
    new Uint32Array(buffer,72,3)[1]=1;new Uint32Array(buffer,84,1)[0]=3;expect(()=>parseFacePreview(manifest,buffer)).toThrow('morph vertex');
  });
  it('rejects non-finite deltas, unknown controls and uncovered materials',()=>{
    const {manifest,buffer}=fixture();new Float32Array(buffer,88,3)[0]=NaN;expect(()=>parseFacePreview(manifest,buffer)).toThrow('non-finite');
    new Float32Array(buffer,88,3)[0]=.2;manifest.actionLimits={};expect(()=>parseFacePreview(manifest,buffer)).toThrow('unknown morph');
    manifest.actionLimits={mouthSmileLeft:1};manifest.meshes[0].groups=[];expect(()=>parseFacePreview(manifest,buffer)).toThrow('material coverage');
  });
  it('resets to the exact neutral coordinates without mutating the cached asset',()=>{
    const {manifest,buffer}=fixture(),mesh=parseFacePreview(manifest,buffer).meshes[0],original=mesh.positions.slice(),output=new Float32Array(mesh.positions.length);
    deformFacePositions(mesh,{mouthSmileLeft:1},output);expect(output[3]).toBeCloseTo(1.2);expect(output[4]).toBeCloseTo(.1);
    expect(mesh.positions).toEqual(original);deformFacePositions(mesh,{},output);expect(output).toEqual(original);
  });
  it('clips invalid/exaggerated preview values and couples opposing controls without editing source values',()=>{
    const source={jawOpen:1.5,mouthClose:1,jawLeft:.9,jawRight:.6,eyeBlinkLeft:1,eyeSquintLeft:.9,eyeWideLeft:1,mouthSmileLeft:NaN};
    const limits=Object.fromEntries(Object.keys(source).map(k=>[k,1]));
    expect(boundedFaceActions(source,limits).mouthSmileLeft).toBe(0);
    const result=coupledFaceActions(source,limits);expect(result.jawOpen).toBeCloseTo(.2);expect(result.jawLeft).toBeCloseTo(.3);expect(result.jawRight).toBe(0);expect(result.eyeBlinkLeft).toBeCloseTo(.75);expect(result.eyeSquintLeft).toBe(0);expect(source.jawOpen).toBe(1.5);expect(source.jawRight).toBe(.6);
  });
});

describe('supplied artist-derived facial rig',()=>{
  it('keeps clearance confined to the extended tongue and restores the actual model to neutral',()=>{
    const {asset}=supplied(),model=new ExpressionFaceModel(asset),raw={jawOpen:.35,tongueOut:1,mouthSmileLeft:.39,mouthSmileRight:.39},original={...raw};
    const surfaces=(model as unknown as {surfaces:{source:{name:string;positions:Float32Array};positions:Float32Array;geometry:THREE.BufferGeometry}[]}).surfaces;
    try{
      model.update(raw);const actions=coupledFaceActions(raw,asset.manifest.actionLimits);
      for(const source of asset.meshes){
        const expected=new Float32Array(source.positions.length);deformFacePositions(source,actions,expected);
        const actual=surfaces.find(s=>s.source.name===source.name)!;
        if(source.name!=='Tongue')expect(actual.positions).toEqual(expected);
        else{
          expect(actual.positions.slice(0,120*3)).toEqual(expected.slice(0,120*3));
          expect(Array.from(actual.positions.filter((_,i)=>i%3===2))).toEqual(Array.from(expected.filter((_,i)=>i%3===2)));
          expect(actual.positions.some((v,i)=>Math.abs(v-expected[i])>1e-6)).toBe(true);
          const normal=actual.geometry.attributes.normal.array;
          for(let i=1280;i<1320;i++)expect(Array.from(normal.slice(i*3,i*3+3))).toEqual(Array.from(normal.slice(1280*3,1280*3+3)));
        }
      }
      expect(raw).toEqual(original);model.update({});
      for(const surface of surfaces)expect(surface.positions).toEqual(surface.source.positions);
    }finally{model.dispose();}
  });
  it('has verified attribution, unchanged source and a small self-contained preview',()=>{
    const {manifest,buffer,asset}=supplied();expect(buffer.byteLength).toBeLessThan(8*1024**2);
    expect(createHash('sha256').update(new Uint8Array(buffer)).digest('hex')).toBe(manifest.sha256);
    expect(manifest.source.sha256).toBe('856f8516d6fe75cf24c06de05c6c652c5a95667cb764abdbb387746aaa50cac0');
    if(existsSync(manifest.source.file))expect(createHash('sha256').update(readFileSync(manifest.source.file)).digest('hex')).toBe(manifest.source.sha256);
    expect(manifest.source.artist).toBe('ComputerCat');expect(manifest.license.url).toBe('https://creativecommons.org/licenses/by/4.0/');
    expect(readFileSync('public/expression-face/LICENSE.txt','utf8')).toContain('ComputerCat');expect(asset.manifest.eyes.map(e=>e.side).sort()).toEqual(['Left','Right']);
    expect(manifest.actions).toHaveLength(51);expect(manifest.previewExtras).toEqual(['tongueOut']);expect(Object.keys(asset.manifest.actionLimits)).toHaveLength(52);
  });
  it('keeps left/right facial controls distinct and returns every mesh to neutral',()=>{
    const {asset}=supplied(),skin=asset.meshes.find(m=>m.name==='Skin')!,left=new Float32Array(skin.positions.length),right=left.slice();
    deformFacePositions(skin,coupledFaceActions({eyeBlinkLeft:1,mouthSmileLeft:.7},asset.manifest.actionLimits),left);
    deformFacePositions(skin,coupledFaceActions({eyeBlinkRight:1,mouthSmileRight:.7},asset.manifest.actionLimits),right);
    let difference=0,leftMotion=0,rightMotion=0;
    expect(left.every(Number.isFinite)&&right.every(Number.isFinite)).toBe(true);
    for(let i=0;i<left.length;i++){difference+=Math.abs(left[i]-right[i]);leftMotion+=Math.abs(left[i]-skin.positions[i]);rightMotion+=Math.abs(right[i]-skin.positions[i]);}
    expect(difference).toBeGreaterThan(.01);expect(leftMotion).toBeGreaterThan(.01);expect(rightMotion).toBeGreaterThan(.01);
    deformFacePositions(skin,{},left);expect(left).toEqual(skin.positions);
  });
  it('makes each morph finite, local and bounded; simultaneous strong actions remain finite',()=>{
    const {asset}=supplied();
    for(const mesh of asset.meshes){const output=new Float32Array(mesh.positions.length);
      for(const name of mesh.morphs.keys()){
        deformFacePositions(mesh,coupledFaceActions({[name]:1},asset.manifest.actionLimits),output);
        let peak=0;for(let i=0;i<output.length;i++)peak=Math.max(peak,Math.abs(output[i]-mesh.positions[i]));expect(peak).toBeLessThan(.10);
      }
      deformFacePositions(mesh,coupledFaceActions(Object.fromEntries(Object.keys(asset.manifest.actionLimits).map(k=>[k,1.5])),asset.manifest.actionLimits),output);
      expect(output.every(Number.isFinite)).toBe(true);
    }
  });
  it('uses anatomical eye pivots and leaves transforms unchanged on repeated updates',()=>{
    const {asset}=supplied(),model=new ExpressionFaceModel(asset);
    try{
      model.update({eyeLookOutLeft:1,eyeLookUpLeft:.5});
      const left=model.group.children.find(c=>c instanceof THREE.Group&&c.position.x>0)!,right=model.group.children.find(c=>c instanceof THREE.Group&&c.position.x<0)!;
      expect(left.rotation.y).toBeGreaterThan(0);expect(left.rotation.x).toBeLessThan(0);expect(right.rotation.y).toBeCloseTo(0);
      const mesh=model.group.children.find(c=>c instanceof THREE.Mesh) as THREE.Mesh;
      const version=(mesh.geometry.attributes.position as THREE.BufferAttribute).version;
      model.update({eyeLookOutLeft:1,eyeLookUpLeft:.5});expect((mesh.geometry.attributes.position as THREE.BufferAttribute).version).toBe(version);
      model.update({});expect(left.rotation.y).toBeCloseTo(0);expect(left.rotation.x).toBeCloseTo(0);
    }finally{model.dispose();}
    expect(model.group.children).toHaveLength(0);
  });
  it('renders iris and pupil material groups on the rotating eye meshes in the actual preview adapter',()=>{
    const {asset}=supplied(),model=new ExpressionFaceModel(asset);
    try{
      for(const eye of asset.manifest.eyes){
        const source=asset.meshes.find(m=>m.name===eye.mesh)!,pivot=model.group.children.find(c=>c instanceof THREE.Group&&Math.abs(c.position.x-eye.center[0])<1e-6) as THREE.Group;
        const mesh=pivot.children[0] as THREE.Mesh,materials=mesh.material as THREE.MeshStandardMaterial[];
        for(const region of ['Pupil','Iris blue grey','Limbal ring']){
          const at=source.definition.materials.findIndex(m=>m.name.startsWith(region));expect(at).toBeGreaterThanOrEqual(0);
          expect(mesh.geometry.groups.some(g=>g.materialIndex===at&&g.count>0)).toBe(true);
          expect(Math.max(materials[at].color.r,materials[at].color.g,materials[at].color.b)).toBeLessThan(.3);
        }
      }
      model.update({eyeLookOutLeft:.8,eyeLookInRight:.8});
      expect(model.group.children.filter(c=>c instanceof THREE.Group).every(c=>Math.abs(c.rotation.y)>.1)).toBe(true);
    }finally{model.dispose();}
  });
  it('includes attached oral geometry and bounded combination correctives',()=>{
    const {asset}=supplied();expect(asset.meshes.some(m=>m.name==='Tongue')).toBe(true);
    expect(asset.meshes.some(m=>m.correctives.size>=4)).toBe(true);
    const skin=asset.meshes.find(m=>m.name==='Skin')!,output=new Float32Array(skin.positions.length);
    const raw={jawOpen:.89,mouthSmileLeft:.81,mouthSmileRight:.86,mouthUpperUpLeft:.81,mouthLowerDownLeft:.91,tongueOut:1};
    const actions=coupledFaceActions(raw,asset.manifest.actionLimits);deformFacePositions(skin,actions,output);
    expect(output.every(Number.isFinite)).toBe(true);expect(actions.tongueOut).toBeGreaterThan(.9);
    expect(coupledFaceActions({tongueOut:1},asset.manifest.actionLimits).tongueOut).toBe(0);
    const total=['mouthUpperUpLeft','mouthSmileLeft','mouthStretchLeft','mouthFrownLeft','mouthPressLeft'].reduce((v,k)=>v+(actions[k]??0),0);expect(total).toBeLessThanOrEqual(1.65001);
    deformFacePositions(skin,{},output);expect(output).toEqual(skin.positions);
  });
  it('keeps the inner lip lining attached to the skin through jaw and lip combinations',()=>{
    const {manifest,asset}=supplied();
    const attachment:{mesh:string;surface:string;indices:number[];vertices?:number[]}=manifest.oralAttachments[0];
    expect(attachment.mesh).toBe('InnerLips');expect(attachment.surface).toBe('Skin');
    const skin=asset.meshes.find(m=>m.name===attachment.surface)!,lining=asset.meshes.find(m=>m.name===attachment.mesh)!;
    const vertices=attachment.vertices??Array.from({length:lining.positions.length/3},(_,index)=>index);
    expect(attachment.indices).toHaveLength(vertices.length);
    expect(new Set(vertices).size).toBe(vertices.length);
    expect(vertices.every(index=>Number.isInteger(index)&&index>=0&&index<lining.positions.length/3)).toBe(true);
    expect(attachment.indices.every(index=>Number.isInteger(index)&&index>=0&&index<skin.positions.length/3)).toBe(true);
    const posedSkin=new Float32Array(skin.positions.length),posedLining=new Float32Array(lining.positions.length);
    const cases=[{}, {jawOpen:1}, {jawOpen:.9,mouthSmileLeft:.8,mouthSmileRight:.9,mouthUpperUpLeft:.8,mouthLowerDownLeft:.9},
      {jawOpen:.7,mouthPucker:1,mouthRollLower:.6,mouthRollUpper:.4},
      {jawOpen:.8,mouthFunnel:1,mouthShrugLower:.6,mouthLowerDownRight:.8},
      {mouthSmileLeft:1,mouthFrownRight:.7,mouthUpperUpLeft:.6}, {cheekPuff:1,mouthPressLeft:.5,mouthPressRight:.5}];
    for(const strength of [1,1.5])for(const source of cases){
      const actions=coupledFaceActions(Object.fromEntries(Object.entries(source).map(([key,value])=>[key,value*strength])),asset.manifest.actionLimits);
      deformFacePositions(skin,actions,posedSkin);deformFacePositions(lining,actions,posedLining);
      let error=0;
      for(let i=0;i<attachment.indices.length;i++)for(let axis=0;axis<3;axis++){
        const surface=attachment.indices[i]*3+axis,inside=vertices[i]*3+axis;
        error=Math.max(error,Math.abs((posedLining[inside]-posedSkin[surface])-(lining.positions[inside]-skin.positions[surface])));
      }
      expect(error).toBeLessThan(1e-6);
    }
  });
});

afterEach(()=>{vi.unstubAllGlobals();vi.resetModules();});
describe('local asset loading',()=>{
  it('retries a failed fetch, coalesces concurrent requests and rejects a checksum mismatch',async()=>{
    const {manifest,buffer}=supplied();let calls=0,fail=true;
    vi.stubGlobal('fetch',async(url:string)=>{calls++;if(fail)return {ok:false};return url.endsWith('.json')?{ok:true,json:async()=>manifest}:{ok:true,arrayBuffer:async()=>buffer};});
    const {loadFacePreview}=await import('./previewAsset');
    await expect(loadFacePreview()).rejects.toThrow('missing');fail=false;
    const [first,second]=await Promise.all([loadFacePreview(),loadFacePreview()]);expect(first).toBe(second);expect(calls).toBe(4);
    vi.resetModules();const bad={...manifest,sha256:'0'.repeat(64)};
    vi.stubGlobal('fetch',async(url:string)=>url.endsWith('.json')?{ok:true,json:async()=>bad}:{ok:true,arrayBuffer:async()=>buffer});
    const module=await import('./previewAsset');await expect(module.loadFacePreview()).rejects.toThrow('checksum mismatch');
  });
});
