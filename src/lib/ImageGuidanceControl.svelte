<script lang="ts">
  import {tooltip} from './tooltip';
  import {guidanceLabels,type GuidanceMode} from './guidance';
  let {value,disabled=false,advanced=false,onchange,onsetup}:{value:GuidanceMode;disabled?:boolean;advanced?:boolean;onchange:(mode:GuidanceMode)=>void;onsetup?:()=>void}=$props();
</script>
<div class="image-guidance-control" class:advanced>
  <label>Image guidance<select aria-label="Image guidance" {disabled} value={value} use:tooltip={'Applies to the next extraction. Automatic uses the baseline while pose guidance is in qualification.'} onchange={event=>onchange(event.currentTarget.value as GuidanceMode)}>{#each Object.entries(guidanceLabels) as [id,label]}<option value={id}>{label}</option>{/each}</select></label>
  {#if advanced}
    <p>Set the default for extraction. Standard and Detailed maps are available separately under Image maps.</p>
    {#if onsetup}<button class="text-button" {disabled} onclick={onsetup} use:tooltip={'Open Engine settings to explicitly download or import optional image-guidance components.'}>Optional guidance components →</button>{/if}
  {/if}
</div>
<style>
  .image-guidance-control{display:flex;gap:10px;align-items:center;margin:8px 0}.image-guidance-control label{display:flex;align-items:center;gap:10px;font-size:11px;color:var(--muted);flex:1}.image-guidance-control select{min-width:0;flex:1}.advanced{display:grid;gap:10px}.advanced label{display:grid;gap:7px}.advanced p{font-size:11px;color:var(--muted);line-height:1.6;margin:0}.advanced button{justify-self:start}
</style>
