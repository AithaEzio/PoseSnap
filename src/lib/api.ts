import { invoke, isTauri } from '@tauri-apps/api/core';
import { open, save } from '@tauri-apps/plugin-dialog';
import { listen } from '@tauri-apps/api/event';
import type { Progress } from './types';
import type { EngineStatus } from './engine';
export const desktop=isTauri();
export async function request<T>(method:string,payload:unknown={},jobId:string=crypto.randomUUID()):Promise<T> {
  if(!desktop) throw new Error('Open PoseSnap.exe to use local files and GPU extraction. This browser shows the interface only.');
  return invoke<T>('request',{request:{version:1,method,payload,jobId}});
}
export async function progress(callback:(value:Progress)=>void){return desktop?listen<Progress>('pose-progress',event=>callback(event.payload)):()=>{};}
export async function pickImage(){return open({title:'Open a reference image',multiple:false,filters:[{name:'Photos and depth images',extensions:['png','jpg','jpeg','webp','bmp','tif','tiff']} ]});}
export async function pickCalibration(){return open({title:'Import camera calibration',multiple:false,filters:[{name:'Camera calibration',extensions:['json']}]});}
export async function pickDaz(){return open({title:'Choose DAZ Studio 6',multiple:false,filters:[{name:'DAZ Studio',extensions:['exe']} ]});}
export async function savePose(name:string){return save({title:'Save Genesis pose',defaultPath:name+'.duf',filters:[{name:'DAZ pose preset',extensions:['duf']} ]});}
export async function saveExpression(name:string){return save({title:'Save Genesis expression',defaultPath:name+'.duf',filters:[{name:'DAZ expression preset',extensions:['duf']} ]});}
export async function clipboard(){return invoke<string>('clipboard_image');}
export async function cancel(){if(desktop)await invoke('cancel');}
export async function openExternalUrl(url:string){return invoke<void>('open_external_url',{url});}
export async function engineStatus(){return invoke<EngineStatus>('engine_status');}
export async function engineTask(action:'check'|'verify'|'install',componentId?:string,source?:string){return invoke<EngineStatus>('engine_task',{action,componentId:componentId??null,source:source??null});}
export async function enginePause(){return invoke('engine_pause');}
export async function engineEvents(callback:(value:EngineStatus)=>void){return desktop?listen<EngineStatus>('engine-status',event=>callback(event.payload)):()=>{};}
export async function pickComponent(folder:boolean){return open({title:folder?'Choose a component or complete PoseSnap folder':'Choose a verified component archive or model',directory:folder,multiple:false});}
