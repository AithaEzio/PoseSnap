import { Euler, Quaternion, Vector3 } from 'three';
import { forwardKinematics, previewRotations, quat } from './pose';
import type { Interaction, Pose, Rig, RigNode } from './types';

// Used by the development UI fixture. The desktop creates the same contract
// in its private worker from validated cached metadata.
export function blankPose(rig:Rig,id:string):Pose{return {version:1,rigId:rig.id,label:'Untitled pose',imageId:'pose-'+id.replaceAll('-',''),personId:1,sourceId:rig.sourceId,rig,origin:'editor',edited:true,rotations:Object.fromEntries(rig.nodes.filter(poseBone).map(n=>[n.id,[0,0,0]])),translation:[0,0,0],rootRotation:[0,0,0],warnings:[],handRefinement:false};}

function poseBone(node:RigNode){const name=node.id.toLowerCase(),facial=/eye|face|jaw|tongue|teeth|brow|lip|labial|mouth|cheek|nose|ear|chin|squint|nostril|infraorbital/.test(name)&&!name.includes('forearm');return node.type==='bone'&&!facial&&!name.includes('pectoral');}

export const figureKey = '$figure';
export type EditTool = 'select'|'translate'|'rotate';
export type JointGroup = 'body'|'arms'|'legs'|'hands';
export type EditAxis = 'all'|'x'|'y'|'z';
export function isReachJoint(id:string){return /^(l|r)_?(hand|foot)$/i.test(id);}
export function copyPoses(poses:Pose[]):Pose[]{return poses.map(p=>({...p,pins:p.pins?Object.fromEntries(Object.entries(p.pins).map(([id,pin])=>[id,{position:pin.position?[...pin.position]:undefined,rotation:pin.rotation?[...pin.rotation]:undefined}])):undefined,rotations:Object.fromEntries(Object.entries(p.rotations).map(([k,v])=>[k,[...v]])),translation:[...p.translation],rootRotation:[...(p.rootRotation??[0,0,0])]}));}
export interface EditSnapshot {poses:Pose[];baseline:Pose[];selected:number|null;bone:string;refinement?:Interaction|null;interaction?:Interaction|null}
export function snapshot(poses:Pose[],baseline:Pose[],selected:number|null,bone=figureKey):EditSnapshot{return {poses:copyPoses(poses),baseline:copyPoses(baseline),selected,bone};}
export function matchingJoint(source:Pose,target:Pose,id:string){
  if(id===figureKey)return id;
  const aliases:Record<string,string>={abdomenLower:'spine1',abdomenUpper:'spine2',chestLower:'spine3',chestUpper:'spine4',neckLower:'neck1',neckUpper:'neck2'};
  const semantic=(name:string)=>aliases[name]??name.replace(/Shldr(Bend|Twist)/,'_upperarm').replace(/Forearm(Bend|Twist)/,'_forearm').replace(/Thigh(Bend|Twist)/,'_thigh').replace(/Collar/,'_shoulder').replace(/^([lr])([A-Z])/,'$1_$2').toLowerCase().replace(/_toe$/,'_toes');
  return target.rig.nodes.find(n=>n.id===id)?.id??joints(target).find(n=>semantic(n.id)===semantic(id))?.id??figureKey;
}
// Development fixture only: desktop scene creation validates source provenance.
export function addedFixture(poses:Pose[],rig:Rig){const scene=poses.every(p=>p.studio)?poses[0].imageId:'pose-'+crypto.randomUUID().replaceAll('-','');const members=copyPoses(poses).map(p=>({...p,origin:'editor' as const,studio:true,imageId:scene,layout:undefined,studioSource:p.studioSource??(p.origin!=='editor'?{imageId:p.imageId,personId:p.personId,personKey:'development'}:undefined)}));const next=blankPose(rig,crypto.randomUUID());next.imageId=scene;next.studio=true;next.personId=Math.max(...members.map(p=>p.personId))+1;next.label='Mannequin '+next.personId;next.translation=[Math.max(...members.map(p=>p.translation[0]))+100,0,members[0].translation[2]];return {poses:[...members,next],selected:next.personId};}
export function editable(node:RigNode,axis:number){return !node.limits['xyz'[axis]]?.locked && !node.driven?.includes('xyz'[axis]);}
export function limited(node:RigNode,axis:number,value:number,current:number){
  if(!Number.isFinite(value)||!editable(node,axis))return current;
  const limit=node.limits['xyz'[axis]];
  return limit?.clamped?Math.max(limit.min,Math.min(limit.max,value)):value;
}
export function rotateJoint(pose:Pose,bone:string,values:number[]):Pose{
  const root=pose.rig.nodes.find(n=>!n.parent)!;
  const node=bone===figureKey?root:pose.rig.nodes.find(n=>n.id===bone);
  if(!node||bone!==figureKey&&!poseBone(node))return pose;
  const current=bone===figureKey?pose.rootRotation??[0,0,0]:pose.rotations[bone]??[0,0,0];
  const angles=values.map((v,i)=>limited(node,i,v,current[i]));
  return bone===figureKey?{...pose,rootRotation:angles,edited:true}:{...pose,rotations:{...pose.rotations,[bone]:angles},edited:true};
}
/** Zero local driving rotations, optionally traversing the actual rig subtree. */
export function zeroSelection(pose:Pose,bone:string,withChildren=false):Pose{
  const selected=pose.rig.nodes.find(n=>bone===figureKey?!n.parent:n.id===bone);
  if(!selected)return pose;
  const ids=new Set([selected.id]);
  if(withChildren){
    const children=new Map<string,RigNode[]>();
    for(const node of pose.rig.nodes)if(node.parent)children.set(node.parent,[...(children.get(node.parent)??[]),node]);
    const pending=[selected.id];
    for(let i=0;i<pending.length;i++)for(const child of children.get(pending[i])??[]){
      if(!ids.has(child.id)){ids.add(child.id);pending.push(child.id);}
    }
  }
  let next=pose;
  for(const node of pose.rig.nodes){
    if(!ids.has(node.id)||node.parent&&!poseBone(node))continue;
    const key=node.parent?node.id:figureKey;
    const current=key===figureKey?pose.rootRotation??[0,0,0]:pose.rotations[key]??[0,0,0];
    const values=[0,1,2].map(axis=>limited(node,axis,0,current[axis]));
    if(values.some((v,axis)=>v!==current[axis]))next=rotateJoint(next,key,values);
  }
  return next;
}
export function limbParents(pose:Pose,bone:string):RigNode[]{
  const nodes=new Map(pose.rig.nodes.map(n=>[n.id,n])),chain:RigNode[]=[];
  let parent=nodes.get(bone)?.parent;
  const pattern=/hand/i.test(bone)?/forearm|shldr|upperarm|collar|shoulder/i:/thigh|shin/i;
  while(parent){const node=nodes.get(parent);if(!node||node.type!=='bone'||!pattern.test(node.id))break;chain.push(node);parent=node.parent;}
  return chain;
}
/** A moved hand/foot changes its parent limb, rather than the endpoint channel. */
export function resetSelection(pose:Pose,baseline:Pose,bone:string):Pose{
  if(pose.personId!==baseline.personId||pose.rigId!==baseline.rigId)return pose;
  if(bone===figureKey)return {...pose,translation:[...baseline.translation],rootRotation:[...(baseline.rootRotation??[0,0,0])],edited:true};
  if(!pose.rig.nodes.some(n=>n.id===bone))return pose;
  const rotations={...pose.rotations},ids=[bone,...(isReachJoint(bone)?limbParents(pose,bone).map(n=>n.id):[])];
  for(const id of ids){if(baseline.rotations[id])rotations[id]=[...baseline.rotations[id]];else delete rotations[id];}
  return {...pose,rotations,edited:true};
}
export function moveFigure(poses:Pose[],person:number,position:number[],linked=false):Pose[]{
  const selected=poses.find(p=>p.personId===person);if(!selected||position.length!==3||position.some(v=>!Number.isFinite(v)))return poses;
  const delta=position.map((v,i)=>v-selected.translation[i]);
  return poses.map(p=>p.personId===person||linked?{...p,translation:p.translation.map((v,i)=>v+delta[i]),edited:true}:p);
}
// Transform gizmos manipulate a channel-oriented frame. FK itself includes the
// DAZ orientation sandwich; undo that sandwich before reading local channels.
export function gizmoFrame(pose:Pose,bone:string){
  const id=bone===figureKey?pose.rig.nodes.find(n=>!n.parent)!.id:bone;
  const node=pose.rig.nodes.find(n=>n.id===id)!;
  const world=forwardKinematics(pose.rig,previewRotations(pose),pose.translation);
  const state=world.get(id)!;
  return {position:state.position.clone().multiplyScalar(.01),rotation:state.rotation.clone().multiply(quat(node.orientation))};
}
export function gizmoRotation(pose:Pose,bone:string,worldFrame:Quaternion):Pose{
  const id=bone===figureKey?pose.rig.nodes.find(n=>!n.parent)!.id:bone;
  const node=pose.rig.nodes.find(n=>n.id===id)!;
  const world=forwardKinematics(pose.rig,previewRotations(pose),pose.translation);
  const parent=node.parent?world.get(node.parent)?.rotation:new Quaternion();
  const local=quat(node.orientation).invert().multiply((parent?.clone()??new Quaternion()).invert()).multiply(worldFrame);
  const euler=new Euler().setFromQuaternion(local,node.order.split('').reverse().join('') as Euler['order']);
  const current=bone===figureKey?pose.rootRotation??[0,0,0]:pose.rotations[id]??[0,0,0];
  const values=[euler.x,euler.y,euler.z].map((v,i)=>{const degrees=v*180/Math.PI;return degrees+360*Math.round((current[i]-degrees)/360);});
  return rotateJoint(pose,bone,values);
}
export function boundedGizmoRotation(pose:Pose,bone:string,requested:Quaternion){
  const next=gizmoRotation(pose,bone,requested),frame=gizmoFrame(next,bone);
  return {pose:next,frame,limited:frame.rotation.angleTo(requested)>1e-5};
}
export function onFloor(pose:Pose):Pose{
  const world=forwardKinematics(pose.rig,previewRotations(pose),pose.translation);let low=Infinity;
  for(const n of pose.rig.nodes){if(n.type!=='bone')continue;const s=world.get(n.id)!;const end=new Vector3().fromArray(n.end).sub(new Vector3().fromArray(n.center)).applyQuaternion(s.rotation).add(s.position);low=Math.min(low,s.position.y,end.y);}
  return {...pose,translation:[pose.translation[0],pose.translation[1]-(Number.isFinite(low)?low:0),pose.translation[2]],edited:true};
}
export function jointLabel(node:RigNode){
  if(!node.parent)return 'Whole figure';
  const torso:Record<string,string>={spine1:'Lower abdomen',spine2:'Upper abdomen',spine3:'Lower chest',spine4:'Upper chest',neck1:'Lower neck',neck2:'Upper neck'};if(torso[node.id])return torso[node.id];
  const id=node.id.replace(/_shoulder$/,'_Collar').replace(/^l(?=[A-Z_])/,'Left ').replace(/^r(?=[A-Z_])/,'Right ').replace(/_/g,' ').replace(/([a-z])([A-Z])/g,'$1 $2').replace(/Bend/g,'').replace(/Shldr|upperarm/gi,'Shoulder').replace(/Forearm/gi,'Elbow').replace(/Thigh/gi,'Hip').replace(/Shin/gi,'Knee').replace(/metacarpal/gi,' metacarpal').replace(/mid(\d)/gi,'Middle $1').replace(/([a-z])([0-9])/gi,'$1 $2');
  return id.trim().replace(/\s+/g,' ').replace(/^./,v=>v.toUpperCase());
}
export function joints(pose:Pose){return pose.rig.nodes.filter(n=>poseBone(n)&&!n.id.toLowerCase().includes('anchor')&&[0,1,2].some(i=>editable(n,i)));}
export function quickJoints(pose:Pose,group:JointGroup){
  return joints(pose).filter(n=>{
    const name=n.id.toLowerCase();
    if(/twist|metacarpal|metatarsal|pectoral/.test(name))return false;
    if(group==='hands')return /^(l|r)_?(hand|thumb[123]|index[123]|mid[123]|middle[123]|ring[123]|pinky[123])$/.test(name);
    if(group==='arms')return /collar|shoulder|shldr|upperarm|forearm|^(l|r)_?hand$/.test(name);
    if(group==='legs')return /thigh|shin|^(l|r)_?(foot|toe|toes)$/.test(name);
    return /^(hip|pelvis|spine\d*|abdomen\w*|chest\w*|neck\w*|head)$/.test(name);
  });
}
export function handleJoints(pose:Pose,group:JointGroup,selected:string){
  let nodes=group==='hands'?quickJoints(pose,'hands').filter(n=>n.id[0]===(['l','r'].includes(selected[0])?selected[0]:'l')):quickJoints(pose,group);
  const chosen=pose.rig.nodes.find(n=>n.id===selected);if(chosen&&!nodes.includes(chosen))nodes.push(chosen);
  // Dense torso pivots are still available in the inspector, without stacked pins.
  if(group!=='hands')nodes=nodes.filter(n=>n===chosen||!/neck|pelvis|abdomenLower|chestLower|collar|shoulder|spine[13]$|(?:l|r)_?(toe|toes)$/i.test(n.id));
  return nodes;
}
