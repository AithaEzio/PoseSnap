import { describe,it,expect } from 'vitest';
import { blankPose } from './editor';
import { neutralRig } from './pose';
import { jointSearchGroups,chooserGroup,jointSection } from './jointSearch';
import type { RigNode } from './types';

const pose=()=>blankPose(neutralRig(),'search');
describe('joint search',()=>{
  it('follows a new anatomical selection without changing the rig or whole-figure browsing group',()=>{
    const p=pose(),before=JSON.stringify(p);
    expect(chooserGroup(p,'rShin','arms')).toBe('legs');
    expect(chooserGroup(p,'lShldrBend','legs')).toBe('arms');
    expect(chooserGroup(p,'lHand','legs')).toBe('hands');
    expect(chooserGroup(p,'hip','hands')).toBe('body');
    expect(chooserGroup(p,'$figure','arms')).toBe('arms');
    expect(JSON.stringify(p)).toBe(before);
  });
  it('handles G9 and correct left/right finger maps through attachment ancestry',()=>{
    const p=pose(),template=p.rig.nodes.find(n=>n.id==='lHand')!;
    p.rig.nodes.push({...template,id:'r_hand',parent:'hip'},{...template,id:'r_thumb1',parent:'r_hand'},{...template,id:'attachment',parent:'r_thumb1'},{...template,id:'l_thigh',parent:'hip'});
    expect(jointSection(p,'attachment')).toBe('r-hand');
    expect(chooserGroup(p,'attachment','arms')).toBe('hands');
    expect(chooserGroup(p,'l_thigh','hands')).toBe('legs');
  });
  it('finds fingers by body group and multiple words rather than raw bone names',()=>{
    const groups=jointSearchGroups(pose(),'left finger');
    expect(groups.map(g=>g.id)).toEqual(['l-hand']);
    expect(groups[0].nodes.some(n=>/thumb/i.test(n.id))).toBe(true);
    expect(jointSearchGroups(pose(),'right shoulder').every(g=>g.id==='r-arm')).toBe(true);
    expect(jointSearchGroups(pose(),'left wrist')[0].nodes.map(n=>n.id)).toEqual(['lHand']);
    expect(jointSearchGroups(pose(),'right ankle')[0].nodes.map(n=>n.id)).toEqual(['rFoot']);
  });
  it('groups Genesis 9 aliases and descendant attachments without altering the rig',()=>{
    const p=pose(),template=p.rig.nodes.find(n=>n.id==='lHand')!;
    p.rig={...p.rig,nodes:[...p.rig.nodes,{...template,id:'r_upperarm',parent:'hip'},{...template,id:'l_hand',parent:'hip'},{...template,id:'l_thumb1',parent:'l_hand'},{...template,id:'digitAttachment',parent:'l_thumb1'},{...template,id:'r_metatarsal',parent:'hip'}]};
    const before=JSON.stringify(p.rig),groups=jointSearchGroups(p);
    expect(groups.find(g=>g.id==='l-hand')?.nodes.map(n=>n.id)).toContain('digitAttachment');
    expect(groups.find(g=>g.id==='r-arm')?.nodes.map(n=>n.id)).toContain('r_upperarm');
    expect(groups.find(g=>g.id==='r-leg')?.nodes.map(n=>n.id)).toContain('r_metatarsal');
    expect(JSON.stringify(p.rig)).toBe(before);
  });
  it('filters categories, excludes locked joints and handles no matches',()=>{
    const p=pose(),n=p.rig.nodes.find(n=>n.id==='lHand')!;
    p.rig={...p.rig,nodes:p.rig.nodes.map(node=>node.id===n.id?{...node,limits:Object.fromEntries(['x','y','z'].map(axis=>[axis,{min:0,max:0,clamped:true,locked:true}]))} as RigNode:node)};
    expect(jointSearchGroups(p,'','hands').every(g=>g.category==='hands')).toBe(true);
    expect(jointSearchGroups(p).flatMap(g=>g.nodes).some(node=>node.id===n.id)).toBe(false);
    expect(jointSearchGroups(p,'no such joint')).toEqual([]);
  });
});
