import type { ExpressionOptions, ExpressionSource, FaceProfile, FaceRegion } from './types';

export const detailSliders = [
  {id:'cheekPuff',label:'Cheek puff',region:'cheeks',min:0,hint:'Inflate both cheeks. This is a user adjustment, not a new detection.'},
  {id:'tongueOut',label:'Tongue out',region:'mouth',min:0,hint:'Adjust visible protrusion within the preview and connected figure’s limits. Hidden curl remains unknown.'},
  {id:'horizontal',label:'Eye direction · left / right',region:'gaze',min:-1,hint:'Left and right follow the person’s anatomy. Head orientation stays unchanged.'},
  {id:'vertical',label:'Eye direction · down / up',region:'gaze',min:-1,hint:'Adjust both eyes vertically. Closed or obscured eyes are uncertain.'},
  ...(['Left','Right'] as const).flatMap(side=>[
    {id:`eyeSquint${side}` as const,label:`${side} eye · squint`,region:'eyes' as const,min:0,hint:`Narrow the ${side.toLowerCase()} eyelids. Clears conflicting closure and widening on this eye only.`},
    {id:`eyeBlink${side}` as const,label:`${side} eye · closed`,region:'eyes' as const,min:0,hint:`Close the ${side.toLowerCase()} eye independently. Clears squint and widening on this eye only.`},
    {id:`eyeWide${side}` as const,label:`${side} eye · opened`,region:'eyes' as const,min:0,hint:`Open the ${side.toLowerCase()} eye wider than neutral. Clears closure and squint on this eye only.`}
  ])
] as const;
export const detailGroups=[
  {label:'Mouth, cheeks & gaze',sliders:detailSliders.slice(0,4)},
  {label:'Left eye',sliders:detailSliders.slice(4,7)},
  {label:'Right eye',sliders:detailSliders.slice(7,10)}
];
export const detectedDetailGroups=[
  {label:'Details',items:[['cheekPuff','Cheek puff','cheeks'],['tongueOut','Visible tongue','mouth'],['gaze','Eye direction','gaze']] as const},
  ...(['Left','Right'] as const).map(side=>({label:`${side} eye`,items:[[`eyeSquint${side}`,'Squinting','eyes'],[`eyeBlink${side}`,'Closed','eyes'],[`eyeWide${side}`,'Opened','eyes']] as const}))
];
const eyelidKeys=(id:string)=>/^eye(Squint|Blink|Wide)(Left|Right)$/.test(id)?['eyeSquint','eyeBlink','eyeWide'].map(prefix=>prefix+(id.endsWith('Left')?'Left':'Right')):[id];

function measured(source:ExpressionSource|null,options:ExpressionOptions):Record<string,number>{return {...source?.face.actions,...source?.face.extras,...options.adjustments};}
const gazeKeys=(axis:'horizontal'|'vertical')=>axis==='horizontal'?['eyeLookOutLeft','eyeLookInLeft','eyeLookOutRight','eyeLookInRight']:['eyeLookUpLeft','eyeLookDownLeft','eyeLookUpRight','eyeLookDownRight'];
export function detailValue(id:string,source:ExpressionSource|null,options:ExpressionOptions){
  const a=measured(source,options);
  if(id==='horizontal')return ((a.eyeLookOutLeft??0)-(a.eyeLookInLeft??0)+(a.eyeLookInRight??0)-(a.eyeLookOutRight??0))/2;
  if(id==='vertical')return ((a.eyeLookUpLeft??0)-(a.eyeLookDownLeft??0)+(a.eyeLookUpRight??0)-(a.eyeLookDownRight??0))/2;
  return a[id]??0;
}
/** Explicit overrides leave the source and unrelated/asymmetric actions intact. */
export function adjustDetail(id:typeof detailSliders[number]['id'],value:number,options:ExpressionOptions):ExpressionOptions{
  const slider=detailSliders.find(d=>d.id===id)!;
  const v=Math.max(slider.min,Math.min(1,value)),adjustments={...options.adjustments};
  if(id==='horizontal')Object.assign(adjustments,{eyeLookOutLeft:Math.max(0,v),eyeLookInLeft:Math.max(0,-v),eyeLookOutRight:Math.max(0,-v),eyeLookInRight:Math.max(0,v)});
  else if(id==='vertical')Object.assign(adjustments,{eyeLookUpLeft:Math.max(0,v),eyeLookDownLeft:Math.max(0,-v),eyeLookUpRight:Math.max(0,v),eyeLookDownRight:Math.max(0,-v)});
  else {for(const key of eyelidKeys(id))adjustments[key]=key===id?v:0;}
  return {...options,adjustments,regions:{...options.regions,[slider.region]:true},neutralRegions:options.neutralRegions?.filter(r=>r!==slider.region)};
}
export function resetDetail(id:typeof detailSliders[number]['id'],options:ExpressionOptions):ExpressionOptions{
  const adjustments={...options.adjustments};for(const key of id==='horizontal'||id==='vertical'?gazeKeys(id):eyelidKeys(id))delete adjustments[key];
  return {...options,adjustments};
}
export function detailStatus(action:string,region:FaceRegion,source:ExpressionSource,options:ExpressionOptions,profile?:FaceProfile){
  const keys=action==='gaze'?Object.keys(source.face.actions).filter(k=>k.startsWith('eyeLook')):[action];
  const edited=keys.some(k=>options.adjustments?.[k]!==undefined),amount=Math.max(...keys.map(k=>measured(source,options)[k]??0));
  const evidence=edited?'Adjusted':source.unknown.includes(region)?'Uncertain':amount>.2?'Estimated':'Not observed';
  const needed=keys.filter(k=>(measured(source,options)[k]??0)>.15);
  const supported=new Set(profile?.mappings.map(m=>m.action));
  const transfer=!options.regions[region]?'Region off':!profile?'Connect to transfer':options.neutralRegions?.includes(region)?'Region zeroed':source.unknown.includes(region)&&!edited?'Withheld':profile.rigId==='g9'&&((action==='tongueOut'&&profile.anatomy?.tongue===false)||(action==='gaze'&&profile.anatomy?.eyes===false))?'Anatomy missing':needed.some(k=>!supported.has(k))?'Partial support':action==='tongueOut'&&profile.rigId!=='g9'&&needed.length?'Limited DAZ range':action==='gaze'&&profile.pairedGazeAxes?.length?'Paired eye controls':needed.length?'Ready to transfer':'No movement';
  return {evidence,transfer};
}
