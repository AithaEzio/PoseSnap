import {readFileSync} from 'node:fs';
import {parse} from 'svelte/compiler';
import {transpileModule,ScriptTarget} from 'typescript';
import {beforeEach,afterEach,describe,it,expect,vi} from 'vitest';
import {liveNumber} from '../src/lib/liveNumber';
import {adjustDetail,detailValue,detailSliders} from '../src/lib/expression/details';
import {defaultOptions} from '../src/lib/expression/types';

// Run the actual Svelte handlers with a connected target and isolated transport.
// The browser-only face preview has no connected profile and cannot reproduce
// the native refit that originally disabled a field between its first two digits.
function handlers(file:string,names:string[],ctx:Record<string,any>){
  const source=readFileSync(file,'utf8'),ast=parse(source) as any;
  const declarations=ast.instance.content.body.map((node:any)=>node.type==='ExportNamedDeclaration'?node.declaration:node);
  const snippets=names.map(name=>{const node=declarations.find((n:any)=>n?.type==='FunctionDeclaration'&&n.id.name===name);if(!node)throw Error(name);return source.slice(node.start,node.end);}).join('\n');
  const code=transpileModule(snippets,{compilerOptions:{target:ScriptTarget.ES2022}}).outputText;
  return new Function('ctx',`with(ctx){${code};return {${names.join(',')}};}`)(ctx);
}
class Field extends EventTarget{
  value='';disabled=false;
  get valueAsNumber(){return this.value.trim()===''?NaN:Number(this.value);}
  focus(){if(!this.disabled){(document as any).activeElement=this;this.dispatchEvent(new Event('focus'));}}
  blur(){(document as any).activeElement=null;this.dispatchEvent(new Event('blur'));}
  type(value:string){this.value=value;this.dispatchEvent(new Event('input'));}
  key(key:string){const event=Object.assign(new Event('keydown',{cancelable:true}),{key});this.dispatchEvent(event);return event;}
}
function setup(rig='g8m'){
  const ctx:Record<string,any>={numberFocused:false,disposed:false,refitTimer:null,busy:false,revision:0,rig,profiles:{[rig]:{}},api:{desktop:true},source:{face:{id:2,actions:{},extras:{}}},options:defaultOptions(),target:{supported:43},labels:{[rig]:rig},error:'',request:vi.fn().mockImplementation(async(_method,payload)=>({options:structuredClone(payload.options)})),begin:vi.fn(()=>ctx.busy=true),finish:vi.fn(()=>ctx.busy=false)};
  const workspace=handlers('src/lib/expression/ExpressionWorkspace.svelte',['fit','queueRefit','numberFocus','changeOptions'],ctx);
  const controls=handlers('src/lib/expression/ExpressionControls.svelte',['holdRefit','strength','detail'],{
    get source(){return ctx.source;},get busy(){return ctx.busy;},get options(){return ctx.options;},
    onNumberFocus:workspace.numberFocus,onChange:workspace.changeOptions,adjustDetail
  });
  function field(id='strength'){
    const input=new Field(),hold=controls.holdRefit(input),current=()=>id==='strength'?ctx.options.strength*100:detailValue(id,ctx.source,ctx.options)*100;
    const opts=()=>({value:current(),context:'face-2/'+id,normalize:(value:number)=>Math.max(id==='horizontal'||id==='vertical'?-100:0,Math.min(id==='strength'?150:100,value)),onValue:(value:number)=>{if(id==='strength')controls.strength(value);else controls.detail(id,value);live.update(opts());},onEditing:()=>{}});
    const live=liveNumber(input as unknown as HTMLInputElement,opts());
    return {input,current,destroy(){hold.destroy();live.destroy();}};
  }
  return {ctx,workspace,field};
}
describe('Expression number editing with a connected target',()=>{
  beforeEach(()=>{vi.useFakeTimers();vi.stubGlobal('document',{activeElement:null});});
  afterEach(()=>{vi.clearAllTimers();vi.useRealTimers();vi.unstubAllGlobals();});
  it.each(['g8f','g8m','g9'])('keeps focus through 1 → 10 → 100 and pauses on %s',async rig=>{
    const {ctx,field}=setup(rig),number=field();number.input.focus();
    for(const value of ['1','10','100']){
      number.input.type(value);await vi.advanceTimersByTimeAsync(500);
      expect(document.activeElement).toBe(number.input);expect(ctx.busy).toBe(false);expect(number.current()).toBe(Number(value));expect(ctx.request).not.toHaveBeenCalled();
    }
    number.input.blur();await vi.advanceTimersByTimeAsync(160);
    expect(ctx.request).toHaveBeenCalledOnce();expect(ctx.target.options.strength).toBe(1);number.destroy();
  });
  it('cancels an older queued fit as soon as an unchanged number field receives focus',async()=>{
    const {ctx,workspace,field}=setup();workspace.changeOptions({...ctx.options,strength:.4});await vi.advanceTimersByTimeAsync(100);
    const number=field();number.input.focus();await vi.advanceTimersByTimeAsync(1000);expect(ctx.request).not.toHaveBeenCalled();
    number.input.type('10');number.input.blur();await vi.advanceTimersByTimeAsync(160);expect(ctx.target.options.strength).toBe(.1);expect(ctx.request).toHaveBeenCalledOnce();number.destroy();
  });
  it.each(detailSliders.map(slider=>slider.id))('keeps %s editable through a multi-digit value and a pause',async id=>{
    const {ctx,field}=setup(),number=field(id);number.input.focus();number.input.type('1');await vi.advanceTimersByTimeAsync(500);number.input.type('10');await vi.advanceTimersByTimeAsync(500);
    expect(document.activeElement).toBe(number.input);expect(ctx.busy).toBe(false);expect(ctx.request).not.toHaveBeenCalled();expect(number.current()).toBeCloseTo(10);
    number.input.blur();await vi.advanceTimersByTimeAsync(160);expect(ctx.request).toHaveBeenCalledOnce();expect(ctx.target.options).toEqual(ctx.options);number.destroy();
  });
  it('allows decimals and Enter to finish the edit and fit its final amount',async()=>{
    const {ctx,field}=setup(),number=field();number.input.focus();
    for(const value of ['2','2.','2.5']){number.input.type(value);await vi.advanceTimersByTimeAsync(300);}
    expect(ctx.request).not.toHaveBeenCalled();expect(number.input.key('Enter').defaultPrevented).toBe(true);
    await vi.advanceTimersByTimeAsync(160);expect(ctx.target.options.strength).toBe(.025);expect(ctx.busy).toBe(false);number.destroy();
  });
  it('holds fitting for negative gaze input and independently fits a detail slider amount',async()=>{
    const {ctx,field}=setup(),gaze=field('horizontal');gaze.input.focus();
    for(const value of ['-','-1','-10']){gaze.input.type(value);await vi.advanceTimersByTimeAsync(300);}
    expect(ctx.request).not.toHaveBeenCalled();gaze.input.blur();await vi.advanceTimersByTimeAsync(160);
    expect(ctx.target.options.adjustments.eyeLookInLeft).toBe(.1);expect(ctx.target.options.adjustments.eyeLookOutRight).toBe(.1);gaze.destroy();
    const cheek=field('cheekPuff');cheek.input.focus();cheek.input.type('1');await vi.advanceTimersByTimeAsync(500);cheek.input.type('10');expect(ctx.request).toHaveBeenCalledOnce();cheek.input.blur();await vi.advanceTimersByTimeAsync(160);
    expect(ctx.target.options.adjustments.cheekPuff).toBe(.1);expect(ctx.target.options.adjustments.eyeLookInLeft).toBe(.1);cheek.destroy();
  });
  it('does not fit between two fields when Tab immediately transfers focus',async()=>{
    const {ctx,field}=setup(),strength=field(),tongue=field('tongueOut');strength.input.focus();strength.input.type('10');strength.input.blur();tongue.input.focus();
    await vi.advanceTimersByTimeAsync(500);expect(ctx.request).not.toHaveBeenCalled();tongue.input.type('25');tongue.input.blur();await vi.advanceTimersByTimeAsync(160);
    expect(ctx.request).toHaveBeenCalledOnce();expect(ctx.target.options.strength).toBe(.1);expect(ctx.target.options.adjustments.tongueOut).toBe(.25);strength.destroy();tongue.destroy();
  });
  it('releases a focused field when controls collapse, but never refits a disposed workspace',async()=>{
    const {ctx,field}=setup(),number=field();number.input.focus();number.input.type('10');number.destroy();await vi.advanceTimersByTimeAsync(160);expect(ctx.request).toHaveBeenCalledOnce();
    const next=field();next.input.focus();next.input.type('25');ctx.disposed=true;next.destroy();await vi.advanceTimersByTimeAsync(1000);expect(ctx.numberFocused).toBe(false);expect(ctx.request).toHaveBeenCalledOnce();
  });
  it('keeps an unchanged fitted result without requesting another fit on focus and blur',async()=>{
    const {ctx,field}=setup(),number=field();number.input.focus();number.input.blur();await vi.advanceTimersByTimeAsync(1000);expect(ctx.request).not.toHaveBeenCalled();number.destroy();
  });
});
