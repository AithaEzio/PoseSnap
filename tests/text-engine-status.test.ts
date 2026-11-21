import {describe,it,expect} from 'vitest';
import {textIndicator} from '../src/lib/text/types';
import type {EngineStatus} from '../src/lib/engine';
const engine={phase:'attention',active:false,runtimeReady:false} as EngineStatus;
describe('Text engine runtime prerequisite',()=>{
  it('reports a known missing runtime instead of checking forever',()=>{
    expect(textIndicator(null,false,'',true,engine)).toMatchObject({state:'attention',label:'Local AI Engine Needs attention'});
  });
  it('retains loading, desktop-preview and active verification states',()=>{
    expect(textIndicator(null,true,'Loading Kimodo',true,engine).state).toBe('checking');
    expect(textIndicator(null,false,'',false,engine).state).toBe('preview');
    expect(textIndicator(null,false,'',true,{...engine,active:true}).state).toBe('checking');
  });
});
