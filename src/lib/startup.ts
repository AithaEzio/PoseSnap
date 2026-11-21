import { verificationStatus, type EngineStatus } from './engine';

export interface WorkspaceChecks { preferences:boolean; history:boolean; transport:boolean; preview:boolean }
export function startupState(engine:EngineStatus|null,desktop:boolean,checks:WorkspaceChecks,label:string) {
  const workspaceDone=Object.values(checks).filter(Boolean).length;
  const workspaceReady=workspaceDone===4;
  const engineReady=desktop&&engine?.ready===true&&engine.phase==='ready'&&!engine.active;
  const attention=desktop&&engine?.phase==='attention'&&!engine.active;
  const complete=workspaceReady&&(!desktop||engineReady||attention);
  const verification=engine?.verification;
  const total=4+(desktop?(verification?.total??engine?.components.length??0)+1:0);
  const verificationDetail=verificationStatus(verification);
  const verified=verification?Math.min(verification.completed+(engine?.active?verificationDetail.fraction:0),verification.total):engineReady?engine!.components.length:0;
  const completed=workspaceDone+(desktop?verified+Number(engineReady):0);
  const unknown=desktop&&(!engine||engine.phase==='booting'||engine.active&&!verification);
  return {
    complete,attention:!!attention,workspaceReady,engineReady,
    progress:unknown||complete&&attention?null:Math.min(100,Math.round(completed/total*100)),
    label:complete?attention?'Workspace available · Engine needs attention':desktop?'Workspace and engine ready':'Development workspace ready':desktop&&(!engineReady&&!attention)?engine?.message??'Checking the private engine':label,
    engineLabel:desktop?engineReady?'Ready':attention?'Needs attention':engine?.phase==='booting'?'Checking GPU':'Checking components':'UI preview',
    checksLabel:verification&&!unknown?`${verification.completed}/${verification.total} components checked${engine?.active&&verificationDetail.detail?' · '+verificationDetail.detail:''}`:null
  };
}
