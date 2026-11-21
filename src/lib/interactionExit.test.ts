import { describe,it,expect,vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { createContext,runInContext } from 'node:vm';
import { parse } from 'svelte/compiler';
import { transpileModule,ScriptTarget } from 'typescript';
import { individualAfterInteraction,methodLabel } from './extraction';
import type { Pose,ExtractionPreference } from './types';

// Exercise App.svelte's actual transition, including its commit/rollback state.
// This isolates the handler from WebGL and Tauri, without duplicating its code.
const source=readFileSync(new URL('../App.svelte',import.meta.url),'utf8');
const ast=parse(source,{modern:true});
const handler=ast.instance!.content.body.find(node=>node.type==='FunctionDeclaration'&&node.id?.name==='exitInteraction') as {start:number;end:number}|undefined;
if(!handler)throw new Error('App interaction Exit handler was not found.');
const code=transpileModule(source.slice(handler.start,handler.end),{compilerOptions:{target:ScriptTarget.ES2022}}).outputText;
const solo=(method:'pure'|'smart'):Pose=>({imageId:'hug',personId:2,rigId:'g9',extractionMethod:method,rootRotation:[2,3,4],translation:[5,6,7]} as Pose);
function setup(preference:ExtractionPreference='auto'){
  const context=createContext({api:{desktop:true},busy:false,pendingRefinement:null,photo:{id:'hug'},selected:2,rig:'g9',connected:true,
    extractionMethod:preference,editRevision:7,individualAfterInteraction,methodLabel,
    interaction:{id:'hug-layout'},pose:{...solo('smart'),layout:{reference:true}},lastRefinement:{id:'refined'},
    editPoses:[solo('smart'),{...solo('smart'),personId:1}],
    qualityOpen:true,sourceAvailable:true,placement:'reference',notesOpen:true,reset:0,notice:'',error:'',
    clearEdits:vi.fn(),job:vi.fn<(...args:unknown[])=>Promise<Pose|null>>(async()=>solo(preference==='auto'?'pure':preference))});
  context.clearEdits.mockImplementation(()=>{context.editPoses=[];context.editRevision++;});
  runInContext(code,context);
  return context;
}

describe('App interaction Exit transaction',()=>{
  it('switches the actual pose and footer provenance to Pure while keeping Auto selected',async()=>{
    const c=setup();await c.exitInteraction();
    expect(c.job).toHaveBeenCalledWith('solve',{imageId:'hug',personId:2,rigId:'g9',extractionMethod:'pure',refinement:'accurate',refresh:false});
    expect(c.extractionMethod).toBe('auto');expect(c.pose.extractionMethod).toBe('pure');expect(c.interaction).toBeNull();
    expect(c.editPoses).toEqual([]);expect(c.lastRefinement).toBeNull();
    expect(c.placement).toBe('keep');expect(c.pose.rootRotation).toEqual([2,3,4]);expect(c.pose.translation).toEqual([5,6,7]);
    expect(c.qualityOpen).toBe(false);expect(c.notesOpen).toBe(false);expect(c.sourceAvailable).toBe(true);expect(c.reset).toBe(1);
  });
  it.each(['pure','smart'] as const)('keeps explicit %s selection through the actual handler',async method=>{
    const c=setup(method);await c.exitInteraction();expect(c.extractionMethod).toBe(method);expect(c.pose.extractionMethod).toBe(method);expect(c.interaction).toBeNull();
  });
  it('keeps the current interaction visible until the individual worker request succeeds',async()=>{
    const c=setup();let finish!:(p:Pose)=>void;c.job.mockImplementation(()=>new Promise(resolve=>finish=resolve));
    const pending=c.exitInteraction();expect(c.interaction.id).toBe('hug-layout');expect(c.clearEdits).not.toHaveBeenCalled();
    finish(solo('pure'));await pending;expect(c.interaction).toBeNull();
  });
  it('retains the coordinated pose, placement, edits and measurements after cancellation',async()=>{
    const c=setup();c.job.mockResolvedValue(null);await c.exitInteraction();
    expect(c.interaction.id).toBe('hug-layout');expect(c.pose.extractionMethod).toBe('smart');expect(c.placement).toBe('reference');
    expect(c.editPoses).toHaveLength(2);expect(c.qualityOpen).toBe(true);expect(c.clearEdits).not.toHaveBeenCalled();
  });
  it('reports a worker failure without clearing the accepted interaction',async()=>{
    const c=setup();c.job.mockRejectedValue(Error('Pure component unavailable'));await c.exitInteraction();
    expect(c.error).toContain('Pure component unavailable');expect(c.interaction.id).toBe('hug-layout');expect(c.clearEdits).not.toHaveBeenCalled();
  });
  it('ignores a completed request after switching the reference image',async()=>{
    const c=setup();c.job.mockImplementation(async()=>{c.photo={id:'another'};return solo('pure');});await c.exitInteraction();
    expect(c.pose.extractionMethod).toBe('smart');expect(c.clearEdits).not.toHaveBeenCalled();
  });
  it('does not start during a refinement preview or engine job',async()=>{
    const c=setup();c.busy=true;await c.exitInteraction();expect(c.job).not.toHaveBeenCalled();
    c.busy=false;c.pendingRefinement={previewId:'review'};await c.exitInteraction();expect(c.job).not.toHaveBeenCalled();
  });
});
