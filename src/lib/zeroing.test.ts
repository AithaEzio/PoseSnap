import { describe,expect,it } from 'vitest';
import { evaluatedChannels,neutralRig,previewRotations,forwardKinematics } from './pose';
import { blankPose,copyPoses,figureKey,snapshot,zeroSelection } from './editor';

function posed(){
  const pose=blankPose(neutralRig(),'zero-test');
  for(const id of Object.keys(pose.rotations))pose.rotations[id]=[12,8,4];
  pose.translation=[30,14,-22];pose.rootRotation=[9,18,27];return pose;
}

describe('Pose studio zeroing',()=>{
  it('keeps passive and facial values in old all-bone drafts when zeroing the body subtree',()=>{
    const pose=posed(),template=pose.rig.nodes.find(n=>n.id==='lHand')!;
    for(const id of ['l_pectoral','rPectoral','l_eye','lowerjaw']){pose.rig.nodes.push({...template,id,parent:'hip'});pose.rotations[id]=[4,5,6];}
    const next=zeroSelection(pose,figureKey,true);
    for(const id of ['l_pectoral','rPectoral','l_eye','lowerjaw'])expect(next.rotations[id]).toEqual([4,5,6]);
    expect(next.rotations.lHand).toEqual([0,0,0]);
  });
  it('zeros only the selected hand channels, preserving parent and finger channels',()=>{
    const pose=posed(),before=JSON.stringify(pose),next=zeroSelection(pose,'lHand');
    expect(next.rotations.lHand).toEqual([0,0,0]);
    for(const id of Object.keys(pose.rotations))if(id!=='lHand')expect(next.rotations[id]).toEqual(pose.rotations[id]);
    expect(next.translation).toEqual(pose.translation);expect(next.rootRotation).toEqual(pose.rootRotation);
    expect(next.rig).toBe(pose.rig);expect(next.edited).toBe(true);expect(JSON.stringify(pose)).toBe(before);
  });
  for(const generation of ['g8','g9'])it('zeros the complete '+generation+' hand subtree using hierarchy, not name prefixes',()=>{
    const pose=posed();
    if(generation==='g9'){
      const rename=(id:string)=>id==='lHand'?'l_hand':id==='lIndex1'?'left_digit':id;
      pose.rig.nodes=pose.rig.nodes.map(n=>({...n,id:rename(n.id),parent:n.parent?rename(n.parent):null}));
      pose.rotations=Object.fromEntries(Object.entries(pose.rotations).map(([id,v])=>[rename(id),v]));
    }
    // Reverse the node order: descendants need not follow their parent in the file.
    pose.rig.nodes.reverse();
    const selected=generation==='g9'?'l_hand':'lHand',next=zeroSelection(pose,selected,true);
    const subtree=new Set([selected]);let changed=true;
    while(changed){changed=false;for(const n of pose.rig.nodes)if(n.parent&&subtree.has(n.parent)&&!subtree.has(n.id)){subtree.add(n.id);changed=true;}}
    expect(subtree.size).toBeGreaterThan(10);
    for(const id of Object.keys(pose.rotations))expect(next.rotations[id]).toEqual(subtree.has(id)?[0,0,0]:pose.rotations[id]);
    expect(next.rotations.rHand).toEqual(pose.rotations.rHand);
  });
  it('retains locks and driven values and uses the nearest valid value when zero is outside a limit',()=>{
    const pose=posed(),node=pose.rig.nodes.find(n=>n.id==='lHand')!;
    node.limits={x:{min:5,max:30,clamped:true},y:{min:-90,max:90,clamped:true,locked:true}};node.driven=['z'];
    const next=zeroSelection(pose,'lHand');expect(next.rotations.lHand).toEqual([5,8,4]);
    expect(zeroSelection(next,'lHand')).toBe(next);
  });
  it('lets DAZ driving relationships evaluate after zeroing without rewriting the rig',()=>{
    const pose=posed(),driver=pose.rig.nodes.find(n=>n.id==='lIndex1')!;
    driver.driven=['x'];pose.rotations.lIndex1=[0,8,4];
    pose.rig.formulas=[{output:'#lIndex1?rotation/x',stage:'sum',operations:[{op:'push',url:'#lHand?rotation/x'}]}];
    expect(evaluatedChannels(pose.rig,pose.rotations).lIndex1[0]).toBe(12);
    const next=zeroSelection(pose,'lHand',true);expect(next.rotations.lIndex1).toEqual([0,0,0]);
    expect(evaluatedChannels(next.rig,next.rotations).lIndex1[0]).toBe(0);expect(next.rig).toBe(pose.rig);
    expect(forwardKinematics(next.rig,previewRotations(next),next.translation).get('lHand')!.position.toArray().every(Number.isFinite)).toBe(true);
  });
  it('zeros figure orientation separately from its bones, and never changes scene placement',()=>{
    const pose=posed(),only=zeroSelection(pose,figureKey),all=zeroSelection(pose,figureKey,true);
    expect(only.rootRotation).toEqual([0,0,0]);expect(only.rotations).toBe(pose.rotations);
    expect(all.rootRotation).toEqual([0,0,0]);expect(Object.values(all.rotations).every(v=>v.every(a=>a===0))).toBe(true);
    expect(all.translation).toEqual([30,14,-22]);expect(all.rig).toBe(pose.rig);
  });
  it('keeps one complete undo snapshot, the edit baseline and every partner intact',()=>{
    const a=posed(),b={...posed(),personId:2},baseline=copyPoses([a,b]),undo=snapshot([a,b],baseline,1,'lHand');
    const next=[a,b].map(p=>p.personId===1?zeroSelection(p,'lHand',true):p);
    expect(next[1]).toBe(b);expect(undo.poses[0].rotations.lHand).toEqual([12,8,4]);
    expect(undo.baseline).toEqual(baseline);expect(next[0].rotations.lIndex1).toEqual([0,0,0]);
    expect(copyPoses(undo.poses)).toEqual([a,b]);expect(zeroSelection(a,'missing',true)).toBe(a);
  });
});
