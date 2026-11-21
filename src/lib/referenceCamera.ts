import { Matrix4, Quaternion, Vector3 } from 'three';
import type { CalibratedReferenceCamera, ReferenceCamera } from './types';
export function referenceFrame(camera:ReferenceCamera,width:number,height:number){
  const [w,h]=camera.imageSize,scale=Math.min(width/w,height/h);
  return {x:(width-w*scale)/2,y:(height-h*scale)/2,width:w*scale,height:h*scale,scale};
}
export function referenceProjection(camera:ReferenceCamera,near=.01,far=50){
  const [[fx,,cx],[,fy,cy]]=camera.intrinsics,[w,h]=camera.imageSize;
  if(![fx,fy,w,h,...(camera.version===1?camera.originCm:camera.worldToCamera.flat())].every(Number.isFinite)||Math.min(fx,fy,w,h)<=0)throw Error('Invalid reference camera');
  if(camera.version===2&&camera.projection==='orthographic')return new Matrix4().makeOrthographic(-cx/fx*.01,(w-cx)/fx*.01,cy/fy*.01,-(h-cy)/fy*.01,near,far);
  return new Matrix4().makePerspective(-cx/fx*near,(w-cx)/fx*near,cy/fy*near,-(h-cy)/fy*near,near,far);
}

export function cameraTransform(camera:CalibratedReferenceCamera){
  const t=camera.worldToCamera,rotation=new Matrix4().set(t[0][0],-t[1][0],-t[2][0],0,t[0][1],-t[1][1],-t[2][1],0,t[0][2],-t[1][2],-t[2][2],0,0,0,0,1);
  const position=new Vector3(-t[0][0]*t[0][3]-t[1][0]*t[1][3]-t[2][0]*t[2][3],-t[0][1]*t[0][3]-t[1][1]*t[1][3]-t[2][1]*t[2][3],-t[0][2]*t[0][3]-t[1][2]*t[1][3]-t[2][2]*t[2][3]).multiplyScalar(.01);
  return {position,quaternion:new Quaternion().setFromRotationMatrix(rotation)};
}
