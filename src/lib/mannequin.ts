import * as THREE from 'three';
import { forwardKinematics, previewRotations } from './pose';
import type { Pose, Rig, RigNode, Theme } from './types';

type View={offset:number;count:number;type:'Float32Array'|'Uint16Array'|'Uint32Array'};
type SourceBone={name:string;head:number[];tail:number[]};
export type MannequinManifest={version:2;credit:string;source:string;license:string;bones:SourceBone[];parts:{name:string;kind:string}[];position:View;part:View;index:View;groups:{start:number;count:number;materialIndex:number}[]};
let template:{manifest:MannequinManifest;buffer:ArrayBuffer}|undefined,loading:Promise<void>|undefined;
export function installMannequin(manifest:MannequinManifest,buffer:ArrayBuffer){
  if(manifest.version!==2||!manifest.bones.length||!manifest.parts.length||manifest.parts.some(p=>p.kind!=='surface'))throw new Error('Invalid articulated mannequin surface');
  template={manifest,buffer};
}
export function loadMannequin(){
  if(template)return Promise.resolve();
  return loading??=Promise.all([fetch('/mannequin/surface.json').then(r=>{if(!r.ok)throw new Error('Missing mannequin metadata');return r.json();}),fetch('/mannequin/surface.bin').then(r=>{if(!r.ok)throw new Error('Missing mannequin surface');return r.arrayBuffer();})]).then(([manifest,buffer])=>installMannequin(manifest,buffer));
}
function attribute(view:View,buffer:ArrayBuffer){const C={Float32Array,Uint16Array,Uint32Array}[view.type];return new C(buffer,view.offset,view.count);}
const vector=(p:number[])=>new THREE.Vector3().fromArray(p);
function find(rig:Rig,ids:string[]):RigNode|undefined{return ids.map(id=>rig.nodes.find(n=>n.id===id)).find(Boolean);}
function requireNode(rig:Rig,ids:string[]):RigNode{const n=find(rig,ids);if(!n)throw new Error('Cannot bind mannequin to '+ids.join('/')+'. Refresh the figure connection.');return n;}
function targetName(name:string,rig:Rig):RigNode{
  const central:Record<string,string[]>={Root:['pelvis','hip'],spine:['abdomenUpper','spine2'],'spine.001':['abdomenUpper','spine2'],'Upper Body':['chestUpper','spine4','chest'],'Upper neck':['neckUpper','neck2','neck'],Head:['head']};
  if(central[name])return requireNode(rig,central[name]);
  const [part,sideUpper]=name.split(/\.(?=[LR]$)/),side=sideUpper?.toLowerCase();
  const body:Record<string,string[]>={upper_arm:['ShldrBend','_upperarm'],forearm:['ForearmTwist','ForearmBend','_forearm'],hand:['Hand','_hand'],thigh:['ThighTwist','ThighBend','_thigh'],shin:['Shin','_shin'],foot:['Foot','_foot']};
  const finger=part.match(/^(thumb|f_index|f_middle|f_ring|f_pinky)\.(0[123])$/);
  if(side&&finger){const p=finger[1].replace('f_',''),label=p==='middle'?'Mid':p[0].toUpperCase()+p.slice(1),num=Number(finger[2]);return requireNode(rig,[side+label+num,side+'_'+label.toLowerCase()+num]);}
  if(side&&body[part])return requireNode(rig,body[part].map(p=>side+p));
  throw new Error('Unknown mannequin piece '+name);
}
function frame(direction:THREE.Vector3,reference=new THREE.Vector3(0,0,1)){
  const y=direction.clone().normalize(),front=reference.clone(),z=front.addScaledVector(y,-front.dot(y));
  if(z.length()<.01)z.set(0,1,0).addScaledVector(y,-y.y);z.normalize();const x=y.clone().cross(z).normalize();
  return new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().makeBasis(x,y,z));
}
export class Mannequin{
  group=new THREE.Group();
  // The supplied shells contain inward-facing patches. Render both sides,
  // as Blender does, without modifying the original geometry or its rig.
  private material=new THREE.MeshStandardMaterial({roughness:.72,metalness:.02,side:THREE.DoubleSide});
  private meshes:THREE.SkinnedMesh[]=[];
  private skeleton:THREE.Skeleton;
  private targets:RigNode[];
  private bounds=new THREE.Box3();
  constructor(readonly rig:Rig,readonly personId:number){
    if(!template)throw new Error('The local mannequin surface has not loaded.');
    const {manifest,buffer}=template,source=new Map(manifest.bones.map(b=>[b.name,b]));
    const mapped=manifest.parts.map(p=>targetName(p.name,rig));
    this.targets=[...new Map(mapped.map(n=>[n.id,n])).values()];
    // Visual matrices mirror the existing target FK. The source armature,
    // Rigify controls and scripts never enter the application rig.
    const bones=this.targets.map(n=>{const b=new THREE.Bone();b.name=n.id;b.matrixWorld.makeTranslation(...n.center.map(v=>v*.01) as [number,number,number]);return b;});
    this.skeleton=new THREE.Skeleton(bones);this.skeleton.calculateInverses();
    const get=(ids:string[])=>requireNode(rig,ids),head=get(['head']),scale=head.center[1]*.01/source.get('Head')!.head[1];
    const hands=Object.fromEntries(['l','r'].map(side=>{
      const suffix=side==='l'?'L':'R',wrist=source.get('hand.'+suffix)!,middle=source.get('f_middle.01.'+suffix)!;
      const sourceAlong=vector(middle.head).sub(vector(wrist.head)),sourceSpread=vector(source.get('f_index.01.'+suffix)!.head).sub(vector(source.get('f_pinky.01.'+suffix)!.head));
      const targetAlong=vector(get([side+'Mid1',side+'_mid1']).center).sub(vector(get([side+'Hand',side+'_hand']).center)),targetSpread=vector(get([side+'Index1',side+'_index1']).center).sub(vector(get([side+'Pinky1',side+'_pinky1']).center));
      return [side,{sourceSpread,targetSpread,sourceNormal:sourceAlong.clone().cross(sourceSpread).normalize(),targetNormal:targetAlong.clone().cross(targetSpread).normalize(),width:targetSpread.length()*.01/sourceSpread.length()}];
    }));
    const fits=manifest.parts.map((part,i)=>{
      const name=part.name,b=source.get(name)!,node=mapped[i];let start=vector(b.head),end=vector(b.tail),at=vector(node.center).multiplyScalar(.01),to=vector(node.end).multiplyScalar(.01),width=scale,sourceReference=new THREE.Vector3(0,0,1),targetReference=sourceReference.clone();
      if(/^(upper_arm|forearm|thigh|shin|hand|foot)/.test(name)){
        const side=name.endsWith('.L')?'l':'r',base=name.split('.')[0];
        const from:Record<string,string[]>={upper_arm:['ShldrBend','_upperarm'],forearm:['ForearmBend','_forearm'],thigh:['ThighBend','_thigh'],shin:['Shin','_shin'],hand:['Hand','_hand'],foot:['Foot','_foot']};
        const ends:Record<string,string[]>={upper_arm:['ForearmBend','_forearm'],forearm:['Hand','_hand'],thigh:['Shin','_shin'],shin:['Foot','_foot'],hand:['Mid1','_mid1'],foot:['Toe','_toes']};
        const parent=get(from[base].map(id=>side+id));at=vector(parent.center).multiplyScalar(.01);const child=find(rig,ends[base].map(id=>side+id));if(child)to=vector(child.center).multiplyScalar(.01);
        if(base==='hand'){const hand=hands[side];end=vector(source.get('f_middle.01.'+(side==='l'?'L':'R'))!.head);width=hand.width;sourceReference=hand.sourceSpread;targetReference=hand.targetSpread;}
        if(base==='foot'){
          end=vector(source.get('toe.'+(side==='l'?'L':'R'))!.tail);to=vector(child?.end??parent.end).multiplyScalar(.01);
          // Rest soles stay level. Foot/toe pivots can slope downwards even
          // while the shoe itself rests flat on the ground.
          end.y=start.y;to.y=at.y;width=Math.max(.1,at.y/start.y);sourceReference.set(0,1,0);targetReference.set(0,1,0);
        }
      }
      if(/^(thumb|f_index|f_middle|f_ring|f_pinky)\./.test(name)){const hand=hands[name.endsWith('.L')?'l':'r'];width=hand.width;sourceReference=hand.sourceNormal;targetReference=hand.targetNormal;}
      if(name==='Root'){
        start=vector(source.get('thigh.L')!.head).add(vector(source.get('thigh.R')!.head)).multiplyScalar(.5);
        at=vector(get(['lThighBend','l_thigh']).center).add(vector(get(['rThighBend','r_thigh']).center)).multiplyScalar(.005);end=start.clone().add(new THREE.Vector3(0,.2,0));to=at.clone().add(new THREE.Vector3(0,.2*scale,0));
      }
      if(name==='spine'){end=vector(source.get('Upper Body')!.head);at=vector(get(['abdomenLower','spine1']).center).multiplyScalar(.01);to=vector(get(['chestLower','spine3','spine2','chest']).center).multiplyScalar(.01);}
      if(name==='Upper Body'){
        at=vector(get(['chestLower','spine3','spine2','chest']).center).multiplyScalar(.01);end=vector(source.get('Upper neck')!.head);to=vector(get(['neckLower','neck1','neck']).center).multiplyScalar(.01);
        width=get(['lShldrBend','l_upperarm']).center[0]*.01/source.get('upper_arm.L')!.head[0];
      }
      if(name==='Upper neck'){at=vector(get(['neckLower','neck1','neck']).center).multiplyScalar(.01);end=vector(source.get('Head')!.head);to=vector(head.center).multiplyScalar(.01);width=scale*(rig.sourceId==='posesnap-mannequin'?1:.88);}
      if(name==='Head'){end=start.clone().add(new THREE.Vector3(0,.2,0));to=at.clone().add(new THREE.Vector3(0,.2*scale,0));}
      const sd=end.clone().sub(start),td=to.clone().sub(at);
      return {start,at,direction:sd.clone().normalize(),rotation:frame(td,targetReference).multiply(frame(sd,sourceReference).invert()),length:td.length()/sd.length(),width};
    });
    const positions=attribute(manifest.position,buffer),parts=attribute(manifest.part,buffer),fitted=new Float32Array(positions.length),skinIndices=new Uint16Array(parts.length*4),skinWeights=new Float32Array(parts.length*4),v=new THREE.Vector3();
    // Fit to the rest joints once. Every connected solid piece has ONE
    // influence: pose updates cannot shear, squash or stretch its vertices.
    for(let i=0;i<parts.length;i++){
      const fit=fits[parts[i]];v.fromArray(positions,i*3).sub(fit.start);const along=v.dot(fit.direction);
      v.multiplyScalar(fit.width).addScaledVector(fit.direction,along*(fit.length-fit.width)).applyQuaternion(fit.rotation).add(fit.at).toArray(fitted,i*3);
      skinIndices[i*4]=this.targets.indexOf(mapped[parts[i]]);skinWeights[i*4]=1;
    }
    const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.BufferAttribute(fitted,3));geometry.setIndex(new THREE.BufferAttribute(attribute(manifest.index,buffer),1));geometry.setAttribute('skinIndex',new THREE.BufferAttribute(skinIndices,4));geometry.setAttribute('skinWeight',new THREE.BufferAttribute(skinWeights,4));geometry.computeVertexNormals();
    const mesh=new THREE.SkinnedMesh(geometry,this.material);mesh.bind(this.skeleton,new THREE.Matrix4());mesh.userData={personId};mesh.frustumCulled=false;this.meshes.push(mesh);this.group.add(mesh);
    this.update(null,'dark',true,'');
  }
  update(pose:Pose|null,theme:Theme,selected:boolean,bone:string,ghost=false){
    const world=forwardKinematics(this.rig,pose?previewRotations(pose):{},pose?.translation??[0,0,0]);
    this.material.color.set(selected?(theme==='light'?0xaaa7b5:0xbfc1cc):(theme==='light'?0x9c8cb5:0xa090ba));this.bounds.makeEmpty();
    if(this.material.transparent!==ghost)this.material.needsUpdate=true;this.material.transparent=ghost;this.material.opacity=ghost?.18:1;this.material.depthWrite=!ghost;
    for(let i=0;i<this.targets.length;i++){
      const n=this.targets[i],state=world.get(n.id)!;
      this.skeleton.bones[i].matrixWorld.compose(state.position.clone().multiplyScalar(.01),state.rotation,new THREE.Vector3(1,1,1));this.bounds.expandByPoint(state.position.clone().multiplyScalar(.01));
      this.bounds.expandByPoint(vector(n.end).sub(vector(n.center)).applyQuaternion(state.rotation).add(state.position).multiplyScalar(.01));
    }
    this.skeleton.update();this.bounds.expandByScalar(.14);for(const mesh of this.meshes){mesh.boundingBox=this.bounds.clone();mesh.boundingSphere=this.bounds.getBoundingSphere(new THREE.Sphere());}this.group.userData.selectedBone=bone;
  }
  pickBone(face:THREE.Intersection){
    const mesh=face.object as THREE.SkinnedMesh;if(!face.face)return null;
    const index=mesh.geometry.getAttribute('skinIndex').getX(face.face.a),node=this.targets[index];
    // Surface clicks select bend. The separate twist control stays available
    // in the joint list and still drives the rigid visual segment.
    return node.id.includes('Twist')&&node.parent?node.parent:node.id;
  }
  dispose(){for(const m of this.meshes)m.geometry.dispose();this.skeleton.dispose();this.material.dispose();}
}
