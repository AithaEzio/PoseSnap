import { describe, expect, it } from 'vitest';
import { engineIndicator, expressionIndicator, workspaceEngineIndicator, setupPlan, type EngineStatus } from './engine';

const installed:EngineStatus={version:1,root:'PoseSnap',phase:'ready',ready:true,runtimeReady:true,active:false,message:'Components and GPU verified.',components:[],transfers:[],gpu:'Fixture GPU'};
describe('engine state shown in the workspace',()=>{
  it('requires verified readiness for the green light',()=>{
    expect(engineIndicator(installed,true).state).toBe('ready');
    expect(engineIndicator({...installed,ready:false},true).state).toBe('attention');
  });
  it('names the active engine while preserving running, missing and preview states',()=>{
    const face={...installed,components:[{id:'expression',state:'installed'}]} as EngineStatus;
    expect(workspaceEngineIndicator('extract',installed,true).label).toBe('Pose Engine Ready');
    expect(workspaceEngineIndicator('editor',installed,true).label).toBe('Pose Retargeter Engine Ready');
    expect(workspaceEngineIndicator('expression',face,true).label).toBe('Expression Engine Ready');
    expect(workspaceEngineIndicator('editor',installed,true,true,'Retargeting').state).toBe('running');
    expect(workspaceEngineIndicator('expression',{...face,runtimeReady:false},true).state).toBe('attention');
    expect(workspaceEngineIndicator('extract',null,false).state).toBe('preview');
  });
  it('shows local work rather than idle readiness during a pose job',()=>{
    expect(engineIndicator(installed,true,true,'Fitting hands')).toEqual({state:'running',label:'Running',detail:'Fitting hands'});
    expect(engineIndicator(installed,true,false).state).toBe('ready');
  });
  it('distinguishes setup work, booting and a failed engine',()=>{
    expect(engineIndicator({...installed,phase:'downloading',active:true,ready:false},true).state).toBe('running');
    expect(engineIndicator({...installed,phase:'verifying',active:true,ready:false},true).state).toBe('running');
    expect(engineIndicator({...installed,phase:'booting',ready:false},true).state).toBe('checking');
    expect(engineIndicator({...installed,phase:'attention',ready:false},true).state).toBe('attention');
    expect(engineIndicator({...installed,phase:'attention',ready:false,active:true},true,true).state).toBe('attention');
  });
  it('does not claim readiness before a check or in a browser preview',()=>{
    expect(engineIndicator(null,true).state).toBe('checking');
    expect(engineIndicator(null,false).label).toBe('UI preview');
  });
  it('qualifies CPU facial readiness separately from GPU and private import/export requirements',()=>{
    const face={...installed,ready:false,phase:'attention' as const,gpu:null,components:[{id:'expression',label:'Expression',version:'1',required:false,state:'installed' as const,locations:[],relativeLocations:[],installedBytes:43e6,downloadBytes:43e6,source:null,downloadSources:[],downloadable:true,message:''}]};
    expect(expressionIndicator(face,true).state).toBe('ready');
    expect(expressionIndicator({...face,runtimeReady:false},true).state).toBe('attention');
    expect(expressionIndicator({...face,active:true},true).state).toBe('checking');
    expect(expressionIndicator({...face,components:[]},true).label).toBe('Face missing');
  });
});
describe('complete installation planning',()=>{
  const ids=['python','body','camera','segmentation','interaction-detector','wholebody','hands','expression','kimodo-encoder','kimodo-motion','kimodo-runtime','clue-body','legacy-detector'];
  const missing={...installed,components:ids.map(id=>({id,label:id,state:'missing',downloadable:true,downloadBytes:10,installedBytes:20,required:false}))} as EngineStatus;
  it('includes dependencies and every mode by default, but no optional diagnostics/fallback',()=>{
    const plan=setupPlan(missing);expect(plan.pending.map(c=>c.id)).toEqual(ids.slice(0,11));expect(plan.unavailable).toEqual([]);expect(plan.downloadBytes).toBe(110);
  });
  it('offers a complete smaller pose/expression setup and excludes installed components',()=>{
    const state={...missing,components:missing.components.map(c=>c.id==='python'?{...c,state:'installed' as const}:c)};
    expect(setupPlan(state,'pose-expression').pending.map(c=>c.id)).toEqual(ids.slice(1,8));
    expect(setupPlan(state,'pose-expression').installedBytes).toBe(140);
  });
  it('does not mistake an unhosted requirement for successful complete setup',()=>{
    const state={...missing,components:missing.components.filter(c=>c.id!=='body').map(c=>c.id==='python'?{...c,downloadable:false}:c)};
    expect(setupPlan(state).unavailable).toEqual(['body','python']);
  });
});

describe('optional guidance setup is explicit',()=>{
  const ids=['python','guidance-shade','guidance-shade-detail','guidance-moge3-model','guidance-moge3-runtime'];
  const engine={...installed,components:ids.map(id=>({id,label:id,state:'missing',downloadable:true,downloadBytes:10,installedBytes:20,required:false}))} as EngineStatus;
  it('installs the image profiles with their Python dependency',()=>{
    expect(setupPlan(engine,'guidance').pending.map(c=>c.id)).toEqual(ids.slice(0,3));
  });
  it('does not include retired trial components in guidance installation',()=>{
    expect(setupPlan(engine,'guidance').pending.map(c=>c.id)).not.toContain('guidance-moge3-model');
    expect(setupPlan(engine,'guidance').pending.map(c=>c.id)).not.toContain('guidance-moge3-runtime');
  });
});
