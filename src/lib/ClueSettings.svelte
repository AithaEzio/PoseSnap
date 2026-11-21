<script lang="ts">
  import {tooltip} from './tooltip';
  let {enabled=false,disabled=false,installed=null,onchange}:{enabled?:boolean;disabled?:boolean;installed?:boolean|null;onchange:(enabled:boolean)=>void}=$props();
</script>
<div class="clue-preference">
  <label class="clue-toggle">
    <span><strong>Use CLUE diagnostics</strong><small>Body uncertainty · {enabled?'On':'Off'}</small></span>
    <input type="checkbox" role="switch" aria-label="Use CLUE diagnostics" checked={enabled} {disabled} onchange={event=>onchange(event.currentTarget.checked)} use:tooltip={'Include estimated source uncertainty on your next pose extraction. Off skips loading CLUE. Saved poses and notes are kept.'}/>
  </label>
  <p>{enabled?'Adds regional review notes from the initial body estimate.':'CLUE will not load during pose extraction.'} Applies to your next extraction; saved poses stay intact.</p>
  {#if enabled&&installed===false}<p class="missing">Install or import the optional CLUE component in Engine settings to use these notes.</p>{/if}
</div>
<style>
  .clue-preference{display:grid;gap:8px;margin:12px 0}.clue-toggle{display:flex;align-items:center;justify-content:space-between;gap:16px;cursor:pointer}.clue-toggle span{display:grid;gap:4px}.clue-toggle strong{font-size:12px;font-weight:600}.clue-toggle small,p{font-size:10px;line-height:1.6;color:var(--muted);margin:0}.clue-toggle input{appearance:none;flex-shrink:0;width:36px;height:20px;border:1px solid var(--line);border-radius:12px;background:var(--field,var(--panel));position:relative;cursor:pointer;margin:0}.clue-toggle input::before{content:'';position:absolute;width:12px;height:12px;left:3px;top:3px;border-radius:50%;background:var(--muted)}.clue-toggle input:checked{background:var(--accent);border-color:var(--accent)}.clue-toggle input:checked::before{left:19px;background:var(--panel)}.clue-toggle input:focus-visible{outline:2px solid var(--accent);outline-offset:3px}.clue-toggle input:disabled{opacity:.45;cursor:default}.missing{color:var(--accent)}
</style>
