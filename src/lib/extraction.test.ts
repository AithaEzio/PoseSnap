import { describe,it,expect,vi } from 'vitest';
import { extractionFor, individualAfterInteraction } from './extraction';
import type { ExtractionMethod, Pose } from './types';
describe('Auto extraction policy',()=>{
  it('resolves the operation rather than the detected person count',()=>{
    expect(extractionFor('auto')).toBe('pure');
    expect(extractionFor('auto',true)).toBe('smart');
  });
  it('preserves explicit overrides for either operation',()=>{
    for(const interaction of [false,true]){expect(extractionFor('pure',interaction)).toBe('pure');expect(extractionFor('smart',interaction)).toBe('smart');}
  });
});

describe('Returning from interaction to individual extraction',()=>{
  const selection={imageId:'hug',personId:2,rigId:'g9' as const};
  const pose=(method:ExtractionMethod):Pose=>({...selection,extractionMethod:method} as Pose);
  it('requests the Pure cache/solve in Auto, independent of the Smart interaction result',async()=>{
    const interactionPose={...pose('smart'),layout:{reference:true}};
    const solve=vi.fn<Parameters<typeof individualAfterInteraction>[2]>(async()=>pose('pure'));
    const result=await individualAfterInteraction(selection,'auto',solve,()=>true);
    expect(solve).toHaveBeenCalledExactlyOnceWith({...selection,extractionMethod:'pure',refinement:'accurate',refresh:false});
    expect(result?.extractionMethod).toBe('pure');expect(result?.layout).toBeUndefined();
    expect(interactionPose.extractionMethod).toBe('smart');expect(interactionPose.layout.reference).toBe(true);
  });
  it.each(['pure','smart'] as const)('respects an explicit %s preference on Exit',async method=>{
    const solve=vi.fn<Parameters<typeof individualAfterInteraction>[2]>(async()=>pose(method));
    expect(await individualAfterInteraction(selection,method,solve,()=>true)).toEqual(pose(method));
    expect(solve.mock.calls[0][0]).toMatchObject({extractionMethod:method,refresh:false});
  });
  it('does not replace the interaction when the task fails or is cancelled',async()=>{
    expect(await individualAfterInteraction(selection,'auto',async()=>null,()=>true)).toBeNull();
    await expect(individualAfterInteraction(selection,'auto',async()=>{throw Error('worker stopped');},()=>true)).rejects.toThrow('worker stopped');
  });
  it('discards a completed response after image, selection, preference or edit state changes',async()=>{
    let current=true,finish!:(result:Pose)=>void;
    const pending=individualAfterInteraction(selection,'auto',()=>new Promise(resolve=>finish=resolve),()=>current);
    current=false;finish(pose('pure'));expect(await pending).toBeNull();
  });
  it.each([
    {extractionMethod:'smart'}, {imageId:'other'}, {personId:1}, {rigId:'g8f'}, {layout:{reference:true}}
  ])('rejects a mismatched or still coordinated worker response: %j',async patch=>{
    await expect(individualAfterInteraction(selection,'auto',async()=>({...pose('pure'),...patch} as Pose),()=>true)).rejects.toThrow('Your interaction is kept');
  });
});
