import {readFileSync} from 'node:fs';
import {parse} from 'svelte/compiler';
import {transpileModule,ScriptTarget} from 'typescript';
import {describe,it,expect,vi} from 'vitest';
import {actorsFromPoses} from '../src/lib/text/types';

const source=readFileSync('src/lib/text/TextWorkspace.svelte','utf8');
const ast=parse(source) as any;
function handler(name:string,ctx:Record<string,unknown>){
  const node=ast.instance.content.body.map((n:any)=>n.type==='ExportNamedDeclaration'?n.declaration:n).find((n:any)=>n?.type==='FunctionDeclaration'&&n.id.name===name);
  const code=transpileModule(source.slice(node.start,node.end),{compilerOptions:{target:ScriptTarget.ES2022}}).outputText;
  return (...args:unknown[])=>new Function('ctx','args',`with(ctx){${code};return ${name}(...args);}`)(ctx,args);
}
function context(){
  const saved={id:'saved',signature:'signed',mode:'modify',prompt:'Left hand down',poses:[{personId:1,rigId:'g9'}],expressions:[]};
  return {saved,accepted:saved,actorsFromPoses,actors:[{id:1,rigId:'g9'}],prompt:saved.prompt,busy:false,canVary:true,fingerprint:'current',shown:saved,variationBatch:[],style:'natural',handShapes:false,work:async(_label:string,fn:()=>unknown)=>fn(),request:vi.fn(),runtime:null,onstatus:vi.fn(),interpreted:null,progress:vi.fn(),choices:[],candidate:null,previewFingerprint:'',selected:1,previewMode:'pose',reset:0,notice:'',refresh:vi.fn(),recordCreation:vi.fn(),onexpression:vi.fn()};
}
describe('creation-only Text to Pose',()=>{
  it('restores accepted legacy edits for display without reviving an editing mode',async()=>{
    const ctx=context();ctx.request.mockResolvedValue(ctx.saved);
    await handler('restore',ctx)({id:'saved'});
    expect(ctx.accepted).toBe(ctx.saved);
    expect(ctx.actors).toEqual([{id:1,rigId:'g9'}]);
    expect(ctx.prompt).toBe(ctx.saved.prompt);
    expect(ctx).not.toHaveProperty('mode');
    expect(ctx).not.toHaveProperty('editSource');
  });
  it('creates fresh choices after opening legacy history without sending its body as a baseline',async()=>{
    const ctx=context(),result={id:'new',signature:'new-signed',poses:ctx.saved.poses,intent:{status:'plan'}};
    ctx.request.mockResolvedValueOnce({runtime:{},intent:{status:'plan'},contextSignature:'context'}).mockResolvedValueOnce(result);
    await handler('preview',ctx)();
    for(const [,payload] of ctx.request.mock.calls){
      expect(payload).toMatchObject({mode:'create',output:'pose',bodyGenerator:'kimodo',creative:true,candidateCount:3,style:'natural',handShapes:false});
      expect(payload).not.toHaveProperty('baselines');
    }
    expect(ctx.accepted).toBe(ctx.saved);
    expect(ctx.candidate).toBe(result);
  });
  it('keeps More like this tied to every choice in the preceding batch',async()=>{
    const ctx=context(),choices=[{id:'a',signature:'a-signed'},{id:'b',signature:'b-signed'},{id:'c',signature:'c-signed'}];
    ctx.shown={...ctx.saved,...choices[1],mode:'create'};
    ctx.variationBatch=choices as never[];
    ctx.request.mockResolvedValueOnce({runtime:{},intent:{status:'clarify'}});
    await handler('preview',ctx)(true);
    expect(ctx.request.mock.calls[0][1].variationOf).toEqual({...choices[1],choices});
    expect(ctx.accepted).toBe(ctx.saved);
  });
});
