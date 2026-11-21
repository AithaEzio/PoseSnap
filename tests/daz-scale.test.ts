import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

// Execute the production DAZ script, including its readback and undo paths.
const template = readFileSync('worker/daz.py', 'utf8').split("return '''")[1].split("'''.replace('CONFIG'")[0];
const rigLabels:Record<string,string> = {g8f:'Genesis 8 Female',g8m:'Genesis 8 Male',g9:'Genesis 9'};
function fixture(rigId = 'g9', placement = 'reference', selectedRigId = rigId) {
  const state = { ack: null as any, started: 0, accepted: 0, rolledBack: 0, cancelled: false, writes: [] as string[] };
  const properties: any[] = [];
  function property(name: string, value: number) {
    const p = {
      value, getRawValue() { return this.value; }, getValue() { return this.value; },
      getDefaultValue: () => 1, isLocked: () => false,
      setValue(v: number) { this.value = v; state.writes.push(name); }
    };
    properties.push(p); return p;
  }
  function node(name: string) {
    const n: any = { getName: () => name };
    for (const axis of ['X', 'Y', 'Z']) {
      const rotation = property(name + '/' + axis + 'Rotate', 0);
      const position = property(name + '/' + axis + 'Position', 17);
      const scale = property(name + '/' + axis + 'Scale', axis === 'Y' ? 1.1 : .9);
      n['get' + axis + 'RotControl'] = () => rotation;
      n['get' + axis + 'PosControl'] = () => position;
      n['get' + axis + 'ScaleControl'] = () => scale;
    }
    const scale = property(name + '/Scale', 1);
    n.getScaleControl = () => scale;
    return n;
  }
  const hip = node('hip'), figure = node('figure'), identity = property('FBMIdentity', .7);
  Object.assign(figure, {
    inherits: (type: string) => type === 'DzSkeleton', getLabel: () => selectedRigId,
    assetUri: selectedRigId === 'g9' ? '/Genesis9/' : selectedRigId === 'g8f' ? '/Genesis8Female/' : '/Genesis8Male/', assetSource: '',
    getNodeParent: () => null, getNodeChildren: () => [hip],
    findNodeChild: (name: string) => name === 'hip' || name === (selectedRigId === 'g9' ? 'l_thigh' : 'lThighBend') ? hip : null
  });
  // Match a character whose height ERC changes effective scale but not its raw dial.
  figure.getScaleControl().getValue = () => figure.getScaleControl().value * .915;
  const config = {
    jobId: 'scale-test', ack: 'ack', cancel: 'cancel', placement, rigLabel: rigLabels[rigId],
    pose: { rigId, label: rigId, rotations: { hip: [12, 34, 56] }, rootRotation: [0, 90, 0], translation: [10, 15, -20], rig: { nodes: [{ id: 'hip' }] } },
    evaluated: { hip: [12, 34, 56] }
  };
  let snapshot: number[] = [];
  const context = {
    Scene: { getPrimarySelection: () => figure },
    DzFileInfo: class { exists() { return state.cancelled; } },
    DzFile: class { static WriteOnly = 1; open() { return true; } write(s: string) { state.ack = JSON.parse(s); } close() {} },
    beginUndo() { state.started++; snapshot = properties.map(p => p.value); },
    acceptUndo() { state.accepted++; },
    cancelUndo() { state.rolledBack++; properties.forEach((p, i) => p.value = snapshot[i]); }
  };
  return { state, figure, hip, identity, node, config, run() { vm.runInNewContext(template.replace('CONFIG', JSON.stringify(config)), context); return state.ack; } };
}

describe('DAZ scale preservation', () => {
  for(const target of ['g8f','g8m','g9'])for(const selected of ['g8f','g8m','g9'].filter(id=>id!==target)){
    it(`names ${target} when ${selected} is selected, without using the prompt or touching the scene`,()=>{
      const f=fixture(target,'keep',selected);f.config.pose.label='Both holding hands';
      const accepted=JSON.stringify(f.config.pose),ack=f.run();
      expect(ack.success).toBe(false);
      expect(ack.message).toContain('Select '+rigLabels[target]+' in DAZ Studio to apply this pose.');
      expect(ack.message).not.toContain('Both holding hands');
      expect(f.state.started).toBe(0);expect(f.state.writes).toEqual([]);
      expect(f.state.accepted).toBe(0);expect(f.state.rolledBack).toBe(0);
      expect(f.identity.getRawValue()).toBe(.7);expect(f.figure.getScaleControl().getValue()).toBe(.915);
      expect(JSON.stringify(f.config.pose)).toBe(accepted);
    });
  }
  it.each(['g8f','g8m','g9'])('accepts a descriptive pose title when the selected %s figure matches',rig=>{
    const f=fixture(rig,'keep');f.config.pose.label='Both holding hands';
    expect(f.run().success).toBe(true);expect(f.state.accepted).toBe(1);
  });
  it.each(['g8f','g8m','g9'])('preserves %s morphed pectoral correctives and identity while applying body channels',rig=>{
    const f=fixture(rig),pectoral=f.node(rig==='g9'?'l_pectoral':'lPectoral');
    pectoral.getXRotControl().getValue=()=>-1.5112384825432912;
    pectoral.getXRotControl().getControllerList=()=>{throw Error('JB2_Animation must not be inspected during body application');};
    f.figure.getNodeChildren=()=>[f.hip,pectoral];
    expect(f.run()).toMatchObject({success:true,maximumError:0,scalePreserved:true});
    expect(f.identity.getRawValue()).toBe(.7);expect(pectoral.getXRotControl().getValue()).toBe(-1.5112384825432912);
    expect(f.state.writes.some(n=>/pectoral|Identity|Scale/i.test(n))).toBe(false);
  });
  for (const rig of ['g8f', 'g8m', 'g9']) for (const placement of ['keep', 'floor', 'origin', 'reference']) {
    it(`applies ${rig}/${placement} without writing any scale or identity dial`, () => {
      const f = fixture(rig, placement), ack = f.run();
      expect(ack).toMatchObject({ success: true, maximumError: 0, scalePreserved: true });
      expect(f.state.accepted).toBe(1);
      expect(f.state.writes.every(id => /\/(?:[XYZ]Rotate|[XYZ]Position)$/.test(id))).toBe(true);
      expect(f.figure.getScaleControl().getRawValue()).toBe(1);
      expect(f.figure.getScaleControl().getValue()).toBe(.915);
      expect(f.figure.getYScaleControl().getValue()).toBe(1.1);
      expect(f.hip.getXScaleControl().getRawValue()).toBe(.9);
      expect(f.identity.getRawValue()).toBe(.7);
      expect(ack.warnings.length).toBe(placement === 'reference' ? 1 : 0);
      if (placement === 'keep') expect(f.figure.getXPosControl().getValue()).toBe(17);
    });
  }
  it('allows pose-driven bone scale evaluation while preserving the raw bone scale', () => {
    const f = fixture(), scale = f.hip.getYScaleControl();
    scale.getValue = () => scale.value * (1 + Math.abs(f.hip.getXRotControl().value) * .005);
    expect(f.run().success).toBe(true);
    expect(scale.getRawValue()).toBe(1.1);
    expect(scale.getValue()).toBeCloseTo(1.166);
  });
  it('rolls back if DAZ unexpectedly changes the effective figure scale', () => {
    const f = fixture(), scale = f.figure.getScaleControl();
    scale.getValue = () => scale.value * .915 * (1 + f.hip.getXRotControl().value * .005);
    expect(f.run()).toMatchObject({ success: false });
    expect(f.state.ack.message).toContain('scale control');
    expect(f.state.rolledBack).toBe(1); expect(f.state.accepted).toBe(0);
    expect(f.hip.getXRotControl().value).toBe(0); expect(scale.getValue()).toBe(.915);
  });
  it('rolls back an unexpected raw bone scale change without attempting a scale setter', () => {
    const f = fixture(), rotation = f.hip.getXRotControl(), scale = f.hip.getScaleControl();
    const originalSet = rotation.setValue.bind(rotation);
    rotation.setValue = (value: number) => { originalSet(value); scale.value = .8; };
    expect(f.run()).toMatchObject({ success: false }); expect(f.state.rolledBack).toBe(1);
    expect(scale.getRawValue()).toBe(1);
    expect(f.state.writes.some(id => /Scale/.test(id))).toBe(false);
  });
  it('rejects invalid scale and parented reference placement before mutation', () => {
    for (const parented of [false, true]) {
      const f = fixture();
      if (parented) f.figure.getNodeParent = () => ({});
      else f.hip.getScaleControl().getValue = () => NaN;
      expect(f.run().success).toBe(false); expect(f.state.writes).toHaveLength(0);
    }
  });
  it('preserves scales on failed rotation readback and cancellation', () => {
    for (const cancelled of [false, true]) {
      const f = fixture();
      if (cancelled) f.state.cancelled = true;
      else f.hip.getXRotControl().getValue = () => 0;
      expect(f.run().success).toBe(false); expect(f.state.accepted).toBe(0);
      expect(f.figure.getScaleControl().getValue()).toBe(.915);
      expect(f.hip.getXScaleControl().getValue()).toBe(.9);
      expect(f.state.writes.some(id => /Scale|Identity/.test(id))).toBe(false);
    }
  });
});
