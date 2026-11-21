<script lang="ts">
  import {Cpu,Power,PowerOff} from 'lucide-svelte';
  import EngineLight from '../EngineLight.svelte';
  import {kimodoIndicator,type KimodoRuntime} from './types';
  let {runtime,busy=false,stage='',desktop=false,compact=false,onruntime}:{runtime:KimodoRuntime|null|undefined;busy?:boolean;stage?:string;desktop?:boolean;compact?:boolean;onruntime:(operation:'load'|'unload')=>void}=$props();
  const indicator=$derived(kimodoIndicator(runtime,busy,stage,desktop));
</script>
<div class="text-engine-controls" class:compact>
  {#if !compact}<div class="engine-overview" data-state={indicator.state}><Cpu size={23}/><div><strong><EngineLight state={indicator.state} label={indicator.label}/></strong><p aria-live="polite">{indicator.detail}</p></div></div>{/if}
  <div class="engine-actions"><button class="secondary" disabled={busy||!desktop||runtime?.ready||runtime?.phase==='missing'||!runtime} onclick={()=>onruntime('load')}><Power size={14}/> Load Kimodo</button><button class="secondary" disabled={busy||!desktop||!runtime?.ready} onclick={()=>onruntime('unload')}><PowerOff size={14}/> Unload</button></div>
  <p class="setting-note">CPU text encoder + NVIDIA GPU body generator. Unloads after two minutes idle, or earlier when system RAM is low.</p>
</div>
