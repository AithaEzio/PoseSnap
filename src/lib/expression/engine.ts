import { desktop } from '../api';
import type { Face } from './types';
export const faceAssetBase=desktop?'http://expression.localhost':'/__expression-assets';
export const faceImageUrl=(id:string)=>faceAssetBase+'/image/'+encodeURIComponent(id);
export class FaceEngine {
  private worker:Worker|null=null;
  private pending:{reject:(error:Error)=>void}|null=null;
  private timeout:ReturnType<typeof setTimeout>|null=null;
  private idle:ReturnType<typeof setTimeout>|null=null;
  private abort:AbortController|null=null;
  private generation=0;
  private loading=false;
  private scheduleIdle(){if(this.idle)clearTimeout(this.idle);this.idle=this.worker?setTimeout(()=>this.cancel(),60000):null;}
  cancel(){this.generation++;this.loading=false;this.abort?.abort();this.abort=null;this.pending?.reject(new Error('Cancelled. Your previous expression is preserved.'));this.pending=null;this.worker?.terminate();this.worker=null;if(this.timeout)clearTimeout(this.timeout);if(this.idle)clearTimeout(this.idle);this.timeout=null;this.idle=null;}
  async run(type:'detect'|'extract',url:string,progress:(label:string,percent:number)=>void,face?:Face):Promise<{faces?:Face[];face?:Face}>{
    if(this.pending||this.loading)throw Error('Finish the current facial task first.');
    if(this.idle)clearTimeout(this.idle);
    this.loading=true;const generation=++this.generation;this.abort=new AbortController();
    let bitmap:ImageBitmap;
    try{const response=await fetch(url,{signal:this.abort.signal});if(!response.ok)throw Error('The original reference could not be opened. Import it again.');bitmap=await createImageBitmap(await response.blob());}catch(error){if(generation===this.generation)this.scheduleIdle();throw error;}finally{if(generation===this.generation){this.loading=false;this.abort=null;}}
    if(generation!==this.generation){bitmap.close();throw Error('Cancelled. Your previous expression is preserved.');}
    try{this.worker??=new Worker('/expression-worker.js');}catch(error){bitmap.close();this.scheduleIdle();throw error;}
    const worker=this.worker,jobId=crypto.randomUUID();
    return new Promise((resolve,reject)=>{
      this.pending={reject};
      const finish=()=>{this.pending=null;if(this.timeout)clearTimeout(this.timeout);this.timeout=null;this.scheduleIdle();};
      worker.onmessage=({data})=>{
        if(generation!==this.generation)return;
        if(data.type==='progress'){progress(data.label,data.percent);return;}
        if(data.jobId!==jobId)return;
        finish();if(data.type==='error'){reject(Error(data.message));this.worker?.terminate();this.worker=null;}else resolve(data);
      };
      worker.onerror=()=>{if(generation!==this.generation)return;finish();worker.terminate();this.worker=null;reject(Error('The local face engine could not start. Verify Expression engine in Settings → Engine & downloads.'));};
      this.timeout=setTimeout(()=>{this.cancel();reject(Error('The face engine timed out. Verify its local files and try again.'));},60000);
      try{worker.postMessage({type,jobId,base:faceAssetBase,bitmap,box:face?Array.from(face.box):undefined,faceId:face?.id,roll:face?.roll},[bitmap]);}catch(error){bitmap.close();finish();worker.terminate();this.worker=null;reject(error);}
    });
  }
}
