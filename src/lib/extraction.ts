import type { ExtractionMethod, ExtractionPreference, Pose, RigId } from './types';

export const methodLabel:Record<ExtractionPreference,string>={auto:'Auto',pure:'Pure',smart:'Genesis Smart Fit'};
/** Context is the operation, not the number of people detected in the photo. */
export function extractionFor(preference:ExtractionPreference,interaction=false):ExtractionMethod {
  return preference==='auto'?(interaction?'smart':'pure'):preference;
}

interface IndividualSelection {imageId:string;personId:number;rigId:RigId}
interface IndividualRequest extends IndividualSelection {extractionMethod:ExtractionMethod;refinement:'accurate';refresh:false}

/** Resolve the individual operation afresh; never reuse a coordinated partner pose. */
export async function individualAfterInteraction(
  selection:IndividualSelection,
  preference:ExtractionPreference,
  solve:(payload:IndividualRequest)=>Promise<Pose|null>,
  isCurrent:()=>boolean
):Promise<Pose|null> {
  const method=extractionFor(preference);
  // solve reuses this method's validated source cache, or extracts it if absent.
  const result=await solve({...selection,extractionMethod:method,refinement:'accurate',refresh:false});
  if(!result||!isCurrent())return null;
  if(result.imageId!==selection.imageId||result.personId!==selection.personId||result.rigId!==selection.rigId||
     result.extractionMethod!==method||result.layout?.reference){
    throw new Error('The individual extraction did not match the selected person and method. Your interaction is kept; retry Exit.');
  }
  return result;
}
