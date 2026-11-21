import {describe,it,expect} from 'vitest';
import {textSettings,defaults,textIndicator,kimodoIndicator,actorsFromPoses,canVaryPreview,type TextResult,type KimodoRuntime} from './types';
import type {Pose} from '../types';
describe('Kimodo-only preferences and health',()=>{
  it('migrates to approximate hand shapes without importing retired model settings',()=>{
    expect(textSettings({theme:'light'})).toEqual(defaults);
    expect(textSettings({textHandShapes:false})).toEqual({textHandShapes:false});
    expect(textSettings()).toEqual({textHandShapes:false});
    expect(textSettings({textHandShapes:true})).toEqual({textHandShapes:true});
    expect(textSettings({textVision:true,textPack:'old'} as unknown as Parameters<typeof textSettings>[0])).toEqual(defaults);
  });
  const engine:KimodoRuntime={version:1,ready:false,phase:'unloaded',error:'',encoderReady:false,motionReady:false,installed:{},experimental:true,idleSeconds:120,cacheBytes:0};
  it('marks readiness only after helpers are loaded and retains existing state colors',()=>{
    expect(textIndicator(null,false,'',true).state).toBe('checking');
    expect(kimodoIndicator(engine,false,'',true).state).toBe('idle');
    expect(kimodoIndicator({...engine,ready:true,phase:'ready'},false,'',true)).toMatchObject({state:'ready',label:'Local AI Engine Ready'});
    expect(kimodoIndicator({...engine,phase:'missing'},false,'',true).label).toBe('Local AI Engine Not installed');
    expect(kimodoIndicator({...engine,phase:'attention',error:'Bad checksum'},false,'',true)).toMatchObject({state:'attention',detail:'Bad checksum'});
    for(const stage of ['Loading Kimodo','Verifying Kimodo','Unloading Kimodo'])expect(kimodoIndicator(engine,true,stage,true).state).toBe('checking');
    expect(kimodoIndicator(engine,true,'Fitting Person 1',true).state).toBe('running');
  });
});
describe('body preview ownership and variations',()=>{
  const first={personId:1,label:'Accepted first'} as Pose,second={personId:2,label:'Accepted second'} as Pose;
  const result={poses:[second,first],expressions:[]} as unknown as TextResult;
  it('restores numbered actors and their captured generations without edit baselines',()=>{
    expect(actorsFromPoses([{personId:7,rigId:'g9'} as Pose])).toEqual([{id:1,rigId:'g9'}]);
  });
  it('offers more choices from an accepted creation only while its direction and options still match',()=>{
    const source={...result,output:'pose',mode:'create',prompt:'A relaxed standing pose',generation:{style:'natural',handShapes:false},poses:[{...first,rigId:'g8f'}]} as TextResult;
    const actors=[{id:1,rigId:'g8f' as const}];
    expect(canVaryPreview(actors,source,source.prompt,'natural',false)).toBe(true);
    expect(canVaryPreview(actors,{...source,mode:'modify'},source.prompt,'natural',false)).toBe(false);
    expect(canVaryPreview(actors,source,'Raise the left hand','natural',false)).toBe(false);
    expect(canVaryPreview(actors,source,source.prompt,'happy',false)).toBe(false);
    expect(canVaryPreview(actors,source,source.prompt,'natural',true)).toBe(false);
    expect(canVaryPreview([{id:1,rigId:'g9'}],source,source.prompt,'natural',false)).toBe(false);
  });
});
