import { Euler, Quaternion, Vector3 } from 'three';
import { figureKey, onFloor, rotateJoint } from './editor';
import { quat } from './pose';
import type { Pose } from './types';

export const facingPresets = [
  { id: 'extracted', label: 'As extracted', angles: [0, 0, 0] },
  { id: 'back', label: 'Turn 180°', angles: [0, 180, 0] },
  { id: 'left', label: 'Turn left 90°', angles: [0, -90, 0] },
  { id: 'right', label: 'Turn right 90°', angles: [0, 90, 0] },
  { id: 'faceup', label: 'Lie face up', angles: [-90, 0, 0] },
  { id: 'facedown', label: 'Lie face down', angles: [90, 0, 0] }
] as const;
export type FacingPreset = typeof facingPresets[number]['id'];
const root = (pose: Pose) => pose.rig.nodes.find(n => !n.parent)!;
function rootWorld(pose: Pose) {
  const n = root(pose), orientation = quat(n.orientation);
  return orientation.clone().multiply(quat(pose.rootRotation ?? [0, 0, 0], n.order)).multiply(orientation.invert());
}
function rootAngles(pose: Pose, world: Quaternion) {
  const n = root(pose), orientation = quat(n.orientation);
  const local = orientation.clone().invert().multiply(world).multiply(orientation);
  const euler = new Euler().setFromQuaternion(local, n.order.split('').reverse().join('') as Euler['order']);
  return [euler.x, euler.y, euler.z].map(v => v * 180 / Math.PI);
}
export function facingPreset(pose: Pose, baseline: Pose): FacingPreset | 'custom' {
  const relative = rootWorld(pose).multiply(rootWorld(baseline).invert());
  return facingPresets.find(p => relative.angleTo(quat([...p.angles])) < 1e-5)?.id ?? 'custom';
}
/** Lowest rig endpoint; matches the studio's existing Place on floor behavior. */
export function floorClearance(poses: Pose[], person: number, together = false): number {
  const members = poses.filter(p => together || p.personId === person);
  return members.length ? Math.min(...members.map(p => p.translation[1] - onFloor(p).translation[1])) : 0;
}
export function setFloorClearance(poses: Pose[], person: number, height: number, together = false): Pose[] {
  if (!poses.some(p => p.personId === person) || !Number.isFinite(height)) return poses;
  const delta = height - floorClearance(poses, person, together);
  if (Math.abs(delta) < 1e-8) return poses;
  return poses.map(p => p.personId === person || together ? { ...p, translation: [p.translation[0], p.translation[1] + delta, p.translation[2]], edited: true } : p);
}
/** Apply an absolute preset relative to the editing baseline, without erasing joint edits. */
export function setFacing(poses: Pose[], baseline: Pose[], person: number, preset: FacingPreset, together = false): Pose[] {
  const selected = poses.find(p => p.personId === person), initial = baseline.find(p => p.personId === person);
  const choice = facingPresets.find(p => p.id === preset);
  if (!selected || !initial || initial.rigId !== selected.rigId || !choice) return poses;
  const wanted = quat([...choice.angles]).multiply(rootWorld(initial));
  const turned = rotateJoint(selected, figureKey, rootAngles(selected, wanted));
  const delta = rootWorld(turned).multiply(rootWorld(selected).invert()).normalize();
  if (delta.angleTo(new Quaternion()) < 1e-8) return poses;
  const pivot = new Vector3().fromArray(root(selected).center).add(new Vector3().fromArray(selected.translation));
  let blocked = false;
  const next = poses.map(p => {
    if (p.personId === person) return turned;
    if (!together) return p;
    const orientation = delta.clone().multiply(rootWorld(p));
    const rotated = rotateJoint(p, figureKey, rootAngles(p, orientation));
    if (rootWorld(rotated).angleTo(orientation) > 1e-5) blocked = true;
    const center = new Vector3().fromArray(root(p).center);
    const position = center.clone().add(new Vector3().fromArray(p.translation)).sub(pivot).applyQuaternion(delta).add(pivot).sub(center);
    return { ...rotated, translation: position.toArray() };
  });
  if (blocked) return poses; // A locked partner must not break a rigid scene turn.
  const airborne = poses.filter(p => together || p.personId === person).every(p => !!p.footSupport?.length && p.footSupport.every(s => s.state === 'air'));
  return airborne ? next : setFloorClearance(next, person, floorClearance(poses, person, together), together);
}
