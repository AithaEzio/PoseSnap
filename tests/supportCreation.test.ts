import {readFileSync} from 'node:fs';
import {parse} from 'svelte/compiler';
import {transpileModule,ScriptTarget} from 'typescript';
import {describe,it,expect,vi} from 'vitest';
import {guidanceStatus} from '../src/lib/guidance';

// Exercise the real completion handlers with isolated model/transport stubs.
// No models, app history, settings or engagement records are touched.
function handler(file:string,name:string,ctx:Record<string,unknown>){
  const source=readFileSync(file,'utf8'),ast=parse(source) as any;
  const node=ast.instance.content.body.map((n:any)=>n.type==='ExportNamedDeclaration'?n.declaration:n).find((n:any)=>n?.type==='FunctionDeclaration'&&n.id.name===name);
  if(!node)throw Error('Missing handler '+name);
  const code=transpileModule(source.slice(node.start,node.end),{compilerOptions:{target:ScriptTarget.ES2022}}).outputText;
  return (...args:unknown[])=>new Function('ctx','args',`with(ctx){${code};return ${name}(...args);}`)(ctx,args);
}
function app(){return {guidanceStatus,extractDisabled:false,photo:{id:'photo'},selected:1,pose:null,groupActive:false,clearEdits:vi.fn(),clearPose:vi.fn(),rig:'g8f',refinement:'accurate',extractionMethod:'auto',zeroCroppedJoints:true,imageGuidance:'auto',inputKind:'photo',extractionFor:()=> 'pure',job:vi.fn().mockResolvedValue({personId:1,rigId:'g8f'}),notice:'',lastRefinement:null,refinementSnapshots:new Map(),sourceAvailable:false,interactionChoices:{},reset:0,api:{desktop:true,request:vi.fn().mockResolvedValue([])},history:[],error:'',formatElapsed:()=> '1s',recordCreation:vi.fn()};}
function text(){
  const result={id:'batch',poses:[{personId:1},{personId:2}],intent:{},alternatives:[{id:'a'},{id:'b'},{id:'c'}]};
  return {prompt:'Both dancing',busy:false,canVary:true,fingerprint:'same',shown:null,variationBatch:[],actors:[{id:1,rigId:'g8f'},{id:2,rigId:'g9'}],style:'natural',handShapes:false,work:async(_label:unknown,fn:()=>unknown)=>fn(),request:vi.fn().mockResolvedValueOnce({runtime:{},intent:{status:'plan'}}).mockResolvedValueOnce(result),runtime:null,onstatus:vi.fn(),interpreted:null,progress:vi.fn(),choices:[],candidate:null,previewFingerprint:'',selected:1,previewMode:'pose',reset:0,notice:'',refresh:vi.fn(),recordCreation:vi.fn()};
}
describe('count completed user creations without counting internal work',()=>{
  it('counts a successful explicit extraction, including a reused result, but not a failed or cancelled job',async()=>{
    const ctx=app(),run=handler('src/App.svelte','extract',ctx);await run();await run();
    expect(ctx.recordCreation).toHaveBeenCalledTimes(2);expect(ctx.recordCreation.mock.calls[0][0]).not.toBe(ctx.recordCreation.mock.calls[1][0]);
    ctx.job.mockResolvedValue(null);await run();expect(ctx.recordCreation).toHaveBeenCalledTimes(2);
    ctx.extractDisabled=true;await run();expect(ctx.recordCreation).toHaveBeenCalledTimes(2);
  });
  it('counts a whole successful interaction by actor, excluding partial builds',async()=>{
    const poses=[{personId:1,rigId:'g8f'},{personId:2,rigId:'g9'}],ctx={...app(),busy:false,chosenMembers:poses,status:{rigs:['g8f','g9']},interactionBuild:'',interaction:null,placement:'keep',drawer:'interaction',rigLabels:{},job:vi.fn().mockResolvedValue({poses})};
    await handler('src/App.svelte','buildInteraction',ctx)();expect(ctx.recordCreation).toHaveBeenCalledOnce();expect(ctx.recordCreation.mock.calls[0][1]).toBe(2);
    ctx.recordCreation.mockClear();ctx.job.mockResolvedValueOnce({}).mockResolvedValueOnce(null);
    await handler('src/App.svelte','buildInteraction',ctx)();expect(ctx.recordCreation).not.toHaveBeenCalled();
  });
  it('counts Create and More like this once per actor, rather than once per alternative',async()=>{
    for(const variation of [false,true]){
      const ctx=text();await handler('src/lib/text/TextWorkspace.svelte','preview',ctx)(variation);
      expect(ctx.choices).toHaveLength(3);expect(ctx.recordCreation).toHaveBeenCalledOnce();expect(ctx.recordCreation.mock.calls[0][1]).toBe(2);
    }
  });
  it('does not count a clarification or a preview invalidated during generation',async()=>{
    const clarify=text();clarify.request.mockReset().mockResolvedValue({runtime:{},intent:{status:'clarify'}});await handler('src/lib/text/TextWorkspace.svelte','preview',clarify)();expect(clarify.recordCreation).not.toHaveBeenCalled();
    const stale=text();stale.work=async(_label,fn)=>{const result=await fn();stale.fingerprint='changed';return result;};await handler('src/lib/text/TextWorkspace.svelte','preview',stale)();expect(stale.recordCreation).not.toHaveBeenCalled();
  });
  it('counts an extracted expression only after its published result and save succeed',async()=>{
    const face={id:1},ctx={busy:false,photo:{id:'photo'},selected:1,installed:true,onengine:vi.fn(),faces:[face],revision:0,begin:vi.fn(),faceEngine:{run:vi.fn().mockResolvedValue({face})},originalUrl:'',progress:vi.fn(),sourceFromFace:()=>({face}),api:{desktop:true},profiles:{},rig:'g8f',options:{},request:vi.fn().mockResolvedValue({}),onhistory:vi.fn(),source:null,target:null,neutral:false,notice:'',connected:true,error:'',finish:vi.fn(),formatElapsed:()=> '1s',recordCreation:vi.fn()};
    const run=handler('src/lib/expression/ExpressionWorkspace.svelte','extract',ctx);await run();expect(ctx.recordCreation).toHaveBeenCalledOnce();
    ctx.recordCreation.mockClear();ctx.request.mockRejectedValue(Error('Save failed'));await run();expect(ctx.recordCreation).not.toHaveBeenCalled();
    ctx.faceEngine.run.mockImplementation(async()=>{ctx.revision++;return {face};});await run();expect(ctx.recordCreation).not.toHaveBeenCalled();
  });
  it('requires 33 deliberate activations in one About visit, persisting only on completion',async()=>{
    const visit=()=>({activations:0,disabled:false,saving:false,message:'',desktop:true,supportEvent:vi.fn().mockResolvedValue({disabled:true})});
    const ctx=visit(),run=handler('src/lib/AboutCreator.svelte','activate',ctx);
    for(let i=0;i<32;i++)await run();expect(ctx.supportEvent).not.toHaveBeenCalled();
    const next=visit();await handler('src/lib/AboutCreator.svelte','activate',next)();expect(next.supportEvent).not.toHaveBeenCalled();
    await run();expect(ctx.supportEvent).toHaveBeenCalledWith({kind:'disable'});expect(ctx.message).toBe('Automatic support reminders are off.');
    await run();expect(ctx.supportEvent).toHaveBeenCalledOnce();
  });
});
