export interface OralAttachment {mesh:string;surface:string;vertices:number[];indices:number[]}
export const ORAL_CLEARANCE_ASSET:string;
export function createOralClearance(meshes:{name:string;positions:Float32Array;index:Uint16Array|Uint32Array}[],attachment:OralAttachment,assetSha256:string):{
  correct(surfaces:Map<string,Float32Array>,actions:Record<string,number>):{lining:boolean;tongue:boolean};
};
