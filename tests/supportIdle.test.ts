import {readFileSync} from 'node:fs';
import {parse} from 'svelte/compiler';
import {transpileModule,ScriptTarget} from 'typescript';
import {describe,it,expect,vi,beforeEach,afterEach} from 'vitest';
import {idleForReminder} from '../src/lib/support';

const source=readFileSync('src/lib/SupportSystem.svelte','utf8'),ast=parse(source) as any;
const mount=ast.instance.content.body.find((n:any)=>n.type==='ExpressionStatement'&&n.expression.callee?.name==='onMount').expression.arguments[0];
const code=transpileModule(source.slice(mount.start,mount.end).replaceAll('import.meta.env.DEV','false'),{compilerOptions:{target:ScriptTarget.ES2022}}).outputText.replace(/;\s*$/,'');
function setup(){
  const ctx={desktop:true,ready:false,blocked:false,claim:null,open:false,window:new EventTarget(),document:Object.assign(new EventTarget(),{activeElement:{matches:()=>false},visibilityState:'visible',hasFocus:()=>true}),performance:{now:()=>Date.now()},idleForReminder,
    supportEvent:vi.fn().mockImplementation(async(event:{kind:string})=>({disabled:false,pending:'welcome',waitMs:0,claim:event.kind==='claim'?{id:'claim-1234',kind:'welcome'}:null}))};
  const cleanup=new Function('ctx',`with(ctx){return (${code})();}`)(ctx);
  return {ctx,cleanup};
}
describe('safe support display scheduling',()=>{
  beforeEach(()=>{vi.useFakeTimers();vi.setSystemTime(0);});
  afterEach(()=>{vi.clearAllTimers();vi.useRealTimers();});
  it('counts a launch when the workspace appears and waits for five safe idle seconds',async()=>{
    const {ctx,cleanup}=setup();await vi.advanceTimersByTimeAsync(10000);expect(ctx.supportEvent).not.toHaveBeenCalled();
    ctx.ready=true;await vi.advanceTimersByTimeAsync(1000);expect(ctx.supportEvent.mock.calls.filter(c=>c[0].kind==='workspace')).toHaveLength(1);expect(ctx.open).toBe(false);
    await vi.advanceTimersByTimeAsync(4999);expect(ctx.open).toBe(false);await vi.advanceTimersByTimeAsync(1);expect(ctx.open).toBe(true);cleanup();
  });
  it('starts a new idle interval after a long task or pending Apply/Cancel decision',async()=>{
    const {ctx,cleanup}=setup();ctx.ready=true;ctx.blocked=true;
    await vi.advanceTimersByTimeAsync(60000);expect(ctx.open).toBe(false);
    ctx.blocked=false;await vi.advanceTimersByTimeAsync(1000);expect(ctx.open).toBe(false);
    await vi.advanceTimersByTimeAsync(4999);expect(ctx.open).toBe(false);
    // Polling can add up to five seconds; it must never shorten safe idle.
    await vi.advanceTimersByTimeAsync(5001);expect(ctx.open).toBe(true);cleanup();
  });
  it('defers hidden windows and text entry, and suppresses optional storage failures',async()=>{
    const {ctx,cleanup}=setup();ctx.ready=true;ctx.document.visibilityState='hidden';await vi.advanceTimersByTimeAsync(15000);expect(ctx.open).toBe(false);
    ctx.document.visibilityState='visible';ctx.document.activeElement.matches=()=>true;await vi.advanceTimersByTimeAsync(15000);expect(ctx.open).toBe(false);
    ctx.document.activeElement.matches=()=>false;ctx.supportEvent.mockRejectedValue(Error('Storage unavailable'));await vi.advanceTimersByTimeAsync(15000);expect(ctx.open).toBe(false);cleanup();
  });
});
