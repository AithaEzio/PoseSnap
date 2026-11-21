<script lang="ts">
  import {Layers3,ChevronDown,ScanLine} from 'lucide-svelte';
  import {tooltip} from './tooltip';
  import type {GuidanceInspection,MapQuality,ReferenceKind} from './guidance';
  let {imageId,kind='photo',busy=false,job,onsetup}:{imageId:string;kind?:ReferenceKind;busy?:boolean;job:<T>(method:string,payload:unknown)=>Promise<T|null>;onsetup?:()=>void}=$props();
  let inspection=$state<GuidanceInspection|null>(null),selected=$state('original'),opened=$state(false);
  let provider=$state<'image'|'geometry'>('image'),mapQuality=$state<MapQuality>('standard');
  const context=$derived([imageId,kind,provider,mapQuality].join('/'));
  function clearInspection(){inspection=null;selected='original';}
  async function inspect(map='original'){
    if(busy)return;
    const request=context;
    const result=await job<GuidanceInspection>('guidance_inspect',{imageId,map,provider,mapQuality});
    if(result&&request===context){inspection=result;selected=map;}
  }
</script>
<details class="reference-maps" bind:open={opened}>
  <summary use:tooltip={'Inspect prepared maps without changing your pose, camera calibration or current extraction settings.'}><span><Layers3 size={13}/> Image maps</span><ChevronDown size={13}/></summary>
  <div class="map-content">
    <div class="map-toolbar">
      <button class="secondary" disabled={busy} onclick={()=>inspect()} use:tooltip={'Prepare or reuse cached maps for this reference.'}><ScanLine size={13}/>{inspection?'Refresh maps':'Inspect maps'}</button>
      {#if kind==='photo'}
        <select aria-label="Reference map source" disabled={busy} value={provider} onchange={event=>{provider=event.currentTarget.value==='geometry'?'geometry':'image';clearInspection();}} use:tooltip={'ShadeNet prepares image maps. Geometry maps reuse prepared MoGe-2 geometry.'}><option value="image">Image maps</option><option value="geometry">Geometry maps</option></select>
        {#if provider==='image'}
          <select aria-label="Image map detail" disabled={busy} value={mapQuality} onchange={event=>{mapQuality=event.currentTarget.value==='detailed'?'detailed':'standard';clearInspection();}} use:tooltip={'Detailed runs six passes and takes longer. This setting is for map inspection.'}><option value="standard">Standard</option><option value="detailed">Detailed</option></select>
        {/if}
      {/if}
    </div>
    {#if inspection}
      <div class="map-tabs" role="group" aria-label="Reference map display">{#each [['original','Original'],['depth','Depth'],['normals','Normals'],['albedo','Albedo']] as [id,label]}<button class="secondary" class:active={selected===id} aria-pressed={selected===id} disabled={busy||!inspection.available.includes(id)} use:tooltip={inspection.available.includes(id)?'Inspect '+label.toLowerCase()+' without replacing the reference or accepted pose.':'This map is unavailable for this input or provider.'} onclick={()=>inspect(id)}>{label}</button>{/each}</div>
      {#if inspection.url}<img src={inspection.url} alt={selected+' inspection for the selected reference'}/>{/if}
      <p role="status">{inspection.message??(selected==='depth'?(inspection.evidence.depthEncoding==='relative-unverified'?'Relative depth · Direction and metric scale unverified.':'Predicted surface depth · Physical distance remains uncertain.'):selected==='normals'?'Visible surface orientation · Hidden joint twist remains uncertain.':selected==='albedo'?'Predicted base colour · Not additional geometry.':'Original reference · Your accepted pose is kept.')}</p>
      {#if inspection.evidence.state==='missing'&&onsetup}<button class="text-button" disabled={busy} onclick={onsetup}>Get optional image guidance files →</button>{/if}
      {#if inspection.evidence.cacheHit}<small>Using cached maps</small>{/if}
    {:else}<p>View depth, surface orientation and base colour separately. Map inspection keeps your accepted pose.</p>{/if}
  </div>
</details>
<style>
  .reference-maps{margin:10px 0;border:1px solid var(--line);border-radius:8px;background:var(--field,var(--panel))}summary{list-style:none;display:flex;justify-content:space-between;align-items:center;padding:10px 12px;cursor:pointer;font-size:11px}summary span{display:flex;gap:7px;align-items:center}summary::-webkit-details-marker{display:none}.map-content{padding:0 12px 12px;display:grid;gap:10px}.map-toolbar,.map-tabs{display:flex;align-items:center;gap:7px;flex-wrap:wrap}.map-toolbar select{flex:1;min-width:110px}.map-tabs button{flex:1;min-width:58px;padding:7px;font-size:10px}.map-tabs .active{color:var(--accent);border-color:var(--accent)}img{width:100%;height:auto;max-height:360px;object-fit:contain;border-radius:6px;background:var(--canvas,var(--panel))}p,small{font-size:10px;line-height:1.6;color:var(--muted);margin:0}summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
</style>
