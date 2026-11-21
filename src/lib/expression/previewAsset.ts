import * as THREE from 'three';
import {createOralClearance,type OralAttachment} from './oralClearance.mjs';
import {smoothExtendedTongueTip} from './tongueTipNormals.mjs';

type FloatView = {offset:number;count:number;type:'Float32Array'};
type IndexView = {offset:number;count:number;type:'Uint16Array'|'Uint32Array'};
type SparseMorph = {indices:IndexView;deltas:FloatView};
type Corrective = SparseMorph & {drivers:string[];max:number};
export interface FacePreviewManifest {
  version:1;
  coordinateConvention:string;
  binary:'face.bin';
  binaryBytes:number;
  sha256:string;
  bounds:{min:number[];max:number[]};
  framing?:{center:number[];height:number;width:number};
  actionLimits:Record<string,number>;
  oralAttachments?:OralAttachment[];
  meshes:{name:string;positions:FloatView;normals:FloatView;index:IndexView;
    groups:{start:number;count:number;materialIndex:number}[];
    materials:{name:string;color:number[];roughness:number;side?:'front'|'double'}[];
    morphs:Record<string,SparseMorph>;correctives?:Record<string,Corrective>}[];
  eyes:{mesh:string;center:number[];side:'Left'|'Right';yawLimitDegrees:number;pitchLimitDegrees:number}[];
}
type PreparedMesh={name:string;positions:Float32Array;normals:Float32Array;index:Uint16Array|Uint32Array;
  definition:FacePreviewManifest['meshes'][number];morphs:Map<string,{indices:Uint16Array|Uint32Array;deltas:Float32Array}>;correctives:Map<string,{indices:Uint16Array|Uint32Array;deltas:Float32Array;drivers:string[];max:number}>};
export type FacePreviewAsset={manifest:FacePreviewManifest;meshes:PreparedMesh[]};
const fail=(detail:string):never=>{throw new Error('The expression face asset is damaged: '+detail+'. Restore public/expression-face from a complete PoseSnap folder.');};
function vector(value:number[],label:string){if(!Array.isArray(value)||value.length!==3||value.some(v=>!Number.isFinite(v)))fail(label);}
function view(buffer:ArrayBuffer,range:FloatView|IndexView,label:string):Float32Array|Uint16Array|Uint32Array {
  const ctor=range?.type==='Float32Array'?Float32Array:range?.type==='Uint16Array'?Uint16Array:range?.type==='Uint32Array'?Uint32Array:null;
  if(!ctor)return fail(label);
  if(!Number.isSafeInteger(range.offset)||!Number.isSafeInteger(range.count)||range.offset<0||range.count<0||range.offset%ctor.BYTES_PER_ELEMENT||range.offset+range.count*ctor.BYTES_PER_ELEMENT>buffer.byteLength)fail(label);
  return new ctor(buffer,range.offset,range.count);
}
function floats(buffer:ArrayBuffer,range:FloatView,label:string){
  if(range?.type!=='Float32Array')fail(label);
  const values=view(buffer,range,label) as Float32Array;
  for(const value of values)if(!Number.isFinite(value))fail(label+' contains non-finite values');
  return values;
}
function indices(buffer:ArrayBuffer,range:IndexView,label:string){
  if(range?.type!=='Uint32Array'&&range?.type!=='Uint16Array')fail(label);
  return view(buffer,range,label) as Uint16Array|Uint32Array;
}
/** Validate binary boundaries before allocating scene objects or accepting deltas. */
export function parseFacePreview(manifest:FacePreviewManifest,buffer:ArrayBuffer):FacePreviewAsset {
  if(manifest?.version!==1||manifest.binary!=='face.bin'||!/^([a-f0-9]{64})$/.test(manifest.sha256)||manifest.coordinateConvention!=='right-handed, Y-up, +Z front, metres'||manifest.binaryBytes!==buffer.byteLength||buffer.byteLength>16*1024**2)fail('unsupported format');
  vector(manifest.bounds?.min,'bounds');vector(manifest.bounds?.max,'bounds');
  if(manifest.bounds.max.some((v,i)=>v<=manifest.bounds.min[i]))fail('empty bounds');
  if(manifest.framing){vector(manifest.framing.center,'camera framing');if(![manifest.framing.height,manifest.framing.width].every(v=>Number.isFinite(v)&&v>0&&v<2))fail('camera dimensions');}
  if(!Array.isArray(manifest.meshes)||!manifest.meshes.length||manifest.meshes.length>16||!Array.isArray(manifest.eyes)||!manifest.actionLimits)fail('mesh metadata');
  for(const [name,limit] of Object.entries(manifest.actionLimits))if(!/^[a-z][A-Za-z]+$/.test(name)||!Number.isFinite(limit)||limit<=0||limit>1.5)fail('action limits');
  const names=new Set<string>();
  const meshes=manifest.meshes.map(definition=>{
    if(typeof definition.name!=='string'||names.has(definition.name))fail('duplicate mesh');names.add(definition.name);
    const positions=floats(buffer,definition.positions,'positions'),normals=floats(buffer,definition.normals,'normals'),index=indices(buffer,definition.index,'triangles');
    const count=positions.length/3;
    if(!Number.isInteger(count)||!count||count>100_000||normals.length!==positions.length||!index.length||index.length%3)fail('mesh dimensions');
    for(const value of index)if(value>=count)fail('triangle index');
    if(!definition.materials?.length||!Array.isArray(definition.groups)||!definition.morphs)fail('materials or morphs');
    for(const material of definition.materials){vector(material.color,'material color');if(material.color.some(v=>v<0||v>1)||!Number.isFinite(material.roughness)||material.roughness<0||material.roughness>1||material.side!==undefined&&!['front','double'].includes(material.side))fail('material');}
    let end=0;
    for(const group of definition.groups){if(group.start!==end||!Number.isInteger(group.count)||group.count<=0||group.count%3||!Number.isInteger(group.materialIndex)||group.materialIndex<0||group.materialIndex>=definition.materials.length)fail('material group');end+=group.count;}
    if(end!==index.length)fail('material coverage');
    const morphs=new Map<string,{indices:Uint16Array|Uint32Array;deltas:Float32Array}>();
    for(const [name,range] of Object.entries(definition.morphs)){
      if(!(name in manifest.actionLimits))fail('unknown morph');
      const affected=indices(buffer,range.indices,'morph indices'),deltas=floats(buffer,range.deltas,'morph deltas');
      if(deltas.length!==affected.length*3)fail('morph dimensions');
      const seen=new Set<number>();for(const value of affected){if(value>=count||seen.has(value))fail('morph vertex');seen.add(value);}
      morphs.set(name,{indices:affected,deltas});
    }
    const correctives=new Map<string,{indices:Uint16Array|Uint32Array;deltas:Float32Array;drivers:string[];max:number}>();
    for(const [name,range] of Object.entries(definition.correctives??{})){
      if(!Array.isArray(range.drivers)||range.drivers.length!==2||range.drivers.some(v=>!(v in manifest.actionLimits))||new Set(range.drivers).size!==2||!Number.isFinite(range.max)||range.max<=0||range.max>1)fail('corrective drivers');
      const affected=indices(buffer,range.indices,'corrective indices'),deltas=floats(buffer,range.deltas,'corrective deltas');
      if(deltas.length!==affected.length*3)fail('corrective dimensions');
      const seen=new Set<number>();for(const value of affected){if(value>=count||seen.has(value))fail('corrective vertex');seen.add(value);}
      correctives.set(name,{indices:affected,deltas,drivers:range.drivers,max:range.max});
    }
    return {name:definition.name,positions,normals,index,definition,morphs,correctives};
  });
  const sides=new Set<string>();
  for(const attachment of manifest.oralAttachments??[]){
    const lining=meshes.find(m=>m.name===attachment.mesh),skin=meshes.find(m=>m.name===attachment.surface);
    if(!lining||!skin||!Array.isArray(attachment.vertices)||!Array.isArray(attachment.indices)||attachment.vertices.length!==attachment.indices.length||!attachment.vertices.length)fail('oral attachments');
    const liningCount=lining?.positions.length??fail('oral lining'),skinCount=skin?.positions.length??fail('oral surface');
    if(attachment.vertices.some(v=>!Number.isInteger(v)||v<0||v>=liningCount/3)||attachment.indices.some(v=>!Number.isInteger(v)||v<0||v>=skinCount/3))fail('oral attachment vertex');
  }
  for(const eye of manifest.eyes){
    vector(eye.center,'eye pivot');
    if(!names.has(eye.mesh)||!['Left','Right'].includes(eye.side)||sides.has(eye.side)||![eye.yawLimitDegrees,eye.pitchLimitDegrees].every(v=>Number.isFinite(v)&&v>0&&v<=45))fail('eye rig');
    sides.add(eye.side);
  }
  return {manifest,meshes};
}
let cached:Promise<FacePreviewAsset>|undefined;
/** One local asset shared by preview mounts. A failed request can be retried. */
export function loadFacePreview():Promise<FacePreviewAsset>{
  return cached??=Promise.all([
    fetch('/expression-face/manifest.json').then(r=>{if(!r.ok)throw Error('Expression face metadata is missing. Restore the expression-face folder.');return r.json();}),
    fetch('/expression-face/face.bin').then(r=>{if(!r.ok)throw Error('Expression face mesh is missing. Restore the expression-face folder.');return r.arrayBuffer();})
  ]).then(async([manifest,buffer])=>{
    const asset=parseFacePreview(manifest,buffer);
    const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',buffer))).map(value=>value.toString(16).padStart(2,'0')).join('');
    if(digest!==manifest.sha256)fail('checksum mismatch');
    return asset;
  }).catch(error=>{cached=undefined;throw error;});
}
export function boundedFaceActions(values:Record<string,number>,limits:Record<string,number>){
  const actions:Record<string,number>={};
  for(const [name,limit] of Object.entries(limits)){const value=values[name];actions[name]=Number.isFinite(value)?Math.max(0,Math.min(limit,value)):0;}
  return actions;
}
/** Preview-only anatomical coupling; never rewrite extracted or DAZ values. */
export function coupledFaceActions(values:Record<string,number>,limits:Record<string,number>){
  const actions=boundedFaceActions(values,limits);
  actions.jawOpen=(actions.jawOpen??0)*(1-.8*(actions.mouthClose??0));
  for(const side of ['Left','Right']){
    actions['eyeBlink'+side]=Math.max(actions['eyeBlink'+side]??0,.45*(actions['eyeSquint'+side]??0))*(1-.25*(actions['eyeWide'+side]??0));
    // Squint contributes to the shared lid closure; adding its morph too would close twice.
    actions['eyeSquint'+side]=0;
    const smile='mouthSmile'+side,frown='mouthFrown'+side,opposing=Math.min(actions[smile]??0,actions[frown]??0);
    actions[smile]=(actions[smile]??0)-opposing;actions[frown]=(actions[frown]??0)-opposing;
    const names=['mouthUpperUp','mouthPress','mouthSmile','mouthFrown','mouthStretch'].map(name=>name+side),total=names.reduce((sum,name)=>sum+(actions[name]??0),0);
    if(total>1.65)for(const name of names)actions[name]*=1.65/total;
  }
  for(const region of ['jaw','mouth']){const net=(actions[region+'Left']??0)-(actions[region+'Right']??0);actions[region+'Left']=Math.max(0,net);actions[region+'Right']=Math.max(0,-net);}
  const t=Math.max(0,Math.min(1,((actions.jawOpen??0)-.1)/.22));actions.tongueOut=(actions.tongueOut??0)*t*t*(3-2*t);
  return actions;
}
export function deformFacePositions(mesh:PreparedMesh,actions:Record<string,number>,output:Float32Array){
  output.set(mesh.positions);
  for(const [name,morph] of mesh.morphs){const weight=actions[name]??0;if(!weight)continue;
    for(let i=0;i<morph.indices.length;i++){const at=morph.indices[i]*3,from=i*3;for(let axis=0;axis<3;axis++)output[at+axis]+=morph.deltas[from+axis]*weight;}
  }
  for(const corrective of mesh.correctives.values()){
    const weight=Math.min(corrective.max,corrective.drivers.reduce((product,name)=>product*Math.max(0,Math.min(1,actions[name]??0)),1));if(!weight)continue;
    for(let i=0;i<corrective.indices.length;i++){const at=corrective.indices[i]*3,from=i*3;for(let axis=0;axis<3;axis++)output[at+axis]+=corrective.deltas[from+axis]*weight;}
  }
}
/** The artist mesh is a preview adapter. DAZ channels stay owned by the target profile. */
export class ExpressionFaceModel {
  readonly group=new THREE.Group();
  readonly bounds:THREE.Box3;
  private surfaces:{source:PreparedMesh;geometry:THREE.BufferGeometry;positions:Float32Array}[]=[];
  private eyes:{pivot:THREE.Group;definition:FacePreviewManifest['eyes'][number]}[]=[];
  private materials:THREE.Material[]=[];
  private previous:string|null=null;
  private clearance:ReturnType<typeof createOralClearance>|null;
  private posed=new Map<string,Float32Array>();
  constructor(private asset:FacePreviewAsset){
    this.clearance=asset.manifest.oralAttachments?.[0]?createOralClearance(asset.meshes,asset.manifest.oralAttachments[0],asset.manifest.sha256):null;
    this.bounds=new THREE.Box3(new THREE.Vector3().fromArray(asset.manifest.bounds.min),new THREE.Vector3().fromArray(asset.manifest.bounds.max));
    for(const source of asset.meshes){
      const geometry=new THREE.BufferGeometry(),positions=source.positions.slice();
      geometry.setAttribute('position',new THREE.BufferAttribute(positions,3));geometry.setAttribute('normal',new THREE.BufferAttribute(source.normals.slice(),3));geometry.setIndex(new THREE.BufferAttribute(source.index,1));
      source.definition.groups.forEach(g=>geometry.addGroup(g.start,g.count,g.materialIndex));
      const materials=source.definition.materials.map(m=>new THREE.MeshStandardMaterial({color:new THREE.Color().fromArray(m.color),roughness:m.roughness,metalness:0,side:m.side==='double'?THREE.DoubleSide:THREE.FrontSide}));this.materials.push(...materials);
      const mesh=new THREE.Mesh(geometry,materials);mesh.frustumCulled=false;
      const definition=asset.manifest.eyes.find(e=>e.mesh===source.name);
      if(definition){const pivot=new THREE.Group();pivot.position.fromArray(definition.center);mesh.position.copy(pivot.position).negate();pivot.add(mesh);this.group.add(pivot);this.eyes.push({pivot,definition});}
      else this.group.add(mesh);
      this.surfaces.push({source,geometry,positions});
      this.posed.set(source.name,positions);
    }
  }
  update(values:Record<string,number>){
    const actions=coupledFaceActions(values,this.asset.manifest.actionLimits);
    const signature=JSON.stringify(actions);if(signature===this.previous)return;this.previous=signature;
    for(const {source,positions} of this.surfaces)if(source.morphs.size)deformFacePositions(source,actions,positions);
    // The clearance adapter sees this model's posed buffers only. Source asset
    // arrays and canonical/extracted/exported expression values stay immutable.
    this.clearance?.correct(this.posed,actions);
    for(const {source,geometry,positions} of this.surfaces){
      if(!source.morphs.size)continue;
      geometry.attributes.position.needsUpdate=true;geometry.computeVertexNormals();
      if(source.name==='Tongue'&&this.clearance){
        smoothExtendedTongueTip(geometry.attributes.normal.array as Float32Array,positions,actions.tongueOut??0);
        geometry.attributes.normal.needsUpdate=true;
      }
    }
    for(const {pivot,definition} of this.eyes){
      const side=definition.side,sign=side==='Left'?1:-1,v=(name:string)=>actions[name+side]??0;
      pivot.rotation.set(-THREE.MathUtils.degToRad(definition.pitchLimitDegrees)*(v('eyeLookUp')-v('eyeLookDown')),sign*THREE.MathUtils.degToRad(definition.yawLimitDegrees)*(v('eyeLookOut')-v('eyeLookIn')),0,'YXZ');
    }
  }
  dispose(){this.surfaces.forEach(s=>s.geometry.dispose());this.materials.forEach(m=>m.dispose());this.group.clear();}
}
