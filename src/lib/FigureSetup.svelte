<script lang="ts">
  import { onDestroy } from 'svelte';
  import { ChevronDown, Rotate3D, RotateCcw } from 'lucide-svelte';
  import { facingPreset, facingPresets, type FacingPreset } from './figureSetup';
  import { liveNumber } from './liveNumber';
  import { tooltip } from './tooltip';
  import type { Pose } from './types';
  let { pose, baseline, height, group = false, linked = $bindable(false), busy = false, onFacing, onHeight, onEditing }:
    { pose: Pose; baseline: Pose; height: number; group?: boolean; linked?: boolean; busy?: boolean;
      onFacing: (value: FacingPreset) => void; onHeight: (value: number) => void; onEditing: (active: boolean) => void } = $props();
  let open = $state(true), sliding = false;
  const preset = $derived(facingPreset(pose, baseline));
  const initialLabel = $derived(pose.origin === 'editor' && !pose.studioSource ? 'Initial orientation' : 'As extracted');
  const scope = $derived(group && linked ? 'Whole scene' : 'Mannequin ' + pose.personId);
  function startSlide() { if (!busy && !sliding) { sliding = true; onEditing(true); } }
  function endSlide() { if (sliding) { sliding = false; onEditing(false); } }
  onDestroy(endSlide);
</script>

<details class="figure-setup" bind:open>
  <summary use:tooltip={'Quick whole-figure orientation and floor placement. Changes are saved with your pose and support Undo.'}><Rotate3D size={13}/><span>Facing &amp; floor</span><small>{scope}</small><ChevronDown size={13}/></summary>
  <div class="setup-body">
    {#if group}<label class="setup-scope" use:tooltip={'Move and turn the mannequins together, preserving their spacing. Individual joint rotations still affect the selected mannequin.'}><input type="checkbox" bind:checked={linked} disabled={busy}/> Adjust partners together</label>{/if}
    <label class="setup-label" for="studio-facing">Figure facing</label>
    <div class="facing-row">
      <select id="studio-facing" value={preset} disabled={busy} onchange={e=>onFacing(e.currentTarget.value as FacingPreset)} use:tooltip={'Turn relative to the pose when editing began. Joint edits stay intact; the camera view stays where you left it.'}>
        {#if preset==='custom'}<option value="custom" disabled>Custom orientation</option>{/if}
        {#each facingPresets as item}<option value={item.id}>{item.id==='extracted'?initialLabel:item.label}</option>{/each}
      </select>
      <button class="icon-button" disabled={busy||preset==='extracted'} aria-label="Reset figure facing" onclick={()=>onFacing('extracted')} use:tooltip={'Restore '+initialLabel.toLowerCase()+'. Keep joint edits and floor clearance. Undo restores this adjustment.'}><RotateCcw size={13}/></button>
    </div>
    <div class="height-heading"><label class="setup-label" for="studio-floor-height">Floor offset</label><small>cm</small></div>
    <div class="height-row">
      <input type="range" aria-label="Adjust floor offset" min={Math.min(-30,Math.floor(height))} max={Math.max(30,Math.ceil(height))} step="0.5" value={height} disabled={busy} onpointerdown={e=>{e.currentTarget.setPointerCapture(e.pointerId);startSlide();}} onpointerup={endSlide} onpointercancel={endSlide} onkeydown={e=>{if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End','PageUp','PageDown'].includes(e.key))startSlide();}} onkeyup={endSlide} onblur={endSlide} onchange={endSlide} oninput={e=>onHeight(e.currentTarget.valueAsNumber)} use:tooltip={'Raise or lower '+scope.toLowerCase()+'. Zero aligns the lowest rig point with the floor. One drag is one Undo step.'}/>
      <input id="studio-floor-height" type="number" step="0.5" disabled={busy} use:liveNumber={{value:height,context:pose.imageId+'/'+pose.personId+'/'+linked+'/floor',onValue:onHeight,onEditing}} use:tooltip={'Offset in centimetres from the preview floor. Negative values go below the floor; positive values raise the figure.'}/>
    </div>
    <button class="text-button" disabled={busy||Math.abs(height)<.0001} onclick={()=>onHeight(0)} use:tooltip={'Align the lowest rig point with the floor. Horizontal and depth positions stay intact. Undo restores the height.'}><RotateCcw size={12}/> Place on floor</button>
    <p class="setup-caption">{group&&linked?'Scene turns and moves together.':'Adjusts the whole selected mannequin.'} Pins stay active.</p>
  </div>
</details>

<style>
  .figure-setup{margin:12px 0;border:1px solid var(--line);border-radius:8px;background:var(--deep);overflow:hidden}
  summary{display:flex;align-items:center;gap:6px;padding:11px 10px;font-size:11px;list-style:none;cursor:pointer}
  summary::-webkit-details-marker{display:none}summary span{font-weight:600}summary small{margin-left:auto;white-space:nowrap;font-size:9px;color:var(--muted)}
  .figure-setup[open] summary :global(svg:last-child){transform:rotate(180deg)}
  .setup-body{padding:0 10px 10px}.setup-label{font-size:10px;color:var(--muted)}
  .facing-row{display:flex;gap:5px;margin:6px 0 12px}.facing-row select{width:100%;min-width:0;flex:1;font-size:11px;height:32px;padding:5px 7px;border:1px solid var(--line);border-radius:6px;background-color:var(--panel)}.facing-row .icon-button{flex-shrink:0;width:28px;height:32px}
  .height-heading{display:flex;align-items:center;justify-content:space-between}.height-heading small{color:var(--subtle);font-size:9px}
  .height-row{display:grid;grid-template-columns:minmax(0,1fr) 62px;align-items:center;gap:8px;margin:6px 0}.height-row input[type=range]{width:100%;min-width:0;margin:0;accent-color:var(--accent)}.height-row input[type=number]{width:100%;min-width:0;height:31px;padding:5px;border:1px solid var(--line);border-radius:5px;background:var(--panel);font-size:11px}
  .setup-scope{display:flex;align-items:center;gap:6px;font-size:10px;color:var(--muted);margin:0 0 12px;line-height:1.5}.setup-scope input{margin:0;accent-color:var(--accent)}
  .setup-body .text-button{font-size:10px;margin:3px 0}.setup-caption{font-size:9px;line-height:1.5;margin:5px 0 0;color:var(--subtle)}
</style>
