import {describe,it,expect} from 'vitest';
import {existsSync,readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {Vector3,SkinnedMesh} from 'three';
import {Mannequin,installMannequin} from './mannequin';
import {neutralRig} from './pose';
import type {Rig,Pose} from './types';
const bytes=readFileSync('public/mannequin/surface.bin'),manifest=JSON.parse(readFileSync('public/mannequin/surface.json','utf8'));
installMannequin(manifest,bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength));
const pose=(rig:Rig):Pose=>({version:1,rigId:rig.id,label:'Stress',sourceId:rig.sourceId,imageId:'test',personId:1,rig,rotations:{},translation:[0,0,0],rootRotation:[0,0,0],warnings:[],handRefinement:true});
describe('supplied rigid posing mannequin',()=>{
  it('keeps the original faceless geometry and every source component',()=>{
    expect(manifest.source).toContain('6ead91e980434073bfb15799d3e674bb');expect(manifest.credit).toContain('BLENDERJO');expect(manifest.parts).toHaveLength(65);
    expect(manifest.position.count).toBe(268248);expect(manifest.index.count).toBe(535440);
    expect(createHash('sha256').update(bytes).digest('hex')).toBe('fa82c2121adab707ea57d55b86218caf9f9f33d523ebf48836d4d7c28038509a');
    const authorshipDirectory='assets/mannequin/source/blenderjo';
    if(existsSync(authorshipDirectory)){
      const source=JSON.parse(readFileSync(authorshipDirectory+'/source.json','utf8'));
      expect(manifest.position.count).toBe(source.vertices*3);expect(manifest.index.count).toBe(source.indices);
      expect(bytes.equals(readFileSync(authorshipDirectory+'/source.bin'))).toBe(true);
    }
  });
  for(const id of ['g8f','g8m','g9'] as const)it('preserves solid-part edge lengths under bend, twist and finger poses on '+id,()=>{
    const rig=JSON.parse(readFileSync('data/rigs/'+id+'.json','utf8')) as Rig,p=pose(rig),before=JSON.stringify(rig),m=new Mannequin(rig,1),mesh=m.group.children[0] as SkinnedMesh;
    const indices=mesh.geometry.index!,weights=mesh.geometry.getAttribute('skinWeight'),joints=mesh.geometry.getAttribute('skinIndex');let rigid=true;
    for(let i=0;i<weights.count;i++)if(weights.getX(i)!==1||weights.getY(i)!==0||weights.getZ(i)!==0||weights.getW(i)!==0)rigid=false;
    for(let i=0;i<indices.count;i+=3)if(joints.getX(indices.getX(i))!==joints.getX(indices.getX(i+1))||joints.getX(indices.getX(i))!==joints.getX(indices.getX(i+2)))rigid=false;
    expect(rigid).toBe(true);
    const edges=Array.from({length:1200},(_,n)=>{const index=Math.floor(n*(indices.count/3)/1200)*3,a=indices.getX(index),b=indices.getX(index+1);return {a,b,length:mesh.getVertexPosition(a,new Vector3()).distanceTo(mesh.getVertexPosition(b,new Vector3()))};});
    for(const twist of [-70,70]){
      const values:Record<string,number[]>={};
      for(const n of rig.nodes){let value:number[]|undefined;
        if(/ShldrBend|_upperarm/.test(n.id))value=[0,20,n.id[0]==='l'?70:-70];
        if(/ForearmBend|_forearm/.test(n.id))value=[id==='g9'?twist:0,n.id[0]==='l'?-95:95,0];
        if(/ForearmTwist/.test(n.id))value=[twist,0,0];
        if(/ThighBend|_thigh/.test(n.id))value=[-85,0,0];
        if(/Shin|_shin/.test(n.id))value=[120,0,0];
        if(/Hand|_hand/.test(n.id))value=[0,0,n.id[0]==='l'?40:-40];
        if(/(Index|Mid|Ring|Pinky)[123]|_(index|mid|ring|pinky)[123]/.test(n.id))value=[0,0,n.id[0]==='l'?-65:65];
        if(n.id==='head')value=[20,30,-20];
        if(value)values[n.id]=value.map((v,i)=>{const limit=n.limits['xyz'[i]];return limit?.locked?0:limit?.clamped?Math.min(limit.max,Math.max(limit.min,v)):v;});
      }
      m.update({...p,rotations:values,translation:[9,11,13],rootRotation:[15,25,-10]},'neon',true,'head');
      let error=0;for(const edge of edges)error=Math.max(error,Math.abs(mesh.getVertexPosition(edge.a,new Vector3()).distanceTo(mesh.getVertexPosition(edge.b,new Vector3()))-edge.length));
      expect(error).toBeLessThan(.000001);
    }
    expect(JSON.stringify(rig)).toBe(before);m.dispose();
  });
  it('supports the neutral workspace without a connected DAZ figure',()=>{const rig=neutralRig(),m=new Mannequin(rig,0);expect(m.group.children).toHaveLength(1);m.update(null,'light',true,'');expect(Array.from((m.group.children[0] as SkinnedMesh).geometry.getAttribute('position').array).every(Number.isFinite)).toBe(true);m.dispose();});
  it('reproduces the source rest geometry, including palm roll, thumbs and level soles',()=>{
    const m=new Mannequin(neutralRig(),0),mesh=m.group.children[0] as SkinnedMesh,original=new Float32Array(bytes.buffer,bytes.byteOffset+manifest.position.offset,manifest.position.count);let error=0;
    for(let i=0;i<original.length/3;i++)error=Math.max(error,mesh.getVertexPosition(i,new Vector3()).distanceTo(new Vector3().fromArray(original,i*3)));
    expect(error).toBeLessThan(.000001);m.dispose();
  });
});
