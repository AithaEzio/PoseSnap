<script lang="ts">
  import {tooltip} from './tooltip';
  let {enabled=true,disabled=false,active=true,scope='Genesis Smart Fit',onchange}:{enabled?:boolean;disabled?:boolean;active?:boolean;scope?:string;onchange:(enabled:boolean)=>void}=$props();
</script>
<div class="crop-setting">
  <label><span><strong>Zero cropped joints</strong><small>{enabled?'On':'Off'} · {scope}</small></span>
    <input type="checkbox" role="switch" aria-label="Zero cropped joints" checked={enabled} {disabled} onchange={event=>onchange(event.currentTarget.checked)} use:tooltip={'Applies to the next Smart Fit extraction or interaction rebuild. Existing poses and Studio edits stay intact. Hidden joints inside the photo remain estimates.'}/>
  </label>
  <p>Start joints outside the photo at neutral. Keep the visible pose.</p>
  {#if !active}<p>Pure keeps its SAM estimate. This option applies when using Smart Fit.</p>{/if}
</div>
<style>
  .crop-setting{display:grid;gap:8px;margin:12px 0}.crop-setting label{display:flex;align-items:center;justify-content:space-between;gap:16px;cursor:pointer}.crop-setting label span{display:grid;gap:4px}.crop-setting strong{font-size:12px;font-weight:600}.crop-setting small,p{font-size:10px;line-height:1.6;color:var(--muted);margin:0}.crop-setting input{appearance:none;flex-shrink:0;width:36px;height:20px;border:1px solid var(--line);border-radius:12px;background:var(--field,var(--panel));position:relative;cursor:pointer;margin:0}.crop-setting input::before{content:'';position:absolute;width:12px;height:12px;left:3px;top:3px;border-radius:50%;background:var(--muted)}.crop-setting input:checked{background:var(--accent);border-color:var(--accent)}.crop-setting input:checked::before{left:19px;background:var(--panel)}.crop-setting input:focus-visible{outline:2px solid var(--accent);outline-offset:3px}.crop-setting input:disabled{opacity:.45;cursor:default}
</style>
