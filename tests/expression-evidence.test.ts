import { describe,it,expect } from 'vitest';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
const context:any={};vm.runInNewContext(readFileSync('public/expression-evidence.js','utf8'),context);const evidence=context.FaceEvidence;
describe('facial ownership and mirrored checks',()=>{
  it('retains the weaker puff when both views are strong despite different saturation',()=>{
    // Recorded browser evidence from the supplied first portrait. The previous
    // agreement-only gate discarded both measurements at 0.6406 agreement.
    const puff=evidence.pairedDetail('cheekPuff',.9748236870492945,.6153995057150661);
    expect(puff.accepted).toBe(true);expect(puff.value).toBeCloseTo(.6153995057150661);expect(puff.agreement).toBeLessThan(.65);
    expect(evidence.pairedDetail('cheekPuff',.6153995057150661,.9748236870492945)).toEqual(puff);
  });
  it('rejects a one-sided puff estimate and preserves stricter tongue evidence',()=>{
    for(const [a,b] of [[.98,.08],[.04,.05],[.7,.19]])expect(evidence.pairedDetail('cheekPuff',a,b).accepted).toBe(false);
    expect(evidence.pairedDetail('cheekPuff',.3,.35).accepted).toBe(true);
    expect(evidence.pairedDetail('tongueOut',.98,.4).accepted).toBe(false);
    expect(evidence.pairedDetail('tongueOut',.8,.85).accepted).toBe(true);
  });
  it('remaps subject left/right without destroying asymmetry',()=>{expect(evidence.unflip({eyeBlinkLeft:.9,eyeBlinkRight:.1,jawLeft:.8,browInnerUp:.3})).toEqual({eyeBlinkRight:.9,eyeBlinkLeft:.1,jawRight:.8,browInnerUp:.3});});
  it('keeps consistent asymmetry distinct from disagreement',()=>{const original={eyeBlinkLeft:.9,eyeBlinkRight:.1};expect(evidence.disagreement(original,evidence.unflip({eyeBlinkLeft:.1,eyeBlinkRight:.9})).eyes).toBe(0);expect(evidence.disagreement(original,{eyeBlinkLeft:.1,eyeBlinkRight:.9}).eyes).toBeCloseTo(.8);});
  it('rejects distant or equally likely partners instead of swapping faces',()=>{expect(()=>evidence.selected([{box:[0,0,50,50]}],768)).toThrow('ambiguously');expect(()=>evidence.selected([{box:[300,250,500,550]},{box:[310,260,490,540]}],768)).toThrow('ambiguously');const wanted={box:[250,200,520,560]};expect(evidence.selected([wanted,{box:[0,100,120,240]}],768)).toEqual(wanted);});
  it('bounds multi-scale work and covers all borders without resizing the source pixels',()=>{
    for(const [w,h] of [[1675,1694],[8000,5000],[3000,500]]){const windows=evidence.windows(w,h);expect(windows.length).toBeLessThanOrEqual(17);expect(windows[0]).toMatchObject({x:0,y:0,width:w,height:h});for(const r of windows){expect(r.x).toBeGreaterThanOrEqual(0);expect(r.y).toBeGreaterThanOrEqual(0);expect(r.x+r.width).toBeLessThanOrEqual(w+.001);expect(r.y+r.height).toBeLessThanOrEqual(h+.001);}expect(windows.some((r:any)=>Math.abs(r.x+r.width-w)<.001&&Math.abs(r.y+r.height-h)<.001)).toBe(true);}
  });
  it('keeps a nine-portrait collage distinct while removing overlapping tile duplicates',()=>{
    const faces=Array.from({length:9},(_,i)=>({box:[i%3*400,Math.floor(i/3)*400,i%3*400+180,Math.floor(i/3)*400+220],landmarks:[],resolution:1}));
    const result=evidence.merge([...faces.reverse(),{...faces[0],box:faces[0].box.map((v:number)=>v+8)}]);expect(result).toHaveLength(9);expect(result.map((v:any)=>v.id)).toEqual([1,2,3,4,5,6,7,8,9]);expect(result[0].box[0]).toBe(0);expect(result[8].box[1]).toBe(800);
  });
  it('restores rolled pixels and head orientation to the original image frame',()=>{
    const face={box:[100,100,300,300],landmarks:[[200,100,10]],matrix:[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]};
    const result=evidence.restore(face,{x:100,y:200,width:400,height:400},400,Math.PI/2);expect(result.landmarks[0][0]).toBeCloseTo(400);expect(result.landmarks[0][1]).toBeCloseTo(400);expect(result.matrix[0]).toBeCloseTo(0);expect(result.matrix[1]).toBeCloseTo(-1);expect(face.matrix[0]).toBe(1);
  });
});
