import {invoke} from '@tauri-apps/api/core';
import {desktop} from './api';

export const creatorLinks={kofi:'https://ko-fi.com/aithaezio',github:'https://github.com/AithaEzio?tab=repositories'} as const;
export type SupportKind='welcome'|'frequent';
export type SupportClaim={id:string;kind:SupportKind};
export type SupportReply={disabled:boolean;pending:SupportKind|null;waitMs:number;claim:SupportClaim|null};
type SupportEvent={kind:'workspace'|'status'|'claim'|'disable'}|{kind:'creation';operationId:string;actors:number}|{kind:'dismiss';claimId:string};
export const supportCopy={
  welcome:{title:'Oh! You missed me?',body:'Back for another creative moment? If PoseSnap is helping bring your ideas to life, consider supporting Aitha, its creator.'},
  frequent:{title:'Looks like you like me.',body:'If PoseSnap is becoming part of your creative flow, a little support helps Aitha keep building and improving it.'}
} as const;
export const closingSeconds=(deadline:number,now:number)=>Math.max(0,Math.ceil((deadline-now)/1000));
export const idleForReminder=(lastActivity:number,now:number,blocked:boolean,visible:boolean)=>!blocked&&visible&&now-lastActivity>=5000;

export async function supportEvent(event:SupportEvent):Promise<SupportReply>{
  if(!desktop)throw Error('Automatic reminders are desktop-only.');
  return invoke<SupportReply>('support_event',{event});
}
/** Called only when a user-requested creation has reached its displayed result. */
export function recordCreation(operationId:string,actors=1){
  if(!desktop)return;
  void (async()=>{for(let attempt=0;attempt<3;attempt++){
    try{await supportEvent({kind:'creation',operationId,actors});return;}
    catch{if(attempt<2)await new Promise(resolve=>setTimeout(resolve,100*(attempt+1)));}
  }})();
}
