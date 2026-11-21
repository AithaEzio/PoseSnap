import { Euler, Matrix4, Quaternion, Vector3 } from 'three';
import type { Pose, Rig } from './types';
import mannequinRest from './mannequin-rest.json';
const degrees=Math.PI/180;
export function quat(values:number[],order='XYZ') {return new Quaternion().setFromEuler(new Euler(values[0]*degrees,values[1]*degrees,values[2]*degrees,order.split('').reverse().join('') as Euler['order']));}
export function evaluatedChannels(rig:Rig,values:Record<string,number[]>){
  const key=(url:string)=>{const match=url.match(/#([^?]+)\?rotation\/([xyz])(?:\/value)?$/);if(!match)throw new Error('Unsupported rig formula');return `${match[1]}/${match[2]}`;};
  const grouped=new Map<string,NonNullable<Rig['formulas']>>(),cache=new Map<string,number>(),active=new Set<string>();
  for(const formula of rig.formulas??[]){const channel=key(formula.output);grouped.set(channel,[...(grouped.get(channel)??[]),formula]);}
  const resolve=(channel:string):number=>{
    if(cache.has(channel))return cache.get(channel)!;
    if(active.has(channel))throw new Error('Cyclic rig formula');active.add(channel);
    const slash=channel.lastIndexOf('/'),bone=channel.slice(0,slash),axis='xyz'.indexOf(channel.slice(slash+1));let base=values[bone]?.[axis]??0,product=1;
    for(const formula of grouped.get(channel)??[]){const stack:number[]=[];
      for(const operation of formula.operations){if(operation.op==='push')stack.push(operation.url?resolve(key(operation.url)):operation.val!);else if(stack.length>=2){const b=stack.pop()!,a=stack.pop()!;stack.push(operation.op==='add'?a+b:a*b);}else throw new Error('Unsupported rig formula');}
      if(stack.length!==1)throw new Error('Invalid rig formula');if(formula.stage==='mult')product*=stack[0];else base+=stack[0];
    }
    active.delete(channel);cache.set(channel,base*product);return base*product;
  };
  return Object.fromEntries(rig.nodes.map(node=>[node.id,['x','y','z'].map(axis=>resolve(`${node.id}/${axis}`))]));
}
export function forwardKinematics(rig:Rig,rotations:Record<string,number[]>,translation:number[]=[0,0,0]) {
  rotations=evaluatedChannels(rig,rotations);
  const nodes=new Map(rig.nodes.map(n=>[n.id,n]));
  const world=new Map<string,{position:Vector3;rotation:Quaternion;matrix:Matrix4}>();
  const pending=[...rig.nodes];
  while(pending.length){let changed=false;
    for(const node of [...pending]){
      if(node.parent&&nodes.has(node.parent)&&!world.has(node.parent))continue;
      const parent=node.parent?world.get(node.parent):undefined;
      const center=new Vector3().fromArray(node.center);
      const parentCenter=new Vector3().fromArray(nodes.get(node.parent??'')?.center??[0,0,0]);
      const position=center.sub(parentCenter).applyQuaternion(parent?.rotation??new Quaternion()).add(parent?.position??new Vector3());
      if(!node.parent)position.add(new Vector3().fromArray(translation));
      const orientation=quat(node.orientation);
      const rotation=(parent?.rotation.clone()??new Quaternion()).multiply(orientation).multiply(quat(rotations[node.id]??[0,0,0],node.order)).multiply(orientation.clone().invert());
      world.set(node.id,{position,rotation,matrix:new Matrix4().compose(position,rotation,new Vector3(1,1,1))});
      pending.splice(pending.indexOf(node),1);changed=true;
    }
    if(!changed)throw new Error('Invalid rig hierarchy');
  }
  return world;
}
export function orientedPose(pose:Pose,rootRotation:number[],floorOffset:number):Pose {
  if(rootRotation.every(v=>v===0))return {...pose,translation:[pose.translation[0],pose.translation[1]+floorOffset,pose.translation[2]],quality:floorOffset&&pose.quality?{...pose.quality,stale:true}:pose.quality};
  const root=pose.rig.nodes.find(n=>!n.parent)!;
  if(pose.rootRotation?.some(v=>v!==0)){const composed=new Euler().setFromQuaternion(quat(rootRotation).multiply(quat(pose.rootRotation)),'ZYX');rootRotation=[composed.x/degrees,composed.y/degrees,composed.z/degrees];}
  const rotations={...pose.rotations,[root.id]:rootRotation};
  const world=forwardKinematics(pose.rig,rotations);
  let minimum=Infinity;
  for(const node of pose.rig.nodes){
    if(node.type!=='bone')continue;
    const state=world.get(node.id)!;
    const end=new Vector3().fromArray(node.end).sub(new Vector3().fromArray(node.center)).applyQuaternion(state.rotation).add(state.position);
    minimum=Math.min(minimum,state.position.y,end.y);
  }
  const airborne=pose.footSupport?.every(s=>s.state==='air');
  return {...pose,rootRotation,referenceCamera:undefined,quality:pose.quality?{...pose.quality,stale:true}:undefined,translation:[0,(airborne?pose.translation[1]:-(Number.isFinite(minimum)?minimum:0))+floorOffset,0]};
}
export function previewRotations(pose:Pose){return {...pose.rotations,[pose.rig.nodes.find(n=>!n.parent)!.id]:pose.rootRotation??[0,0,0]};}
export function orientInteraction(poses:Pose[],rootRotation:number[],floorOffset:number):Pose[]{
  if(rootRotation.every(v=>v===0))return poses.map(pose=>({...pose,translation:[pose.translation[0],pose.translation[1]+floorOffset,pose.translation[2]],quality:floorOffset&&pose.quality?{...pose.quality,stale:true}:pose.quality}));
  const q=quat(rootRotation);let minimum=Infinity;
  const rotated=poses.map(pose=>{const e=new Euler().setFromQuaternion(q.clone().multiply(quat(pose.rootRotation??[0,0,0])),'ZYX');return {...pose,rootRotation:[e.x/degrees,e.y/degrees,e.z/degrees],referenceCamera:undefined,quality:pose.quality?{...pose.quality,stale:true}:undefined,translation:new Vector3().fromArray(pose.translation).applyQuaternion(q).toArray()};});
  for(const pose of rotated){const world=forwardKinematics(pose.rig,previewRotations(pose),pose.translation);
    for(const node of pose.rig.nodes){if(node.type!=='bone')continue;const state=world.get(node.id)!;const end=new Vector3().fromArray(node.end).sub(new Vector3().fromArray(node.center)).applyQuaternion(state.rotation).add(state.position);minimum=Math.min(minimum,state.position.y,end.y);}}
  const lift=(poses.every(p=>p.footSupport?.every(s=>s.state==='air'))?0:-(Number.isFinite(minimum)?minimum:0))+floorOffset;
  return rotated.map(pose=>({...pose,translation:[pose.translation[0],pose.translation[1]+lift,pose.translation[2]]}));
}
export function neutralRig():Rig {
  return {id:'g9',label:'PoseSnap mannequin',sourceId:'posesnap-mannequin',nodes:[{id:'figure',name:'figure',parent:null,center:[0,0,0],end:[0,0,0],type:'figure',orientation:[0,0,0],order:'XYZ',limits:{}},...structuredClone(mannequinRest)]};
}
