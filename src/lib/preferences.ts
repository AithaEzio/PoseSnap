import type { ExtractionPreference,Theme } from './types';

export interface InitialPreferences {theme:Theme;motion:'auto'|'reduced';extractionMethod:ExtractionPreference;clueEnabled:boolean;zeroCroppedJoints:boolean;imageGuidance:'off'|'auto';depthInputType:'relative'|'metric'}
export function validatedPreferences(value:unknown):InitialPreferences {
  const saved=value&&typeof value==='object'?value as Record<string,unknown>:{};
  return {
    theme:['dark','neon','light'].includes(String(saved.theme))?saved.theme as Theme:'dark',
    motion:saved.motion==='reduced'?'reduced':'auto',
    extractionMethod:['auto','pure','smart'].includes(String(saved.extractionMethod))?saved.extractionMethod as ExtractionPreference:'auto',
    clueEnabled:typeof saved.clueEnabled==='boolean'?saved.clueEnabled:false,
    zeroCroppedJoints:typeof saved.zeroCroppedJoints==='boolean'?saved.zeroCroppedJoints:true,
    imageGuidance:saved.imageGuidance==='off'?'off':'auto',
    depthInputType:saved.depthInputType==='metric'?'metric':'relative'
  };
}
export function initialPreferences():InitialPreferences {
  const native=(window as Window&{__POSESNAP_INITIAL_SETTINGS__?:unknown}).__POSESNAP_INITIAL_SETTINGS__;
  if(native)return validatedPreferences(native);
  if(import.meta.env.DEV){
    let saved={};try{saved=JSON.parse(localStorage.getItem('posesnap-development-preferences')??'{}');}catch{/* Invalid preview preferences use defaults. */}
    const params=new URLSearchParams(location.search);
    return validatedPreferences({...saved,...(params.has('theme')?{theme:params.get('theme')}:{}),...(params.has('motion')?{motion:params.get('motion')}: {})});
  }
  return validatedPreferences({});
}
export function rememberDevelopmentPreferences(value:InitialPreferences){
  if(import.meta.env.DEV&&!('__TAURI_INTERNALS__' in window))try{localStorage.setItem('posesnap-development-preferences',JSON.stringify(value));}catch{/* Storage may be unavailable in a preview. */}
}
