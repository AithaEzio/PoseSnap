/** DAZ completion is acknowledged by the worker; this also bounds a stalled bridge. */
export function waitForDaz<T>(operation:Promise<T>,cancel:()=>Promise<unknown>,timeout=70_000):Promise<T>{
  return new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>{
      void cancel().catch(()=>{});
      reject(new Error('DAZ did not finish this task. PoseSnap stopped waiting and kept your expression. Check DAZ and the selected figure before retrying.'));
    },timeout);
    operation.then(value=>{clearTimeout(timer);resolve(value);},error=>{clearTimeout(timer);reject(error);});
  });
}
