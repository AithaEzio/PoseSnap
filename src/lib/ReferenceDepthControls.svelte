<script lang="ts">
  import {onMount} from 'svelte';
  import {tooltip} from './tooltip';
  import * as api from './api';
  let {imageId,busy,job}:{imageId:string;busy:boolean;job:<T>(method:string,payload:unknown)=>Promise<T|null>}=$props();
  let scale=$state(''),encoding=$state('camera-z'),calibrationPath=$state(''),message=$state('');
  onMount(()=>{let disposed=false;void api.request<{scaleCm?:number;encoding?:string;camera?:unknown}>('reference_depth',{imageId}).then(value=>{if(!disposed){scale=value.scaleCm===undefined?'':String(value.scaleCm);encoding=value.encoding??'camera-z';if(value.camera)message='Saved camera calibration is available.';}}).catch(e=>{if(!disposed)message=String(e);});return()=>{disposed=true;};});
  async function choose(){const path=await api.pickCalibration();if(typeof path==='string')calibrationPath=path;}
  async function apply(){
    const result=await job('reference_depth',{imageId,scaleCm:Number(scale),encoding,...(calibrationPath?{calibrationPath}:{})});
    if(result)message='Depth settings saved for the next extraction. Your current pose is kept.';
  }
</script>
<details class="reference-maps"><summary use:tooltip={'Known depth units and matching camera calibration. These settings do not change an accepted pose.'}>Depth settings</summary>
  <div class="depth-fields"><label>Centimetres per source value<input type="number" min=".000001" max="1000" step="any" bind:value={scale} disabled={busy}/></label>
  <label>Depth measurement<select bind:value={encoding} disabled={busy}><option value="camera-z">Camera Z</option><option value="ray-distance">Distance along camera ray</option></select></label>
  <button class="secondary" disabled={busy} onclick={choose} use:tooltip={'Import a version 2 camera JSON with matching image dimensions, physical scale and calibrated provenance.'}>Import camera calibration</button>
  <span class="description">{calibrationPath?'Calibration selected':'Known units and calibration are required before extraction.'}</span>
  <button class="secondary" disabled={busy||!scale} onclick={apply}>Save depth settings</button>{#if message}<p role="status">{message}</p>{/if}</div>
</details>
<style>.depth-fields{display:grid;gap:8px;padding:12px}.depth-fields label{display:grid;gap:5px}p{font-size:11px;color:var(--muted)}</style>
