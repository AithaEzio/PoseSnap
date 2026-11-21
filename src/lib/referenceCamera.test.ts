import {describe,it,expect} from 'vitest';
import {Vector3} from 'three';
import {referenceFrame,referenceProjection} from './referenceCamera';
import {orientedPose,orientInteraction,neutralRig} from './pose';
import type {Pose,ReferenceCamera} from './types';
const camera:ReferenceCamera={version:1,intrinsics:[[1000,0,530],[0,900,410],[0,0,1]],imageSize:[1200,900],originCm:[20,5,-300]};
describe('retained image camera',()=>{
  it('matches off-centre image intrinsics in the Three.js projection',()=>{
    const point=new Vector3(.05,.2,-4).applyMatrix4(referenceProjection(camera));
    expect((point.x+1)*1200/2).toBeCloseTo(542.5,8);
    expect((1-point.y)*900/2).toBeCloseTo(365,8);
  });
  it('letterboxes without stretching image measurements',()=>{
    const frame=referenceFrame(camera,1440,810);expect(frame.width).toBe(1080);expect(frame.x).toBe(180);expect(frame.height).toBe(810);
  });
  it('keeps accepted placement and root orientation until explicitly adjusted',()=>{
    const pose:Pose={version:1,rigId:'g9',label:'Test',imageId:'a',personId:1,sourceId:'a',rig:neutralRig(),rotations:{},translation:[12,3,-5],rootRotation:[5,12,-8],referenceCamera:camera,warnings:[],handRefinement:true};
    const single=orientedPose(pose,[0,0,0],0),group=orientInteraction([pose],[0,0,0],0)[0];
    expect(single.rootRotation).toEqual(pose.rootRotation);expect(single.translation).toEqual(pose.translation);expect(group.translation).toEqual(pose.translation);expect(group.referenceCamera).toEqual(camera);
    expect(orientedPose(pose,[0,90,0],0).referenceCamera).toBeUndefined();
  });
  it('does not silently ground an airborne pose when changing orientation',()=>{
    const pose:Pose={version:1,rigId:'g9',label:'Jump',imageId:'a',personId:1,sourceId:'a',rig:neutralRig(),rotations:{},translation:[0,40,0],footSupport:[{side:'l',state:'air'},{side:'r',state:'air'}],warnings:[],handRefinement:true};
    expect(orientedPose(pose,[0,90,0],0).translation[1]).toBe(40);
    expect(orientInteraction([pose],[0,90,0],0)[0].translation[1]).toBe(40);
  });
});
