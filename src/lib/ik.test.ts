import { describe,it,expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { Vector3 } from 'three';
import { moveLimb } from './ik';
import { handleJoints,quickJoints } from './editor';
import { forwardKinematics,previewRotations } from './pose';
import { Mannequin,installMannequin } from './mannequin';
import { separateHandles,handleGlyph } from './handles';
import type { Pose,Rig,RigId } from './types';
const bytes=readFileSync('public/mannequin/surface.bin');installMannequin(JSON.parse(readFileSync('public/mannequin/surface.json','utf8')),bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength));
function sample(id:RigId):Pose{const rig=JSON.parse(readFileSync('data/rigs/'+id+'.json','utf8')) as Rig;return {version:1,rigId:id,label:'Test',sourceId:rig.sourceId,imageId:'test',personId:1,rig,rotations:{},translation:[3,4,5],rootRotation:[4,15,-8],warnings:[],handRefinement:true};}
describe('bounded direct limb movement',()=>{
  for(const id of ['g8f','g8m','g9'] as const)it('fits a hand on '+id+' without changing the rig or root',()=>{
    const p=sample(id),bone=id==='g9'?'l_hand':'lHand',before=JSON.stringify(p.rig),at=forwardKinematics(p.rig,previewRotations(p),p.translation).get(bone)!.position;
    const target=at.clone().add(new Vector3(-2,.5,2));const result=moveLimb(p,bone,target.toArray(),24);
    expect(result.distanceCm).toBeLessThan(.5);expect(result.pose.rig).toBe(p.rig);expect(JSON.stringify(p.rig)).toBe(before);expect(result.pose.translation).toEqual(p.translation);expect(result.pose.rootRotation).toEqual(p.rootRotation);
    for(const n of p.rig.nodes)for(let axis=0;axis<3;axis++){const value=result.pose.rotations[n.id]?.[axis]??0,limit=n.limits['xyz'[axis]];if(limit?.locked||n.driven?.includes('xyz'[axis]))expect(value).toBe(0);else if(limit?.clamped){expect(value).toBeGreaterThanOrEqual(limit.min-1e-6);expect(value).toBeLessThanOrEqual(limit.max+1e-6);}}
  });
  it('leaves unsupported and fully locked limbs alone',()=>{const p=sample('g9');expect(moveLimb(p,'head',[1,2,3]).pose).toBe(p);for(const n of p.rig.nodes)n.driven=['x','y','z'];expect(moveLimb(p,'l_hand',[1,2,3]).pose).toBe(p);expect(moveLimb(p,'l_hand',[NaN,1,2]).pose).toBe(p);});
  it('bounds unreachable foot targets and moves only limb channels',()=>{const p=sample('g9'),at=forwardKinematics(p.rig,previewRotations(p),p.translation).get('l_foot')!.position,target=at.clone().add(new Vector3(20,15,200)),fit=moveLimb(p,'l_foot',target.toArray());expect(Number.isFinite(fit.distanceCm)).toBe(true);expect(fit.distanceCm).toBeGreaterThan(100);expect(fit.distanceCm).toBeLessThan(at.distanceTo(target));expect(Object.keys(fit.pose.rotations).every(id=>/l_thigh|l_shin/.test(id))).toBe(true);});
});
describe('articulated mannequin binding',()=>{
  for(const id of ['g8f','g8m','g9'] as const)it('moves finite rigid pieces and follows exact target FK for '+id,()=>{
    const p=sample(id),before=JSON.stringify(p.rig),m=new Mannequin(p.rig,1),world=forwardKinematics(p.rig,previewRotations(p),p.translation);m.update(p,'dark',true,'head');
    for(const mesh of m.group.children as any[]){for(let vertex=0;vertex<mesh.geometry.getAttribute('position').count;vertex+=31)expect(mesh.getVertexPosition(vertex,new Vector3()).toArray().every(Number.isFinite)).toBe(true);for(const b of mesh.skeleton.bones)expect(new Vector3().setFromMatrixPosition(b.matrixWorld).distanceTo(world.get(b.name)!.position.clone().multiplyScalar(.01))).toBeLessThan(1e-7);}
    expect(JSON.stringify(p.rig)).toBe(before);expect(m.group.children.length).toBe(1);m.dispose();
  });
  it('limits pins to the active body group and hand side',()=>{const p=sample('g9');expect(handleJoints(p,'arms','l_hand').every(n=>/upperarm|forearm|hand/.test(n.id))).toBe(true);expect(handleJoints(p,'hands','r_index2').every(n=>n.id[0]==='r')).toBe(true);expect(quickJoints(p,'hands').length).toBe(32);});
  it('distinguishes finger segments and sides on handles',()=>{expect(handleGlyph('Left Index 2')).toBe('I2');expect(handleGlyph('Right Elbow')).toBe('RE');expect(handleGlyph('Left Shoulder')).toBe('LS');});
  it('separates crowded projected joints without moving their real anchors',()=>{const original=Array.from({length:8},(_,i)=>({id:String(i),label:'Joint',x:100,y:100,anchorX:100,anchorY:100})),spread=separateHandles(original,400,300);for(let i=0;i<spread.length;i++){expect(spread[i].anchorX).toBe(100);expect(spread[i].anchorY).toBe(100);for(let j=i+1;j<spread.length;j++)expect(Math.hypot(spread[i].x-spread[j].x,spread[i].y-spread[j].y)).toBeGreaterThan(30);}expect(original.every(p=>p.x===100&&p.y===100)).toBe(true);});
  it('preserves G8 twist channels and pelvis in the surface skeleton',()=>{const p=sample('g8m'),m=new Mannequin(p.rig,1);const mesh=m.group.children[0] as any;expect(mesh.skeleton.bones.map((b:any)=>b.name)).toContain('lForearmTwist');expect(mesh.skeleton.bones.map((b:any)=>b.name)).toContain('pelvis');p.rotations.lForearmTwist=[45,0,0];p.rotations.pelvis=[12,0,0];m.update(p,'neon',true,'lHand');const world=forwardKinematics(p.rig,previewRotations(p),p.translation);for(const bone of mesh.skeleton.bones)expect(bone.matrixWorld.equals(world.get(bone.name)!.matrix.clone().setPosition(world.get(bone.name)!.position.clone().multiplyScalar(.01)))).toBe(true);m.dispose();});
});
