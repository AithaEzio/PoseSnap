import type { RigId } from '../types';
export type FaceRegion='brows'|'eyes'|'mouth'|'cheeks'|'gaze';
export interface Face {id:number;box:number[];selectionBox?:number[];observationId?:string;landmarks:number[][];actions:Record<string,number>;matrix:number[];roll?:number;rawActions?:Record<string,number>;extras?:{tongueOut?:number};thumbnail?:string;evidence?:{passes:number;consistency:Partial<Record<FaceRegion,number>>;supplemental?:Partial<Record<'cheekPuff'|'tongueOut',{value:number;agreement:number;accepted?:boolean;method:string}>>;features?:Record<string,number>}}
export interface ExpressionOptions {strength:number;regions:Record<FaceRegion,boolean>;neutralRegions?:FaceRegion[];adjustments?:Record<string,number>}
export interface ExpressionSource {version:1|2;kind?:'text';engine:'mediapipe-1.1.0-face-v1'|'text-intent-v1';imageId?:string;sceneId?:string;face:Face;unknown:FaceRegion[];warnings:string[]}
export interface FaceDriver {id:string;owner:string;property:string;label:string;min:number;max:number;default:number;locked:boolean;dependencies:string[];url:string}
export interface FaceMapping {action:string;driver:string;weight:number;region:FaceRegion}
export interface FaceProfile {version:1;rigId:RigId;label:string;signature:string;drivers:FaceDriver[];mappings:FaceMapping[];unsupported:string[];anatomy?:{eyes:boolean;tongue:boolean};pairedGazeAxes?:('horizontal'|'vertical')[]}
export interface TargetExpression {version:1;kind:'expression';rigId:RigId;profileSignature:string;source:ExpressionSource;options:ExpressionOptions;channels:Record<string,number>;previewActions:Record<string,number>;supported:number;total:number;warnings:string[]}
export const regionLabels:Record<FaceRegion,string>={brows:'Brows',eyes:'Eyelids',mouth:'Mouth & jaw',cheeks:'Cheeks & nose',gaze:'Eye direction'};
export const defaultOptions=():ExpressionOptions=>({strength:1,regions:{brows:true,eyes:true,mouth:true,cheeks:true,gaze:true},neutralRegions:[],adjustments:{}});
