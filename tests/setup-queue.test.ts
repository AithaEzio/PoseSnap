import {expect,it,vi} from 'vitest';
import {componentHandler} from './component-handlers';

function context(){
  const ctx:any={engine:{active:false,components:[]},engineAction:false,busy:false,setupPaused:false,error:'',notice:'',setupPlan:()=>({pending:[{id:'python'},{id:'body'},{id:'expression'}],unavailable:[]})};
  ctx.manageEngine=vi.fn(async()=>{});return ctx;
}
it('installs the complete plan in order and checks only after successful completion',async()=>{
  const ctx=context();await componentHandler('src/App.svelte','downloadComponents',ctx)();
  expect(ctx.manageEngine.mock.calls).toEqual([['install','python'],['install','body'],['install','expression'],['check']]);
  expect(ctx.notice).toContain('installed and checked');
});
it('stops on failure or pause without claiming successful setup',async()=>{
  for(const paused of [false,true]){
    const ctx=context();ctx.manageEngine=vi.fn(async()=>{if(paused)ctx.setupPaused=true;else ctx.error='Failed checksum';});
    await componentHandler('src/App.svelte','downloadComponents',ctx)();expect(ctx.manageEngine).toHaveBeenCalledOnce();expect(ctx.notice).toBe('');
  }
});
it('reports a missing source before downloading a misleading subset',async()=>{
  const ctx=context();ctx.setupPlan=()=>({pending:[{id:'body'}],unavailable:['Python']});
  await componentHandler('src/App.svelte','downloadComponents',ctx)();expect(ctx.manageEngine).not.toHaveBeenCalled();expect(ctx.error).toContain('Python');
});
it('unlocks local setup controls when the task and status IPC both fail',async()=>{
  const ctx:any={api:{desktop:true,engineTask:vi.fn().mockRejectedValue(Error('Connection lost')),engineStatus:vi.fn().mockRejectedValue(Error('Still disconnected'))},busy:false,engineAction:false,setupPaused:false,error:'',engine:{active:true,ready:true,phase:'downloading'},refreshStatus:vi.fn(),history:[{id:'kept'}]};
  await componentHandler('src/App.svelte','manageEngine',ctx)('install','python');
  expect(ctx.engineAction).toBe(false);expect(ctx.engine.active).toBe(false);expect(ctx.engine.ready).toBe(false);expect(ctx.error).toContain('Connection lost');expect(ctx.history).toEqual([{id:'kept'}]);
});
