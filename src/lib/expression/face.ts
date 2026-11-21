import type { Face, FaceRegion, ExpressionSource, ExpressionOptions } from './types';
export function actionRegion(action:string):FaceRegion{
  if(action.startsWith('brow'))return 'brows';
  if(action.startsWith('eyeLook'))return 'gaze';
  if(action.startsWith('eye'))return 'eyes';
  if(action.startsWith('cheek')||action.startsWith('nose'))return 'cheeks';
  return 'mouth';
}
export function shownActions(source:ExpressionSource|null,options:ExpressionOptions,neutral=false):Record<string,number>{
  if(!source||neutral)return {};
  return Object.fromEntries(Object.entries({...source.face.actions,...source.face.extras,...options.adjustments}).map(([action,v])=>[action,options.regions[actionRegion(action)]&&(!source.unknown.includes(actionRegion(action))||action in (options.adjustments??{}))&&!options.neutralRegions?.includes(actionRegion(action))?Math.min(1.5,Math.max(0,v*options.strength)):0]));
}
export function sourceFromFace(imageId:string,face:Face):ExpressionSource{
  const warnings:string[]=[],unknown:FaceRegion[]=[];
  const width=face.box[2]-face.box[0];
  if(width<90)warnings.push('Small face: lip detail and eyelids may be uncertain. A closer reference helps.');
  // Transformation is a learned orientation estimate, not depth ground truth.
  const matrix=face.matrix,yaw=matrix.length===16?Math.abs(Math.atan2(matrix[8],matrix[10])*180/Math.PI):0;
  if(yaw>55){warnings.push('Strong side angle: the far side is estimated. Inspect asymmetric eye and mouth movements.');unknown.push('gaze');}
  if(yaw>80){unknown.push('eyes','brows','mouth','cheeks');warnings.push('This extreme side angle is outside the supported view. Use a more frontal photograph.');}
  for(const [region,error] of Object.entries(face.evidence?.consistency??{}))if(error>.45){unknown.push(region as FaceRegion);warnings.push(regionLabelsForNotes[region]+' predictions conflict between crop and mirrored checks. This region is preserved in DAZ.');}
  if(face.evidence)warnings.push(`${face.evidence.passes} local measurements checked. Consistency is a diagnostic, not an accuracy score.`);
  if((face.extras?.tongueOut??0)>.3)warnings.push('Visible tongue estimated from mouth pixels. Tongue shape and depth remain approximate.');
  const puff=face.evidence?.supplemental?.cheekPuff;if(puff&&(puff.accepted??face.actions.cheekPuff>.2))warnings.push('Cheek puff estimated from facial geometry. Natural face shape can affect this estimate.');
  return {version:1,engine:'mediapipe-1.1.0-face-v1',imageId,face,unknown:[...new Set(unknown)],warnings};
}
const regionLabelsForNotes:Record<string,string>={brows:'Brow',eyes:'Eyelid',mouth:'Mouth',cheeks:'Cheek',gaze:'Eye direction'};
