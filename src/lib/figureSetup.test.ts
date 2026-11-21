import { describe, expect, it } from 'vitest';
import { Quaternion, Vector3 } from 'three';
import { blankPose, copyPoses, onFloor, rotateJoint, snapshot } from './editor';
import { facingPreset, facingPresets, floorClearance, setFacing, setFloorClearance } from './figureSetup';
import { forwardKinematics, previewRotations, quat } from './pose';
import { togglePin, preservePins } from './pinning';
import type { Pose, Rig } from './types';
import g8f from '../../tests/fixtures/target-fit/g8f.json';
import g8m from '../../tests/fixtures/target-fit/g8m.json';
import g9 from '../../tests/fixtures/target-fit/g9.json';
const rigs = [g8f, g8m, g9] as unknown as Rig[];
function pose(rig: Rig, person = 1): Pose {
  const p = blankPose(structuredClone(rig), 'setup-test');
  return { ...p, personId: person, rootRotation: [13, 42, -7], translation: [24, 17, -32] };
}
function frame(p: Pose, bone?: string) { return forwardKinematics(p.rig, previewRotations(p), p.translation).get(bone ?? p.rig.nodes.find(n => !n.parent)!.id)!; }

describe('Pose Studio facing and floor adjustments', () => {
  for (const rig of rigs) for (const preset of facingPresets) {
    it(`${rig.id}: ${preset.id} preserves joint edits, placement axes and rig data`, () => {
      const initial = pose(rig), bone = rig.id === 'g9' ? 'l_shin' : 'lShin';
      const edited = rotateJoint(onFloor(initial), bone, [45, 0, 0]);
      const source = setFloorClearance([edited], 1, 4)[0], before = JSON.stringify(source);
      const next = setFacing([source], [initial], 1, preset.id)[0];
      const expected = quat([...preset.angles]).multiply(frame(initial).rotation);
      expect(frame(next).rotation.angleTo(expected)).toBeLessThan(1e-6);
      expect(facingPreset(next, initial)).toBe(preset.id);
      expect(next.rotations).toEqual(source.rotations);
      expect(next.rig).toBe(source.rig); expect(JSON.stringify(source)).toBe(before);
      expect(next.translation[0]).toBe(source.translation[0]); expect(next.translation[2]).toBe(source.translation[2]);
      expect(floorClearance([next], 1)).toBeCloseTo(4, 7);
    });
  }
  it('does not accumulate a preset when it is selected repeatedly', () => {
    const p = pose(rigs[2]), scene = setFacing([p], [p], 1, 'right');
    const repeated = setFacing(scene, [p], 1, 'right');
    expect(repeated).toBe(scene); expect(facingPreset(repeated[0], p)).toBe('right');
    expect(setFacing(repeated, [p], 1, 'extracted')[0].rootRotation!.every(Number.isFinite)).toBe(true);
  });
  it('keeps mixed-generation contacts and separation during a rigid scene turn', () => {
    const a = pose(rigs[0]), b = { ...pose(rigs[2], 2), translation: [50, 11, 23], rootRotation: [25, -56, 7] };
    const input = [a, b], targets = ['lHand', 'l_hand'];
    const distance = frame(a, targets[0]).position.distanceTo(frame(b, targets[1]).position);
    const offset = floorClearance(input, 1, true), next = setFacing(input, input, 1, 'faceup', true);
    expect(frame(next[0], targets[0]).position.distanceTo(frame(next[1], targets[1]).position)).toBeCloseTo(distance, 6);
    expect(frame(next[0]).position.distanceTo(frame(next[1]).position)).toBeCloseTo(frame(a).position.distanceTo(frame(b).position), 6);
    expect(floorClearance(next, 1, true)).toBeCloseTo(offset, 7);
    expect(next.map(p => p.rotations)).toEqual(input.map(p => p.rotations));
  });
  it('leaves the unselected mannequin untouched unless partners are linked', () => {
    const a = pose(rigs[0]), b = pose(rigs[2], 2);
    expect(setFacing([a, b], [a, b], 1, 'left')[1]).toBe(b);
    expect(setFloorClearance([a, b], 1, 5)[1]).toBe(b);
  });
  it('adjusts linked floor height with one common delta and preserves depth', () => {
    const a = pose(rigs[0]), b = { ...pose(rigs[2], 2), translation: [60, 30, 25] }, input = [a, b];
    const next = setFloorClearance(input, 1, -4.5, true);
    expect(floorClearance(next, 1, true)).toBeCloseTo(-4.5, 7);
    expect(next[0].translation[1] - a.translation[1]).toBeCloseTo(next[1].translation[1] - b.translation[1]);
    next.forEach((p, i) => { expect(p.translation[0]).toBe(input[i].translation[0]); expect(p.translation[2]).toBe(input[i].translation[2]); expect(p.rotations).toBe(input[i].rotations); });
  });
  it('retains airborne root height when changing facing', () => {
    const a: Pose = { ...pose(rigs[2]), footSupport: [{ side: 'l', state: 'air' }, { side: 'r', state: 'air' }] };
    const next = setFacing([a], [a], 1, 'faceup')[0];
    expect(next.translation).toEqual(a.translation);
    expect(setFloorClearance([next], 1, 15)[0].translation[1]).not.toBe(next.translation[1]);
  });
  it('respects root rotation locks and refuses a scene turn a partner cannot follow', () => {
    const a = pose(rigs[0]), b = pose(rigs[2], 2), root = b.rig.nodes.find(n => !n.parent)!;
    root.limits.y = { min: -180, max: 180, clamped: true, locked: true };
    const input = [a, b]; expect(setFacing(input, input, 1, 'right', true)).toBe(input);
    const limited = pose(rigs[2]), n = limited.rig.nodes.find(n => !n.parent)!;
    n.limits.y = { min: -45, max: 45, clamped: true };
    expect(Math.abs(setFacing([limited], [limited], 1, 'back')[0].rootRotation![1])).toBeLessThanOrEqual(45);
  });
  it('shows custom orientation for manual rotation and keeps snapshot data independent', () => {
    const p = pose(rigs[1]), before = snapshot([p], [p], 1), custom = { ...p, rootRotation: [31, 25, 12] };
    expect(facingPreset(custom, p)).toBe('custom');
    const next = setFloorClearance(setFacing([custom], [p], 1, 'right'), 1, 6);
    const restored = copyPoses(before.poses);
    expect(restored[0]).toEqual(p); expect(next[0]).not.toEqual(p);
    expect(before.baseline[0].rootRotation).toEqual(p.rootRotation);
  });
  it('retains camera and pin metadata while existing pin compensation runs', () => {
    const p = pose(rigs[2]); p.referenceCamera = { version: 1, intrinsics: [[1, 0, 0], [0, 1, 0], [0, 0, 1]], imageSize: [100, 100], originCm: [0, 0, 500] } as Pose['referenceCamera'];
    const pinned = togglePin(p, 'l_hand', 'rotation'), next = setFacing([pinned], [p], 1, 'right')[0];
    expect(next.referenceCamera).toBe(p.referenceCamera); expect(next.pins).toEqual(pinned.pins);
    const adjusted = preservePins(next); expect(adjusted.pins).toEqual(pinned.pins); expect(adjusted.referenceCamera).toBe(p.referenceCamera);
    expect(new Quaternion().fromArray(adjusted.pins!.l_hand.rotation!).angleTo(new Quaternion().fromArray(pinned.pins!.l_hand.rotation!))).toBe(0);
  });
  it('handles rig origin orientation and rotation order explicitly', () => {
    const p = pose(rigs[2]), root = p.rig.nodes.find(n => !n.parent)!;
    root.order = 'YZX'; root.orientation = [24, -13, 37]; root.center = [8, 23, -5];
    const next = setFacing([p], [p], 1, 'left')[0];
    expect(frame(next).rotation.angleTo(quat([0, -90, 0]).multiply(frame(p).rotation))).toBeLessThan(1e-6);
    expect(new Vector3(next.translation[0], 0, next.translation[2])).toEqual(new Vector3(p.translation[0], 0, p.translation[2]));
  });
  it('rejects nonfinite floor input and unknown selected mannequins without mutation', () => {
    const p = pose(rigs[2]), input = [p];
    expect(setFloorClearance(input, 1, NaN)).toBe(input);
    expect(setFloorClearance(input, 99, 5)).toBe(input);
    expect(setFacing(input, input, 99, 'right')).toBe(input);
    expect(setFloorClearance(input, 1, floorClearance(input, 1))).toBe(input);
  });
});
