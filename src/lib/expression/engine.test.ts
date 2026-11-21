import { afterEach,beforeEach,describe,expect,it,vi } from 'vitest';
vi.mock('../api',()=>({desktop:false}));
import { FaceEngine } from './engine';
const workers:MockWorker[]=[];
class MockWorker {
  onmessage:((event:any)=>void)|null=null;onerror:(()=>void)|null=null;terminated=false;message:any;
  constructor(){workers.push(this);}
  postMessage(data:any){this.message=data;}
  terminate(){this.terminated=true;}
  deliver(data:any){this.onmessage?.({data:{jobId:this.message.jobId,...data}});}
}
const flush=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};
beforeEach(()=>{vi.useFakeTimers();workers.length=0;vi.stubGlobal('Worker',MockWorker);vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,blob:async()=>new Blob()})));vi.stubGlobal('createImageBitmap',vi.fn(async()=>({close:vi.fn()})));});
afterEach(()=>{vi.unstubAllGlobals();vi.useRealTimers();});
describe('facial worker lifecycle',()=>{
  it('transfers a plain crop and matches result identity',async()=>{const engine=new FaceEngine(),progress=vi.fn();const box=[1,2,101,202];const result=engine.run('extract','/local',progress,{id:2,box,landmarks:[],actions:{},matrix:[]});await flush();expect(workers[0].message.box).toEqual(box);expect(workers[0].message.box).not.toBe(box);workers[0].deliver({type:'result',face:{id:2}});expect((await result).face?.id).toBe(2);engine.cancel();});
  it('cancels fetch before constructing a worker',async()=>{let resolve:(response:any)=>void=()=>{};vi.stubGlobal('fetch',vi.fn(()=>new Promise(r=>resolve=r)));const engine=new FaceEngine(),result=engine.run('detect','/local',vi.fn()).catch(e=>e.message);engine.cancel();resolve({ok:true,blob:async()=>new Blob()});await flush();expect(await result).toContain('Cancelled');expect(workers.length).toBe(0);});
  it('cancels inference and ignores old worker results/errors',async()=>{const engine=new FaceEngine();const first=engine.run('detect','/first',vi.fn()).catch(e=>e.message);await flush();const old=workers[0];engine.cancel();expect(await first).toContain('Cancelled');const second=engine.run('detect','/second',vi.fn());await flush();old.deliver({type:'result',faces:[{id:99}]});old.onerror?.();expect(workers[1].terminated).toBe(false);workers[1].deliver({type:'result',faces:[{id:2}]});expect((await second).faces?.[0].id).toBe(2);engine.cancel();});
  it('rejects parallel work and releases assets after the idle timeout',async()=>{const engine=new FaceEngine(),first=engine.run('detect','/first',vi.fn());await flush();await expect(engine.run('detect','/second',vi.fn())).rejects.toThrow('current facial task');workers[0].deliver({type:'result',faces:[]});await first;vi.advanceTimersByTime(60000);expect(workers[0].terminated).toBe(true);});
  it('terminates failures and allows a clean retry',async()=>{const engine=new FaceEngine(),first=engine.run('detect','/first',vi.fn()).catch(e=>e.message);await flush();workers[0].deliver({type:'error',message:'Missing model'});expect(await first).toBe('Missing model');expect(workers[0].terminated).toBe(true);const retry=engine.run('detect','/retry',vi.fn());await flush();workers[1].deliver({type:'result',faces:[]});expect((await retry).faces).toEqual([]);engine.cancel();});
  it.each(['missing reference','corrupt image'])('still unloads the existing model after a %s',async failure=>{
    const engine=new FaceEngine(),first=engine.run('detect','/first',vi.fn());await flush();workers[0].deliver({type:'result',faces:[]});await first;
    if(failure==='missing reference')vi.stubGlobal('fetch',vi.fn(async()=>({ok:false})));else vi.stubGlobal('createImageBitmap',vi.fn(async()=>{throw Error('Corrupt image');}));
    await expect(engine.run('detect','/bad',vi.fn())).rejects.toThrow();
    expect(workers[0].terminated).toBe(false);vi.advanceTimersByTime(60000);expect(workers[0].terminated).toBe(true);
  });
  it('closes an untransferred bitmap when worker construction fails and permits retry',async()=>{
    const close=vi.fn();vi.stubGlobal('createImageBitmap',vi.fn(async()=>({close})));vi.stubGlobal('Worker',class{constructor(){throw Error('Worker unavailable');}});
    const engine=new FaceEngine();await expect(engine.run('detect','/first',vi.fn())).rejects.toThrow('Worker unavailable');expect(close).toHaveBeenCalledOnce();
    vi.stubGlobal('Worker',MockWorker);const retry=engine.run('detect','/retry',vi.fn());await flush();workers[0].deliver({type:'result',faces:[]});expect((await retry).faces).toEqual([]);engine.cancel();
  });
});
