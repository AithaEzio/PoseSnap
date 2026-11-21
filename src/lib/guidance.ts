import type {Pose} from './types';

export type GuidanceMode='off'|'auto';
export type MapQuality='standard'|'detailed';
export type ReferenceKind='photo'|'relative-depth'|'metric-depth';
export interface GuidanceInspection {
  version:1;imageId:string;available:string[];url?:string;message?:string;notes:string[];
  evidence:{state?:string;provider?:string;profile?:string;cacheHit?:boolean;depthEncoding?:string};
}
export const guidanceLabels:Record<GuidanceMode,string>={off:'Off',auto:'Automatic'};

export function guidanceStatus(poses:Pose[]):string {
  const rows=poses.flatMap(p=>p.referenceEvidence?[p.referenceEvidence]:[]);
  if(!rows.length)return '';
  if(rows.some(r=>r.applied))return rows.length===poses.length&&rows.every(r=>r.applied)?' Image guidance applied.':' Image guidance applied to some people.';
  if(rows.some(r=>r.outcome==='fallback'))return ' Baseline extraction used. See Pose notes.';
  if(rows.some(r=>r.outcome==='insufficient'))return ' Insufficient guidance evidence. See Pose notes.';
  return ' Guidance did not change the pose.';
}
