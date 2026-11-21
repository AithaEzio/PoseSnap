import { describe,it,expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { blankPose,copyPoses,figureKey,rotateJoint,snapshot } from './editor';
import { togglePin,clearPins,preservePins,pinErrors } from './pinning';
import { forwardKinematics,previewRotations } from './pose';
import type { Rig,RigId } from './types';
const sample=(id:RigId='g9')=>blankPose(JSON.parse(readFileSync('data/rigs/'+id+'.json','utf8')) as Rig,'test');

describe('bounded world-space joint pins',()=>{
  for(const id of ['g8f','g8m','g9'] as const){
    it('compensates pinned hand position and orientation on '+id,()=>{
      let p=sample(id);const hand=id==='g9'?'l_hand':'lHand',forearm=id==='g9'?'l_forearm':'lForearmBend';
      p=rotateJoint(p,forearm,[0,-30,0]);p=togglePin(togglePin(p,hand,'position'),hand,'rotation');
      const before=JSON.stringify(p.rig),request=rotateJoint(p,figureKey,[0,3,0]);
      const fitted=preservePins(request,figureKey,24),errors=pinErrors(fitted)[0];
      expect(errors.distanceCm).toBeLessThan(.3);expect(errors.angleDegrees).toBeLessThan(2);
      expect(fitted.rootRotation).toEqual(request.rootRotation);expect(JSON.stringify(p.rig)).toBe(before);expect(fitted.rig).toBe(p.rig);
      const a=forwardKinematics(p.rig,previewRotations(p),p.translation),b=forwardKinematics(fitted.rig,previewRotations(fitted),fitted.translation);
      for(const n of p.rig.nodes){
        if(n.parent)expect(a.get(n.id)!.position.distanceTo(a.get(n.parent)!.position)).toBeCloseTo(b.get(n.id)!.position.distanceTo(b.get(n.parent)!.position),7);
        for(let axis=0;axis<3;axis++){const value=fitted.rotations[n.id]?.[axis]??0,limit=n.limits['xyz'[axis]];
          if(limit?.locked||n.driven?.includes('xyz'[axis]))expect(value).toBe(p.rotations[n.id]?.[axis]??0);
          else if(limit?.clamped){expect(value).toBeGreaterThanOrEqual(limit.min-1e-5);expect(value).toBeLessThanOrEqual(limit.max+1e-5);}
        }
      }
    });
  }
  it('holds wrist orientation when its elbow rotates',()=>{
    const p=togglePin(sample(),'l_hand','rotation'),requested=rotateJoint(p,'l_forearm',[10,-20,0]);
    const fitted=preservePins(requested,'l_forearm');expect(fitted.rotations.l_forearm).toEqual(requested.rotations.l_forearm);
    expect(pinErrors(fitted)[0].angleDegrees).toBeLessThan(1);
  });
  it('fits multiple pins together while the figure moves',()=>{
    let p=sample();p=rotateJoint(p,'l_thigh',[10,0,0]);p=rotateJoint(p,'r_thigh',[10,0,0]);p=rotateJoint(p,'l_shin',[25,0,0]);p=rotateJoint(p,'r_shin',[25,0,0]);
    p=togglePin(togglePin(p,'l_foot','position'),'r_foot','position');
    const requested={...p,translation:[.5,0,.5]},fitted=preservePins(requested,figureKey,24);
    expect(fitted.translation).toEqual(requested.translation);for(const error of pinErrors(fitted))expect(error.distanceCm).toBeLessThan(.5);
    expect(fitted.pins).toEqual(p.pins);
  });
  it('keeps unreachable and fully locked pins honest without invalid channels',()=>{
    let p=sample();for(const n of p.rig.nodes)n.driven=['x','y','z'];p=togglePin(p,'l_foot','position');
    const request={...p,translation:[1000,0,0]},fitted=preservePins(request);
    expect(fitted).toBe(request);expect(pinErrors(fitted)[0].distanceCm).toBeCloseTo(1000);
    expect(fitted.rotations).toEqual(p.rotations);
  });
  it('deep-copies targets for undo and clears only the requested subtree',()=>{
    let p=togglePin(togglePin(sample(),'l_hand','position'),'r_foot','rotation');
    const before=snapshot([p],[p],1,'l_hand'),clone=copyPoses([p])[0];clone.pins!.l_hand.position![0]+=20;
    expect(before.poses[0].pins!.l_hand.position).toEqual(p.pins!.l_hand.position);
    const cleared=clearPins(p,'l_upperarm',true);expect(cleared.pins!.l_hand).toBeUndefined();expect(cleared.pins!.r_foot).toEqual(p.pins!.r_foot);
    p=togglePin(p,'l_hand','position');expect(p.pins!.l_hand).toBeUndefined();expect(clearPins(p).pins).toBeUndefined();
  });
});
