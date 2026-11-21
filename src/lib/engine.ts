export interface EngineComponent {
  id:string; label:string; version:string; required:boolean;
  state:'unchecked'|'checking'|'installed'|'missing'|'attention'; locations:string[]; relativeLocations:string[];
  installedBytes:number; downloadBytes:number|null; source:string|null; downloadSources:string[]; downloadable:boolean; message:string;
}
export interface EngineStatus {
  version:1; root:string; phase:'checking'|'downloading'|'verifying'|'booting'|'ready'|'attention';
  ready:boolean; runtimeReady:boolean; active:boolean; message:string; components:EngineComponent[];
  transfers:{componentId:string;label:string;bytes:number;total:number;bytesPerSecond:number}[]; gpu:string|null;
  verification?:{completed:number;total:number;stage?:'inventory'|'hashing'|null;filesExamined?:number;filesTotal?:number;bytesRead?:number;bytesTotal?:number}|null;
}
export function verificationStatus(verification:EngineStatus['verification']){
  if(!verification?.stage)return {fraction:0,detail:null};
  const ratio=(done:number|undefined,total:number|undefined)=>{
    if(typeof done!=='number'||typeof total!=='number'||!Number.isFinite(done)||!Number.isFinite(total)||total<=0)return 0;
    return Math.min(1,Math.max(0,done/total));
  };
  if(verification.stage==='inventory')return {fraction:.15*ratio(verification.filesExamined,verification.filesTotal),detail:`${(verification.filesExamined??0).toLocaleString('en-US')} / ${(verification.filesTotal??0).toLocaleString('en-US')} files inspected`};
  return {fraction:.15+.85*ratio(verification.bytesRead,verification.bytesTotal),detail:`${bytes(verification.bytesRead??0)} / ${bytes(verification.bytesTotal??0)} read for checksums`};
}
export const engineLabels:Record<EngineStatus['phase'],string>={checking:'Engine checking',downloading:'Engine downloading',verifying:'Engine verifying',booting:'Engine booting up',ready:'Engine ready',attention:'Engine needs attention'};
export function engineIndicator(engine:EngineStatus|null,desktop:boolean,busy=false,stage='') {
  const phaseLabel=engine?engineLabels[engine.phase].replace('Engine ','').replace(/^./,letter=>letter.toUpperCase()):'';
  if (engine&&(engine.phase==='attention'||engine.phase==='ready'&&!engine.ready)) return {state:'attention',label:'Needs attention',detail:engine.message};
  if (engine?.active) return {state:['downloading','verifying'].includes(engine.phase)?'running':'checking',label:phaseLabel,detail:engine.message};
  if (busy) return {state:'running',label:'Running',detail:stage||'Processing the current task locally.'};
  if (!engine) return desktop ? {state:'checking',label:'Checking',detail:'Checking the private engine and its components.'} : {state:'preview',label:'UI preview',detail:'Development preview. Launch PoseSnap to check the local engine.'};
  if (engine.phase==='ready'&&engine.ready) return {state:'ready',label:'Ready',detail:engine.message};
  return {state:'checking',label:phaseLabel,detail:engine.message};
}
export function expressionIndicator(engine:EngineStatus|null,desktop:boolean,busy=false,stage=''){
  if(busy)return {state:'running',label:/DAZ|Zeroing|Connecting.*face/.test(stage)?'Running':'Analyzing',detail:stage||'Analyzing the selected face locally.'};
  if(!desktop)return {state:'preview',label:'Face preview',detail:'Development facial engine. DAZ actions require the desktop app.'};
  if(!engine||engine.active)return {state:'checking',label:'Face checking',detail:engine?.message||'Checking local facial components.'};
  const component=engine.components.find(c=>c.id==='expression');
  if(component?.state!=='installed')return {state:'attention',label:'Face missing',detail:'Download or import the optional Expression engine in Settings.'};
  if(!engine.runtimeReady)return {state:'attention',label:'Needs attention',detail:'The private Python component is needed for local image import, facial profiles and DAZ export. Open Engine settings.'};
  return {state:'ready',label:'Face ready',detail:'Expression files verified. Analysis runs locally on the CPU; body GPU readiness is separate.'};
}
/** Mode names qualify readiness without changing the underlying engine checks. */
export function workspaceEngineIndicator(mode:'extract'|'editor'|'expression',engine:EngineStatus|null,desktop:boolean,busy=false,stage=''){
  const indicator=mode==='expression'?expressionIndicator(engine,desktop,busy,stage):engineIndicator(engine,desktop,busy,stage);
  const name=mode==='expression'?'Expression Engine':mode==='editor'?'Pose Retargeter Engine':'Pose Engine';
  return indicator.state==='ready'?{...indicator,label:name+' Ready'}:indicator;
}
export function bytes(value:number){return value>=1e9?(value/1e9).toFixed(2)+' GB':value>=1e6?(value/1e6).toFixed(1)+' MB':Math.round(value/1e3)+' KB';}
export function missingDownloads(engine:EngineStatus){return engine.components.filter(c=>c.required&&c.state!=='installed'&&c.downloadable);}
export type SetupProfile='all'|'pose-expression'|'guidance';
/** A complete setup must report blockers, rather than silently skip them. */
export function setupPlan(engine:EngineStatus,profile:SetupProfile='all'){
  const ids=profile==='guidance'?['python','guidance-shade','guidance-shade-detail']:['python','body','camera','segmentation','interaction-detector','wholebody','hands','expression',...(profile==='all'?['kimodo-encoder','kimodo-motion','kimodo-runtime']:[])];
  const pending=ids.map(id=>engine.components.find(c=>c.id===id)).filter((c):c is EngineComponent=>!!c&&c.state!=='installed');
  const unavailable=[...ids.filter(id=>!engine.components.some(c=>c.id===id)),...pending.filter(c=>!c.downloadable).map(c=>c.label)];
  return {pending,unavailable,downloadBytes:pending.reduce((sum,c)=>sum+(c.downloadBytes??0),0),installedBytes:pending.reduce((sum,c)=>sum+c.installedBytes,0)};
}
