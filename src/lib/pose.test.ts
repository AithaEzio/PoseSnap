import { describe,it,expect } from 'vitest';
import { orientedPose,orientInteraction,forwardKinematics,neutralRig,quat,evaluatedChannels } from './pose';
import type { Pose } from './types';
describe('authoritative preview pose',()=>{
  const rig=neutralRig();
  const source:Pose={version:1,rigId:'g9',label:'Original',sourceId:'figure',imageId:'image',personId:1,rig,rotations:{lShin:[25,0,0]},translation:[0,0,0],warnings:[],handRefinement:true};
  it('preserves extraction when orientation changes',()=>{const adjusted=orientedPose(source,[0,180,0],2);expect(source.rootRotation).toBeUndefined();expect(adjusted.rotations).toEqual(source.rotations);expect(adjusted.rootRotation).toEqual([0,180,0]);});
  it('rotates a shared layout without independently centering its members',()=>{const a={...source,translation:[-20,0,15]},b={...source,personId:2,translation:[20,5,-15]};const group=orientInteraction([a,b],[0,90,0],3);const distance=(x:number[],y:number[])=>Math.hypot(...x.map((v,i)=>v-y[i]));expect(distance(group[0].translation,group[1].translation)).toBeCloseTo(distance(a.translation,b.translation),8);expect(group[0].translation[0]).toBeCloseTo(15);expect(group[1].translation[0]).toBeCloseTo(-15);expect(a.translation).toEqual([-20,0,15]);});
  it('uses the extrinsic DSON order captured in DAZ Studio',()=>{const {Euler,Quaternion}=requireThree;const values=[-27.8230934865061,60.12635187114582,21.88588302929555],r=Math.PI/180;const daz=new Quaternion().setFromEuler(new Euler(-values[0]*r,-values[1]*r,-values[2]*r,'YZX')).invert();expect(quat(values,'YZX').angleTo(daz)).toBeLessThan(1e-7);});
  it('evaluates selected-figure ERC scalars and addends in the preview',()=>{const driven={...rig,formulas:[{output:'rShin:#rShin?rotation/x',operations:[{op:'push' as const,url:'lShin:#lShin?rotation/x'},{op:'push' as const,val:-.75},{op:'mult' as const},{op:'push' as const,val:2.5},{op:'add' as const}]}]};expect(evaluatedChannels(driven,{lShin:[80,0,0]}).rShin[0]).toBe(-57.5);});
  it('places the lowest target endpoint at the selected floor offset',()=>{const pose=orientedPose(source,[90,0,0],3);const world=forwardKinematics(rig,{...pose.rotations,figure:pose.rootRotation!},pose.translation);let min=Infinity;for(const n of rig.nodes){if(n.type==='bone'){const s=world.get(n.id)!;const {Vector3}=requireThree;const end=new Vector3().fromArray(n.end).sub(new Vector3().fromArray(n.center)).applyQuaternion(s.rotation).add(s.position);min=Math.min(min,s.position.y,end.y);}}expect(min).toBeCloseTo(3,8);});
});
import * as requireThree from 'three';
