<script lang="ts">
  import { SlidersHorizontal, ChevronDown, RotateCcw, Eye, ScanFace, Smile, FolderOpen } from 'lucide-svelte';
  import { tooltip } from '../tooltip';
  import { liveNumber } from '../liveNumber';
  import { detailSliders, detectedDetailGroups, detailValue, adjustDetail, resetDetail, detailStatus } from './details';
  import { regionLabels, type ExpressionOptions, type ExpressionSource, type FaceProfile, type TargetExpression, type FaceRegion } from './types';
  let {source,options,target,profile,rigLabel,busy,desktop,neutral,collapsed=$bindable(false),onChange,onCompare,onReset,onOpen,onZeroDaz,onNumberFocus=()=>{}}:{
    source:ExpressionSource|null;options:ExpressionOptions;target:TargetExpression|null;profile?:FaceProfile;rigLabel:string;
    busy:boolean;desktop:boolean;neutral:boolean;collapsed?:boolean;onChange:(options:ExpressionOptions)=>void;
    onCompare:()=>void;onReset:()=>void;onOpen:()=>void;onZeroDaz:()=>void;
    onNumberFocus?:(focused:boolean)=>void;
  }=$props();
  let area=$state<'mouth'|'cheeks'|'eyes'|'gaze'>('mouth'),side=$state<'Left'|'Right'>('Left');
  const areas=[{id:'mouth',label:'Mouth'},{id:'cheeks',label:'Cheeks'},{id:'eyes',label:'Eyes'},{id:'gaze',label:'Gaze'}] as const;
  const sliders=$derived(detailSliders.filter(slider=>slider.region===area&&(area!=='eyes'||slider.id.endsWith(side))));
  type DetectedDetail=typeof detectedDetailGroups[number]['items'][number];
  const detected=$derived(detectedDetailGroups.flatMap<DetectedDetail>(group=>group.items).filter(([action,,region])=>region===area&&(area!=='eyes'||action.endsWith(side))));
  function strength(value:number){if(!source||busy||!Number.isFinite(value))return;onChange({...options,strength:Math.max(0,Math.min(150,value))/100});}
  function detail(id:typeof detailSliders[number]['id'],value:number){if(!source||busy||!Number.isFinite(value))return;onChange(adjustDetail(id,value/100,options));}
  function holdRefit(input:HTMLInputElement){
    let focused=false;
    const focus=()=>{if(!focused){focused=true;onNumberFocus(true);}};
    const blur=()=>{if(focused){focused=false;onNumberFocus(false);}};
    input.addEventListener('focus',focus);input.addEventListener('blur',blur);
    return {destroy(){blur();input.removeEventListener('focus',focus);input.removeEventListener('blur',blur);}};
  }
  function zeroRegion(region:FaceRegion){
    if(!source||busy)return;
    const zeroed=options.neutralRegions??[];
    onChange({...options,regions:{...options.regions,[region]:true},neutralRegions:zeroed.includes(region)?zeroed.filter(r=>r!==region):[...zeroed,region]});
  }
</script>

<aside class="expression-inspector editor-inspector" class:collapsed aria-label="Expression controls">
  <div class="editor-heading">
    <button class="text-button" aria-label={collapsed?'Expand Expression controls':'Collapse Expression controls'} aria-expanded={!collapsed} use:tooltip={'Show or collapse expression controls. Your adjustments are kept.'} onclick={()=>collapsed=!collapsed}><SlidersHorizontal size={15}/> Expression controls <ChevronDown size={13}/></button>
    {#if !collapsed}<button class="icon-button" aria-label="Reset expression options" disabled={!source||busy} use:tooltip={'Restore 100% strength, detected details and default regions. Your extraction is kept.'} onclick={onReset}><RotateCcw size={15}/></button>{/if}
  </div>
  {#if !collapsed}<div class="editor-body">
    {#if source}
      <div class="selected-joint-card expression-selection"><div><small>FACE {source.face.id} · {source.kind==='text'?'TEXT AUTHORED':'EXTRACTED'}</small><strong>{rigLabel}</strong><span>{target?`${target.supported} / ${target.total} movements supported`:busy?'Fitting facial controls…':profile?'Source preview':'Connect this figure to export'}</span></div></div>
      <div class="expression-compare" role="group" aria-label="Expression comparison">
        <button class="compact-button" class:active={!neutral} aria-pressed={!neutral} disabled={busy} onclick={()=>{if(neutral)onCompare();}} use:tooltip={'Show your expression with its current adjustments.'}><Smile size={13}/> Result</button>
        <button class="compact-button" class:active={neutral} aria-pressed={neutral} disabled={busy} onclick={()=>{if(!neutral)onCompare();}} use:tooltip={'Inspect the neutral preview. Your extracted expression and export values are kept.'}><Eye size={13}/> Neutral</button>
      </div>
      {#if neutral}<p class="editor-caption">Viewing neutral. Your expression is kept.</p>{/if}
      <section class="editor-section expression-strength">
        <h3><label for="expression-strength">Strength</label><small>Percent</small></h3>
        <div class="expression-range-field"><input id="expression-strength" type="range" min="0" max="150" step="1" value={options.strength*100} disabled={busy} oninput={e=>strength(Number(e.currentTarget.value))} use:tooltip={'100% follows the extraction. Lower values soften it; higher values exaggerate within supported limits.'}/><input type="number" min="0" max="150" step="1" aria-label="Expression strength in percent" disabled={busy} use:holdRefit use:liveNumber={{value:options.strength*100,context:source.imageId+'/'+source.face.id+'/strength',normalize:value=>Math.max(0,Math.min(150,value)),onValue:strength,onEditing:()=>{}}}/></div>
      </section>
      <details class="editor-advanced expression-details" open>
        <summary use:tooltip={'Adjust a detail by facial region. Reset restores its extracted value.'}>Fine tune details <ChevronDown size={13}/></summary>
        <div class="editor-advanced-body">
          <div class="expression-region-tabs" role="group" aria-label="Facial detail groups">{#each areas as item}<button class:active={area===item.id} aria-pressed={area===item.id} disabled={busy} onclick={()=>area=item.id} use:tooltip={'Show '+item.label.toLowerCase()+' details. Other adjustments are kept.'}>{item.label}</button>{/each}</div>
          {#if area==='eyes'}<div class="expression-eye-tabs" role="group" aria-label="Eye to adjust">{#each ['Left','Right'] as value}<button class="compact-button" class:active={side===value} aria-pressed={side===value} disabled={busy} onclick={()=>side=value as typeof side} use:tooltip={'Adjust the person’s '+value.toLowerCase()+' eye independently.'}>{value} eye</button>{/each}</div>{/if}
          <p class="editor-caption">{area==='eyes'?'Left and right follow the person’s anatomy.':area==='gaze'?'Both eyes move together. Head orientation is kept.':'Optional adjustments. Reset returns to the extraction.'}</p>
          <details class="expression-detected"><summary>Detected details <ChevronDown size={12}/></summary><div>
            {#each detected as [action,label,region]}{@const state=detailStatus(action,region,source,options,profile)}<div class="expression-detection-row"><span>{label}</span><b>{state.evidence}</b><small>{state.transfer}</small></div>{/each}
          </div></details>
          {#each sliders as slider}
            <div class="expression-detail-field">
              <div class="expression-detail-label"><label for={'face-detail-'+slider.id}>{slider.label.replace(/^(Left|Right) eye · /,'').replace('Eye direction · ','')}</label><button class="icon-button" disabled={busy} aria-label={'Reset '+slider.label} use:tooltip={slider.region==='eyes'?'Restore all detected eyelid movements for this eye.':'Restore the extracted value for '+slider.label.toLowerCase()+'.'} onclick={()=>onChange(resetDetail(slider.id,options))}><RotateCcw size={12}/></button></div>
              <div class="expression-range-field"><input id={'face-detail-'+slider.id} type="range" min={slider.min*100} max="100" step="1" value={detailValue(slider.id,source,options)*100} disabled={busy} use:tooltip={slider.hint} oninput={e=>detail(slider.id,Number(e.currentTarget.value))}/><input type="number" min={slider.min*100} max="100" step="1" aria-label={slider.label+' in percent'} disabled={busy} use:holdRefit use:liveNumber={{value:detailValue(slider.id,source,options)*100,context:source.imageId+'/'+source.face.id+'/'+slider.id,normalize:value=>Math.max(slider.min*100,Math.min(100,value)),onValue:value=>detail(slider.id,value),onEditing:()=>{}}}/></div>
            </div>
          {/each}
        </div>
      </details>
      <details class="editor-advanced expression-regions">
        <summary use:tooltip={'Choose the facial regions to transfer. Disabled and unknown regions are kept in DAZ.'}>Facial regions <ChevronDown size={13}/></summary>
        <div class="editor-advanced-body"><p class="editor-caption">Include a region, or explicitly set it to neutral.</p>
          {#each Object.entries(regionLabels) as [key,label]}{@const region=key as FaceRegion}{@const zeroed=options.neutralRegions?.includes(region)??false}
            <div class="face-region-row"><label class="face-region" use:tooltip={source.unknown.includes(region)?'This region is uncertain. Preserve it, or explicitly choose Zero.':'Include '+label.toLowerCase()+' in preview and export.'}><input type="checkbox" checked={options.regions[region]} disabled={busy||source.unknown.includes(region)&&!zeroed} onchange={e=>onChange({...options,regions:{...options.regions,[region]:e.currentTarget.checked}})}/>{label}{#if source.unknown.includes(region)}<small>Unknown</small>{/if}</label><button class:active={zeroed} disabled={busy} aria-pressed={zeroed} aria-label={(zeroed?'Restore extracted ':'Zero ')+label} use:tooltip={zeroed?'Return to extracted '+label.toLowerCase()+' movements.':'Set supported '+label.toLowerCase()+' controls to neutral. Other regions stay intact.'} onclick={()=>zeroRegion(region)}><RotateCcw size={12}/>{zeroed?'Restore':'Zero'}</button></div>
          {/each}
        </div>
      </details>
    {:else}
      <div class="editor-empty"><ScanFace size={24}/><h3>Bring a feeling into focus.</h3><p>Open a reference, choose a face and extract its expression. Adjust its strength and details here.</p><button class="primary wide" disabled={busy} onclick={onOpen} use:tooltip={'Open a photograph with a clear face.'}><FolderOpen size={15}/> Open image</button></div>
    {/if}
    <details class="editor-advanced expression-daz-actions">
      <summary use:tooltip={'Actions for the selected matching figure in DAZ Studio.'}>DAZ actions <ChevronDown size={13}/></summary>
      <div class="editor-advanced-body"><button class="secondary wide" disabled={!desktop||busy} onclick={onZeroDaz} use:tooltip={desktop?'Zero only the controls PoseSnap applied to this figure. Other DAZ dials and morph values are kept. One DAZ undo step; your extraction is kept.':'This action is available in the desktop app.'}><RotateCcw size={13}/> Zero applied expression</button><p class="editor-caption">Selected {rigLabel} · PoseSnap controls only · One undo step</p></div>
    </details>
  </div>{/if}
</aside>

<style>
  .expression-inspector{width:var(--face-inspector-width);z-index:4}
  .expression-inspector.collapsed{width:205px}
  .editor-heading>.icon-button{flex:none;width:26px;height:26px}
  .expression-selection span{display:block;margin-top:6px;font-size:9px;line-height:1.5;color:var(--muted)}
  .expression-compare{display:flex;gap:6px;margin:12px 0}
  .expression-compare button{flex:1;justify-content:center}
  .expression-range-field{display:grid;grid-template-columns:minmax(0,1fr) 54px;align-items:center;gap:9px}
  .expression-range-field input[type=range]{width:100%;min-width:0;accent-color:var(--accent);margin:0}
  .expression-range-field input[type=number]{width:100%;height:31px;min-width:0;padding:5px;border:1px solid var(--line);border-radius:5px;background:var(--deep);font-size:11px}
  .expression-region-tabs{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));padding:3px;border:1px solid var(--line);border-radius:8px;gap:2px;background:var(--deep)}
  .expression-region-tabs button{border:0;border-radius:5px;background:transparent;color:var(--muted);padding:9px 2px;font-size:10px}
  .expression-region-tabs button.active{color:var(--accent);background:var(--tint)}
  .expression-eye-tabs{display:flex;gap:6px;margin:10px 0}
  .expression-eye-tabs button{flex:1;justify-content:center}
  .expression-details .editor-caption{margin:10px 0;font-size:9px}
  .expression-detected{border:1px solid var(--line);border-radius:8px;background:var(--deep);margin:12px 0}
  .expression-detected summary{display:flex;align-items:center;justify-content:space-between;padding:10px;cursor:pointer;list-style:none;font-size:10px;color:var(--text)}
  .expression-detected>div{padding:0 10px 5px}
  .expression-detection-row{display:grid;grid-template-columns:1fr auto;gap:3px 6px;padding:7px 0;border-top:1px solid var(--line);font-size:10px}
  .expression-detection-row b{color:var(--accent);font-weight:500}
  .expression-detection-row small{grid-column:1/-1;font-size:9px;color:var(--muted)}
  .expression-detail-field{margin-top:12px}
  .expression-detail-label{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:5px;font-size:10px;color:var(--muted)}
  .expression-detail-label>.icon-button{width:24px;height:24px;flex:none}
  .expression-details summary::-webkit-details-marker,.expression-detected summary::-webkit-details-marker{display:none}
  .expression-detected:not([open]) summary :global(svg),.editor-advanced:not([open]) summary :global(svg){transform:rotate(-90deg)}
  .expression-inspector .editor-heading .text-button{white-space:nowrap}
  .expression-daz-actions .wide{font-size:10px;padding:9px 5px}
  .face-region{display:flex;align-items:center;gap:7px;padding:8px 0;font-size:10px;color:var(--muted)}
  .face-region input{accent-color:var(--accent);margin:0}
  .face-region small{font-size:9px}
  button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
</style>
