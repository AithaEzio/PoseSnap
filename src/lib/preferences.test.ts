import { describe,it,expect } from 'vitest';
import { validatedPreferences } from './preferences';
describe('first-frame portable preferences',()=>{
  it('keeps every saved theme and motion preference before asynchronous startup',()=>{
    for(const theme of ['dark','neon','light'])expect(validatedPreferences({theme,motion:'reduced',extractionMethod:'pure'})).toEqual({theme,motion:'reduced',extractionMethod:'pure',clueEnabled:false,zeroCroppedJoints:true,imageGuidance:'auto',depthInputType:'relative'});
  });
  it('rejects malformed settings and preserves the Auto default without changing manual choices',()=>{
    for(const value of [null,42,{theme:'<script>',motion:'fast',extractionMethod:'standard'}])expect(validatedPreferences(value)).toEqual({theme:'dark',motion:'auto',extractionMethod:'auto',clueEnabled:false,zeroCroppedJoints:true,imageGuidance:'auto',depthInputType:'relative'});
  });
  it('restores an explicit CLUE on/off choice and defaults to Off for old or missing settings',()=>{
    for(const clueEnabled of [true,false])expect(validatedPreferences({clueEnabled}).clueEnabled).toBe(clueEnabled);
    for(const clueEnabled of [null,0,'off'])expect(validatedPreferences({clueEnabled}).clueEnabled).toBe(false);
  });
  it('defaults crop zeroing to On and preserves an explicit Off without coercion',()=>{
    expect(validatedPreferences({}).zeroCroppedJoints).toBe(true);
    for(const zeroCroppedJoints of [true,false])expect(validatedPreferences({zeroCroppedJoints}).zeroCroppedJoints).toBe(zeroCroppedJoints);
    for(const zeroCroppedJoints of [null,0,'off'])expect(validatedPreferences({zeroCroppedJoints}).zeroCroppedJoints).toBe(true);
  });
});


describe('depth import defaults',()=>{
  it('defaults to relative and validates the saved type',()=>{
    expect(validatedPreferences({}).depthInputType).toBe('relative');
    expect(validatedPreferences({depthInputType:'metric'}).depthInputType).toBe('metric');
    for(const depthInputType of [true,1,'camera-z',null])expect(validatedPreferences({depthInputType}).depthInputType).toBe('relative');
  });
});

describe('retired geometry preference migration',()=>{
  it('uses MoGe-2 for new work without modifying the saved input',()=>{
    const saved={geometryEngine:'moge3',imageGuidance:'detailed'};
    expect(validatedPreferences(saved)).not.toHaveProperty('geometryEngine');
    expect(validatedPreferences(saved).imageGuidance).toBe('auto');
    expect(saved.imageGuidance).toBe('detailed');
    expect(saved.geometryEngine).toBe('moge3');
  });
});
