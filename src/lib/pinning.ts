import { Quaternion, Vector3 } from 'three';
import { editable, figureKey, rotateJoint } from './editor';
import { forwardKinematics, previewRotations } from './pose';
import type { JointPin, Pose, RigNode } from './types';

const world=(pose:Pose)=>forwardKinematics(pose.rig,previewRotations(pose),pose.translation);
export function togglePin(pose:Pose,bone:string,component:keyof JointPin):Pose {
  const node=pose.rig.nodes.find(n=>n.id===bone&&n.type==='bone');
  if(!node)return pose;
  const pins={...pose.pins},pin={...pins[bone]};
  if(pin[component])delete pin[component];
  else {const frame=world(pose).get(bone)!;pin[component]=component==='position'?frame.position.toArray():frame.rotation.toArray();}
  if(pin.position||pin.rotation)pins[bone]=pin;else delete pins[bone];
  return {...pose,pins};
}
export function clearPins(pose:Pose,bone?:string,withChildren=false):Pose {
  if(!pose.pins||!Object.keys(pose.pins).length)return pose;
  if(!bone||bone===figureKey&&withChildren)return {...pose,pins:undefined};
  const ids=new Set([bone]);
  if(withChildren)for(let changed=true;changed;){changed=false;for(const n of pose.rig.nodes)if(n.parent&&ids.has(n.parent)&&!ids.has(n.id)){ids.add(n.id);changed=true;}}
  const pins=Object.fromEntries(Object.entries(pose.pins).filter(([id])=>!ids.has(id)));
  return {...pose,pins};
}
export function pinErrors(pose:Pose){
  if(!Object.keys(pose.pins??{}).length)return [];
  const frames=world(pose);
  return Object.entries(pose.pins??{}).flatMap(([bone,pin])=>{
    const frame=frames.get(bone);if(!frame)return [];
    return [{bone,distanceCm:pin.position?frame.position.distanceTo(new Vector3().fromArray(pin.position)):null,
      angleDegrees:pin.rotation?frame.rotation.angleTo(new Quaternion().fromArray(pin.rotation))*180/Math.PI:null}];
  });
}
/** Symmetric positive-definite normal system with pivoting, no extra runtime. */
function linearSolve(matrix:number[][],values:number[]){
  const rows=matrix.map((r,i)=>[...r,values[i]]),n=values.length;
  for(let i=0;i<n;i++){
    let pivot=i;for(let j=i+1;j<n;j++)if(Math.abs(rows[j][i])>Math.abs(rows[pivot][i]))pivot=j;
    if(Math.abs(rows[pivot][i])<1e-12)return values.map(()=>0);
    [rows[i],rows[pivot]]=[rows[pivot],rows[i]];
    const scale=rows[i][i];for(let j=i;j<=n;j++)rows[i][j]/=scale;
    for(let k=i+1;k<n;k++){const factor=rows[k][i];for(let j=i;j<=n;j++)rows[k][j]-=factor*rows[i][j];}
  }
  const out=Array(n).fill(0);for(let i=n-1;i>=0;i--){out[i]=rows[i][n];for(let j=i+1;j<n;j++)out[i]-=rows[i][j]*out[j];}
  return out;
}
/** Coupled, soft world-space pins. Only editable driving rotations can change. */
export function preservePins(requested:Pose,editedBone=figureKey,iterations=12):Pose {
  const pins=Object.entries(requested.pins??{});if(!pins.length)return requested;
  const nodes=new Map(requested.rig.nodes.map(n=>[n.id,n])),included=new Set<string>();
  for(const [id] of pins){let node=nodes.get(id);while(node){included.add(node.id);node=node.parent?nodes.get(node.parent):undefined;}}
  // Evaluate only the ancestors necessary for pin frames. Keep all formulas so
  // dependent channels still resolve through their supported driving channels.
  const rig={...requested.rig,nodes:requested.rig.nodes.filter(n=>included.has(n.id))};
  const variables=rig.nodes.filter(n=>n.parent&&n.type==='bone'&&n.id!==editedBone).flatMap(node=>
    [0,1,2].filter(a=>editable(node,a)&&(!node.limits['xyz'[a]]?.clamped||node.limits['xyz'[a]].max-node.limits['xyz'[a]].min>1e-5)).map(axis=>({node,axis})));
  if(!variables.length)return requested;
  const residual=(pose:Pose)=>{
    const frames=forwardKinematics(rig,previewRotations(pose),pose.translation),values:number[]=[];
    for(const [id,pin] of pins){const frame=frames.get(id);if(!frame)continue;
      if(pin.position)values.push(...frame.position.clone().sub(new Vector3().fromArray(pin.position)).toArray());
      if(pin.rotation){const delta=frame.rotation.clone().multiply(new Quaternion().fromArray(pin.rotation).invert()).normalize();
        if(delta.w<0)delta.set(-delta.x,-delta.y,-delta.z,-delta.w);
        const length=Math.hypot(delta.x,delta.y,delta.z),scale=length>1e-8?20*Math.atan2(length,delta.w)/length:20;
        values.push(delta.x*scale,delta.y*scale,delta.z*scale);
      }
    }return values;
  };
  const angles=(p:Pose,v:{node:RigNode;axis:number})=>p.rotations[v.node.id]?.[v.axis]??0;
  const base=variables.map(v=>angles(requested,v)),prior=.0004;
  const cost=(p:Pose,r:number[])=>r.reduce((s,v)=>s+v*v,0)+variables.reduce((s,v,i)=>s+prior*(angles(p,v)-base[i])**2,0);
  let best=requested,r=residual(best),error=cost(best,r);
  if(error<1e-8)return requested;
  for(let iteration=0;iteration<iterations;iteration++){
    const columns=variables.map(({node,axis})=>{
      const values=[...(best.rotations[node.id]??[0,0,0])],original=values[axis];values[axis]+=.1;
      let trial=rotateJoint(best,node.id,values),step=(trial.rotations[node.id]?.[axis]??original)-original;
      if(Math.abs(step)<1e-8){values[axis]=original-.1;trial=rotateJoint(best,node.id,values);step=(trial.rotations[node.id]?.[axis]??original)-original;}
      return Math.abs(step)<1e-8?r.map(()=>0):residual(trial).map((v,i)=>(v-r[i])/step);
    });
    const matrix=columns.map((a,i)=>columns.map((b,j)=>a.reduce((s,v,k)=>s+v*b[k],0)+(i===j?.03+prior:0)));
    const gradient=columns.map((a,i)=>-a.reduce((s,v,k)=>s+v*r[k],0)-prior*(angles(best,variables[i])-base[i]));
    const deltas=linearSolve(matrix,gradient).map(v=>Math.max(-8,Math.min(8,v)));
    let improved=false;
    for(const factor of [1,.5,.25]){
      let trial=best;variables.forEach(({node,axis},i)=>{const values=[...(trial.rotations[node.id]??[0,0,0])];values[axis]+=deltas[i]*factor;trial=rotateJoint(trial,node.id,values);});
      const next=residual(trial),score=cost(trial,next);
      if(score<error-1e-7){best=trial;r=next;error=score;improved=true;break;}
    }
    if(!improved||error<1e-7)break;
  }
  return best;
}
