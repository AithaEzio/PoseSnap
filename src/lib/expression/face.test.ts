import { describe,it,expect } from 'vitest';
import { actionRegion,shownActions,sourceFromFace } from './face';
import { defaultOptions,type Face } from './types';
const face=(yaw=0):Face=>({id:2,box:[10,20,160,200],actions:{eyeBlinkLeft:.8,mouthSmileRight:.4,eyeLookOutLeft:.2,browInnerUp:.2},landmarks:[],matrix:[1,0,0,0,0,1,0,0,Math.sin(yaw*Math.PI/180),0,Math.cos(yaw*Math.PI/180),0,0,0,0,1]});
describe('Expression source interpretation',()=>{
  it('preserves anatomical asymmetry and includes estimated gaze by default',()=>{const source=sourceFromFace('image',face());const actions=shownActions(source,defaultOptions());expect(actions.eyeBlinkLeft).toBe(.8);expect(actions.mouthSmileRight).toBe(.4);expect(actions.eyeLookOutLeft).toBe(.2);});
  it('omits unknown/disabled regions rather than treating them as neutral evidence',()=>{const source=sourceFromFace('image',face());source.unknown=['eyes'];const options=defaultOptions();options.regions.mouth=false;expect(shownActions(source,options)).toMatchObject({eyeBlinkLeft:0,mouthSmileRight:0,browInnerUp:.2});});
  it('supports reversible neutral comparison and bounded exaggeration',()=>{const source=sourceFromFace('image',face());const options=defaultOptions();options.strength=1.5;expect(shownActions(source,options).eyeBlinkLeft).toBeCloseTo(1.2);expect(shownActions(source,options,true)).toEqual({});expect(source.face.actions.eyeBlinkLeft).toBe(.8);});
  it('exposes extreme-view uncertainty without calling coefficients confidence',()=>{const source=sourceFromFace('image',face(85));expect(source.unknown).toContain('eyes');expect(source.warnings.join(' ')).toContain('outside');});
  it('classifies the independent facial regions',()=>{expect(['eyeWideRight','eyeLookDownLeft','browDownLeft','noseSneerRight','mouthRollUpper'].map(actionRegion)).toEqual(['eyes','gaze','brows','cheeks','mouth']);});
  it('keeps supplemental estimates labeled and applies the mouth region to tongue',()=>{const f=face();f.extras={tongueOut:.8};f.actions.cheekPuff=.6;f.evidence={passes:2,consistency:{},supplemental:{cheekPuff:{value:.6,agreement:.9,method:'geometry-v1'}}};const source=sourceFromFace('image',f),options=defaultOptions();expect(shownActions(source,options).tongueOut).toBe(.8);expect(source.warnings.join(' ')).toContain('Tongue shape and depth');expect(source.warnings.join(' ')).toContain('Natural face shape');options.neutralRegions=['mouth'];expect(shownActions(source,options).tongueOut).toBe(0);});
  it('does not label rejected supplemental puff evidence as an applied estimate',()=>{
    const f=face();f.evidence={passes:2,consistency:{},supplemental:{cheekPuff:{value:.3,agreement:.5,accepted:false,method:'geometry-v1'}}};
    expect(sourceFromFace('image',f).warnings.join(' ')).not.toContain('Cheek puff estimated');
    f.evidence.supplemental!.cheekPuff!.accepted=true;
    expect(sourceFromFace('image',f).warnings.join(' ')).toContain('Cheek puff estimated');
  });
});
