import { Matrix3, Vector3 } from 'three';
import { editable, isReachJoint, limbParents, rotateJoint } from './editor';
import { forwardKinematics, previewRotations } from './pose';
import type { Pose, RigNode } from './types';

/** Small damped solve in existing DAZ channels. It never translates bones. */
export function moveLimb(pose:Pose,bone:string,targetCm:number[],iterations=12){
  if(!isReachJoint(bone)||targetCm.length!==3||targetCm.some(v=>!Number.isFinite(v)))return {pose,distanceCm:Infinity};
  const nodes=new Map(pose.rig.nodes.map(n=>[n.id,n])),end=nodes.get(bone);if(!end)return {pose,distanceCm:Infinity};
  const ancestors:RigNode[]=[];let current:RigNode|undefined=end;
  while(current){ancestors.push(current);current=current.parent?nodes.get(current.parent):undefined;}
  const chain=limbParents(pose,bone);
  const variables=chain.flatMap(n=>[0,1,2].filter(a=>editable(n,a)&&(!n.limits['xyz'[a]]?.clamped||n.limits['xyz'[a]].max-n.limits['xyz'[a]].min>1e-5)).map(axis=>({node:n,axis})));
  const rig={...pose.rig,nodes:ancestors.reverse()};
  const position=(p:Pose)=>forwardKinematics(rig,previewRotations(p),p.translation).get(bone)!.position;
  const target=new Vector3().fromArray(targetCm);let best=pose,error=position(pose).distanceTo(target);
  for(let iteration=0;iteration<iterations&&error>.03&&variables.length;iteration++){
    const at=position(best),columns=variables.map(({node,axis})=>{
      const angles=[...(best.rotations[node.id]??[0,0,0])],original=angles[axis];angles[axis]+=.05;
      let trial=rotateJoint(best,node.id,angles),step=(trial.rotations[node.id]?.[axis]??original)-original;
      if(Math.abs(step)<1e-8){angles[axis]=original-.05;trial=rotateJoint(best,node.id,angles);step=(trial.rotations[node.id]?.[axis]??original)-original;}
      return Math.abs(step)<1e-8?new Vector3():position(trial).sub(at).multiplyScalar(1/step);
    });
    const a=[.04,0,0,0,.04,0,0,0,.04];for(const c of columns){const v=c.toArray();for(let i=0;i<3;i++)for(let j=0;j<3;j++)a[i*3+j]+=v[i]*v[j];}
    const inverse=new Matrix3().set(a[0],a[1],a[2],a[3],a[4],a[5],a[6],a[7],a[8]).invert();
    const residual=target.clone().sub(at).clampLength(0,8).applyMatrix3(inverse),deltas=columns.map(c=>Math.max(-8,Math.min(8,c.dot(residual))));
    let improved=false;
    for(const factor of [1,.5,.25]){
      let trial=best;
      variables.forEach(({node,axis},i)=>{const angles=[...(trial.rotations[node.id]??[0,0,0])];angles[axis]+=deltas[i]*factor;trial=rotateJoint(trial,node.id,angles);});
      const next=position(trial).distanceTo(target);if(next<error-1e-6){best=trial;error=next;improved=true;break;}
    }
    if(!improved)break;
  }
  return {pose:best,distanceCm:error};
}
