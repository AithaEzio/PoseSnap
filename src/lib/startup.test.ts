import {describe,it,expect} from 'vitest';
import {startupState} from './startup';
import type {EngineStatus} from './engine';
const checks={preferences:true,history:true,transport:true,preview:true};
const engine:EngineStatus={version:1,root:'PoseSnap',phase:'verifying',ready:false,runtimeReady:true,active:true,message:'Checking components',components:[],transfers:[],gpu:null,verification:{completed:2,total:9}};
describe('actual startup readiness',()=>{
  it('does not open a completed workspace while verification is unfinished',()=>{
    const state=startupState(engine,true,checks,'Loading history');
    expect(state.complete).toBe(false);expect(state.progress).toBe(43);expect(state.checksLabel).toBe('2/9 components checked');
  });
  it('uses indeterminate progress for GPU boot and older native progress events',()=>{
    expect(startupState({...engine,phase:'booting',active:false,verification:{completed:9,total:9}},true,checks,'Preparing preview').progress).toBeNull();
    expect(startupState({...engine,verification:undefined},true,checks,'Preparing preview').progress).toBeNull();
  });
  it('shows real work within a large component without claiming it is accepted',()=>{
    const base={...engine,verification:{completed:1,total:10,stage:'inventory' as const,filesExamined:10000,filesTotal:20000}};
    const inventory=startupState(base,true,checks,'Loading');
    expect(inventory.checksLabel).toContain('10,000 / 20,000 files inspected');
    const hashing=startupState({...base,verification:{...base.verification,stage:'hashing',bytesRead:4e9,bytesTotal:8e9}},true,checks,'Loading');
    expect(hashing.checksLabel).toContain('4.00 GB / 8.00 GB read for checksums');
    expect(hashing.progress).toBeGreaterThan(inventory.progress!);expect(hashing.complete).toBe(false);
    const read=startupState({...base,verification:{...base.verification,stage:'hashing',bytesRead:8e9,bytesTotal:8e9}},true,checks,'Loading');
    expect(read.progress).toBeLessThan(100);expect(read.checksLabel).toContain('1/10 components checked');
  });
  it('requires both workspace and acknowledged engine readiness for 100 percent',()=>{
    const ready={...engine,phase:'ready' as const,active:false,ready:true,verification:{completed:9,total:9}};
    expect(startupState(ready,true,{...checks,preview:false},'Preparing mannequin').complete).toBe(false);
    expect(startupState(ready,true,checks,'Preparing mannequin').progress).toBe(100);
    expect(startupState(ready,true,checks,'Preparing mannequin').complete).toBe(true);
  });
  it('makes recovery reachable without claiming a missing engine is ready',()=>{
    const state=startupState({...engine,phase:'attention',active:false},true,checks,'Preparing mannequin');
    expect(state.complete).toBe(true);expect(state.attention).toBe(true);expect(state.engineReady).toBe(false);expect(state.progress).toBeNull();
  });
  it('labels a browser workspace without claiming GPU readiness',()=>{
    const state=startupState(null,false,checks,'Preparing mannequin');
    expect(state.label).toBe('Development workspace ready');expect(state.engineLabel).toBe('UI preview');expect(state.engineReady).toBe(false);
  });
});
