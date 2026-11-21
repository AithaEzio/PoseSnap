<script lang="ts">
  import {ArrowLeftRight,ChevronDown,Eye} from 'lucide-svelte';
  import {tooltip} from './tooltip';
  import type {Interaction} from './types';
  let {pending=null,busy=false,showOriginal=false,canApply=true,available=false,onPreview,onOriginal}:{pending?:Interaction|null;busy?:boolean;showOriginal?:boolean;canApply?:boolean;available?:boolean;onPreview:()=>void;onOriginal:(value:boolean)=>void}=$props();
  let expanded=$state(false);
  const diagnostic=$derived(pending?.operation==='spacing'?pending.diagnostics.spacing:undefined);
  $effect(()=>{if(diagnostic)expanded=true;});
</script>
<details class="spacing-options" bind:open={expanded}>
  <summary use:tooltip={'Preview a bounded placement adjustment between people. This changes spacing only; detail fitting is separate.'}><span><ArrowLeftRight size={15}/> Spacing between people <small>Experimental</small></span><ChevronDown size={14}/></summary>
  <p>Use depth cues from the reference to review the layout. Joint rotations, character proportions, floor height, pins and confirmed contacts are kept.</p>
  <p class="depth-note">Camera-relative estimates · Hidden bodies and uncertain masks can leave the layout unchanged. This does not measure physical distance or DAZ world Z.</p>
  {#if !available}<p>Extract both people with a shared reference camera before comparing spacing.</p>{/if}
  {#if diagnostic}
    <section class="spacing-result" aria-label="Spacing preview"><h3><Eye size={14}/> {diagnostic.changed?'Preview · Not applied':'Current layout retained'}</h3><p>{diagnostic.reason}</p>
      {#each diagnostic.translations as movement}<div class="spacing-person"><span>Person {movement.personId}</span><strong>{movement.cameraForwardCm.toFixed(1)} cm</strong></div>{/each}
      {#if diagnostic.changed}<p>Camera-forward adjustment · maximum 25 cm. Inspect Reference and Side before applying.</p>{/if}
      <label class="compare"><input type="checkbox" checked={showOriginal} disabled={busy} onchange={event=>onOriginal(event.currentTarget.checked)}/> Show original layout as a ghost</label>
    </section>
  {/if}
  <button class="secondary" onclick={onPreview} disabled={busy||!canApply||!available} use:tooltip={!canApply?'Local spacing previews run in the desktop app.':'Compare spacing without applying detail or side-profile changes. Your accepted pose stays safe until Apply.'}><Eye size={14}/>{busy?'Comparing…':diagnostic?'Preview spacing again':'Preview spacing'}</button>
</details>
<style>
  .spacing-options{border:1px solid var(--line);border-radius:10px;padding:12px;min-width:0}.spacing-options summary{display:flex;align-items:center;justify-content:space-between;gap:8px;cursor:pointer;font-size:11px;font-weight:600;list-style:none}.spacing-options summary::-webkit-details-marker{display:none}.spacing-options summary span{display:flex;align-items:center;gap:7px;flex-wrap:wrap}.spacing-options summary small{color:var(--accent);font-size:9px}.spacing-options[open] summary{margin-bottom:12px}.spacing-options[open] summary>:global(svg){transform:rotate(180deg)}p,.compare{font-size:11px;line-height:1.65;color:var(--muted);margin:0 0 10px}.depth-note{font-size:10px}.spacing-options button{font-size:11px}.spacing-result{border-top:1px solid var(--line);padding-top:12px;margin:12px 0}.spacing-result h3{display:flex;align-items:center;gap:7px;font-size:11px;margin:0 0 8px}.spacing-person{display:flex;justify-content:space-between;padding:7px 0;font-size:11px}.spacing-person strong{font-variant-numeric:tabular-nums}.compare{display:flex;align-items:flex-start;gap:8px;margin:10px 0 0}.compare input{accent-color:var(--accent)}
</style>
