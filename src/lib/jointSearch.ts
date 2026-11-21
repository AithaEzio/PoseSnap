import { jointLabel,joints } from './editor';
import type { Pose,RigNode } from './types';

export const jointFilters=[{id:'all',label:'All'},{id:'body',label:'Body'},{id:'arms',label:'Arms'},{id:'hands',label:'Hands'},{id:'legs',label:'Legs'}] as const;
export type JointFilter=typeof jointFilters[number]['id'];
/** Resolve the actual joint or its nearest anatomical ancestor on G8/G9. */
function section(nodes:Map<string,RigNode>,id:string):string {
  const visited=new Set<string>();
  for(let n=nodes.get(id);n&&!visited.has(n.id);n=n.parent?nodes.get(n.parent):undefined){
    visited.add(n.id);
    const side=/^([lr])(?:_|[A-Z])/.exec(n.id)?.[1];
    if(!side)continue;
    if(/hand|thumb|index|middle|mid\d|ring|pinky|metacarpal/i.test(n.id))return side+'-hand';
    if(/thigh|shin|foot|toe|metatarsal/i.test(n.id))return side+'-leg';
    if(/collar|shoulder|shldr|upperarm|forearm/i.test(n.id))return side+'-arm';
  }
  return 'body';
}
export function jointSection(pose:Pose,id:string){return section(new Map(pose.rig.nodes.map(n=>[n.id,n])),id);}
export function chooserGroup(pose:Pose,id:string,current:'body'|'arms'|'hands'|'legs') {
  if(id==='$figure'||!pose.rig.nodes.some(n=>n.id===id))return current;
  const part=jointSection(pose,id);
  return part.endsWith('-hand')?'hands':part.endsWith('-arm')?'arms':part.endsWith('-leg')?'legs':'body';
}
const sections=[
  {id:'body',label:'Torso & head',category:'body'},
  {id:'l-arm',label:'Left arm',category:'arms'},{id:'r-arm',label:'Right arm',category:'arms'},
  {id:'l-hand',label:'Left hand & fingers',category:'hands'},{id:'r-hand',label:'Right hand & fingers',category:'hands'},
  {id:'l-leg',label:'Left leg & foot',category:'legs'},{id:'r-leg',label:'Right leg & foot',category:'legs'},
] as const;

export function jointSearchGroups(pose:Pose,query='',filter:JointFilter='all'){
  const nodes=new Map(pose.rig.nodes.map(n=>[n.id,n]));
  const tokens=query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const classified=joints(pose).map(node=>({node,section:section(nodes,node.id)}));
  return sections.filter(group=>filter==='all'||group.category===filter).map(group=>({...group,nodes:classified.filter(entry=>{
    const node=entry.node;
    if(entry.section!==group.id)return false;
    const aliases=/^[lr]_?hand$/i.test(node.id)?'wrist palm':/^[lr]_?foot$/i.test(node.id)?'ankle':/abdomen|chest|spine/i.test(node.id)?'spine torso':'';
    const text=(group.label+' '+group.category+' '+jointLabel(node)+' '+node.id+' '+aliases).toLowerCase();
    return tokens.every(token=>text.includes(token));
  }).map(entry=>entry.node)})).filter(group=>group.nodes.length);
}
