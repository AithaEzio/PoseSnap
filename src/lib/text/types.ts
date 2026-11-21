import type {Pose,RigId,Settings} from '../types';
import type {ExpressionSource,TargetExpression} from '../expression/types';
import type {EngineStatus} from '../engine';
export interface TextSettings {textHandShapes:boolean}
export const defaults:TextSettings={textHandShapes:false};
export function textSettings(settings?:Partial<Settings>):TextSettings{return {textHandShapes:settings?.textHandShapes===true};}
export type PoseCharacter='natural'|'expressive'|'dramatic'|'happy'|'sad'|'tired';
export const profiles:PoseCharacter[]=['natural','expressive','dramatic','happy','sad','tired'];
export interface TextActor {id:number;rigId:RigId}
export interface KimodoRuntime {version:1;ready:boolean;phase:'ready'|'unloaded'|'missing'|'attention';error:string;encoderReady:boolean;motionReady:boolean;installed:Record<string,boolean>;experimental:boolean;idleSeconds:number;cacheBytes:number}
export interface CapabilityQualification {id:string;label:string;status:'qualified'|'experimental'|'unavailable';compatible:boolean;componentSignature:string;evidenceRevision:string|null;scope:string;limits:string[]}
export interface TextRuntime {version:2;settings:TextSettings;kimodo:KimodoRuntime;capabilities?:CapabilityQualification[]}
export interface TextExpression {actorId:number;rigId:RigId;source:ExpressionSource;target:TargetExpression|null}
export interface TextIntent {status:'plan'|'clarify'|'unsupported';message?:string;summary?:string;assumptions?:string[];interaction?:string;actors?:{id:number;recipe:string;changes:{part:string;movement:string;amount:number}[];preserve:string[];expression:Record<string,number>;support:Record<string,string>}[]}
// Accepted v1 history remains readable, including retired edits and facial results.
export interface TextResult {version:1;id:string;signature:string;prompt:string;output:'pose'|'expression'|'both';mode:'create'|'modify';intent:TextIntent;poses:Pose[];expressions:TextExpression[];created:number;generation?:{style?:PoseCharacter;handShapes?:boolean};alternatives?:TextResult[];choiceDiagnostics?:{requested:number;returned:number;rejected:string[]}}
export function actorsFromPoses(poses:Pose[]):TextActor[]{return poses.slice(0,2).map((p,i)=>({id:i+1,rigId:p.rigId}));}
export function canVaryPreview(actors:TextActor[],result:TextResult|null,prompt:string,style:PoseCharacter,handShapes:boolean){
  return !!result&&result.mode==='create'&&result.output==='pose'&&result.prompt===prompt.trim()&&result.poses.length===actors.length&&actors.every(a=>result.poses.some(p=>p.personId===a.id&&p.rigId===a.rigId))&&(result.generation?.style??'natural')===style&&(result.generation?.handShapes??true)===handShapes;
}
export function kimodoIndicator(status:KimodoRuntime|null|undefined,busy:boolean,stage:string,desktop:boolean){
  if(busy)return {state:/^(Loading|Verifying|Unloading)/i.test(stage)?'checking':'running',label:'Local AI Engine '+(/^(Loading|Verifying|Unloading)/i.test(stage)?'Preparing':'Running'),detail:stage};
  if(!desktop)return {state:'preview',label:'Local AI preview',detail:'Kimodo runs in the desktop app. This is a development preview.'};
  if(!status)return {state:'checking',label:'Local AI Engine Checking',detail:'Checking optional Kimodo components.'};
  if(status.ready)return {state:'ready',label:'Local AI Engine Ready',detail:'Kimodo CPU Q8 encoder and CUDA motion generator are loaded. Experimental body generation.'};
  if(status.phase==='attention')return {state:'attention',label:'Local AI Engine Needs attention',detail:status.error};
  return {state:'idle',label:'Local AI Engine '+(status.phase==='missing'?'Not installed':'Unloaded'),detail:status.phase==='missing'?'Install or import the optional Kimodo components in Engine settings.':'Kimodo files are installed. Load manually or preview a body pose to load them.'};
}
export function textIndicator(status:TextRuntime|null,busy:boolean,stage:string,desktop:boolean,engine?:EngineStatus|null){
  if(desktop&&!busy&&engine?.phase==='attention'&&!engine.active&&!engine.runtimeReady)return {state:'attention',label:'Local AI Engine Needs attention',detail:'Set up the private Python component in Engine settings to use Kimodo.'};
  return kimodoIndicator(status?.kimodo,busy,stage,desktop);
}
