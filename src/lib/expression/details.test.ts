import {it,expect} from 'vitest';
import {adjustDetail,resetDetail,detailValue,detailStatus,detailGroups,detectedDetailGroups} from './details';
import {defaultOptions,type ExpressionSource} from './types';
const source:ExpressionSource={version:1,engine:'mediapipe-1.1.0-face-v1',imageId:'fixture',face:{id:1,box:[],landmarks:[],matrix:[],actions:{cheekPuff:.6,eyeLookOutLeft:.8,eyeLookInRight:.6,mouthSmileRight:.3},extras:{tongueOut:1}},unknown:[],warnings:[]};
it('overrides an uncertain detail explicitly without altering extraction or other regions',()=>{
  const options=defaultOptions(),next=adjustDetail('cheekPuff',.9,options);
  expect(detailValue('cheekPuff',source,next)).toBe(.9);expect(source.face.actions.cheekPuff).toBe(.6);expect(next.regions.mouth).toBe(true);
  expect(detailValue('cheekPuff',source,resetDetail('cheekPuff',next))).toBe(.6);
});
it('offers all three movements for each eye in detected details and fine tuning',()=>{
  for(const side of ['Left','Right'])for(const stem of ['eyeSquint','eyeBlink','eyeWide']){
    const id=stem+side;
    expect(detailGroups.flatMap(g=>g.sliders.map(s=>s.id))).toContain(id);
    expect(detectedDetailGroups.flatMap(g=>g.items.map(i=>i[0]))).toContain(id);
  }
});
it('resolves manual eyelid conflicts on one eye only and restores its source values',()=>{
  const evidence={...source,face:{...source.face,actions:{eyeSquintLeft:.4,eyeBlinkLeft:.1,eyeWideLeft:.2,eyeBlinkRight:.8}}},before=structuredClone(evidence);
  const right=adjustDetail('eyeBlinkRight',.9,defaultOptions());
  for(const id of ['eyeSquintLeft','eyeBlinkLeft','eyeWideLeft'] as const){
    const edit=adjustDetail(id,.75,right);
    for(const key of ['eyeSquintLeft','eyeBlinkLeft','eyeWideLeft'])expect(detailValue(key,evidence,edit)).toBe(key===id?.75:0);
    expect(detailValue('eyeBlinkRight',evidence,edit)).toBe(.9);
    const reset=resetDetail(id,edit);
    expect(detailValue('eyeSquintLeft',evidence,reset)).toBe(.4);expect(detailValue('eyeBlinkLeft',evidence,reset)).toBe(.1);expect(detailValue('eyeWideLeft',evidence,reset)).toBe(.2);
    expect(detailValue('eyeBlinkRight',evidence,reset)).toBe(.9);
  }
  expect(evidence).toEqual(before);
});
it('uses anatomical gaze signs, zeros opposing controls and restores asymmetric evidence',()=>{
  const next=adjustDetail('horizontal',-.7,defaultOptions());
  expect(next.adjustments).toMatchObject({eyeLookInLeft:.7,eyeLookOutRight:.7,eyeLookOutLeft:0,eyeLookInRight:0});
  expect(detailValue('horizontal',source,next)).toBe(-.7);expect(detailValue('horizontal',source,resetDetail('horizontal',next))).toBeCloseTo(.7);
  expect(adjustDetail('vertical',.4,next).adjustments).toMatchObject({eyeLookUpLeft:.4,eyeLookUpRight:.4,eyeLookDownLeft:0,eyeLookDownRight:0});
});
it('labels edits and unknown evidence separately from transfer readiness',()=>{
  const unknown={...source,unknown:['cheeks' as const]},options=defaultOptions();
  expect(detailStatus('cheekPuff','cheeks',unknown,options)).toEqual({evidence:'Uncertain',transfer:'Connect to transfer'});
  expect(detailStatus('cheekPuff','cheeks',unknown,adjustDetail('cheekPuff',.8,options)).evidence).toBe('Adjusted');
  expect(detailStatus('gaze','gaze',source,options,{mappings:[]} as any).transfer).toBe('Partial support');
  const profile={rigId:'g8f',mappings:[{action:'cheekPuff'}]} as any;
  expect(detailStatus('cheekPuff','cheeks',unknown,options,profile).transfer).toBe('Withheld');
  expect(detailStatus('cheekPuff','cheeks',unknown,adjustDetail('cheekPuff',.8,options),profile).transfer).toBe('Ready to transfer');
  expect(detailStatus('cheekPuff','cheeks',source,{...options,neutralRegions:['cheeks']},profile).transfer).toBe('Region zeroed');
});
