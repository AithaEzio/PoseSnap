<script lang="ts">
  import {Download} from 'lucide-svelte';
  import * as api from '../api';
  import EngineComponentCard from '../EngineComponentCard.svelte';
  import KimodoControls from './KimodoControls.svelte';
  import HandShapeSettings from './HandShapeSettings.svelte';
  import Qualification from './Qualification.svelte';
  import {textSettings,type TextRuntime} from './types';
  import {bytes,setupPlan,type EngineStatus} from '../engine';
  import type {Settings} from '../types';
  let {settings,engine,runtime,busy=false,stage='',onsave,ondownload,onsetup,onimport,onrefresh,onkimodo}:{settings:Partial<Settings>;engine:EngineStatus|null;runtime:TextRuntime|null;busy?:boolean;stage?:string;onsave:(value:Partial<Settings>)=>Promise<void>;ondownload:(id:string)=>Promise<void>;onsetup:()=>Promise<void>;onimport:(id:string,folder:boolean)=>Promise<void>;onrefresh:()=>Promise<void>;onkimodo:(operation:'load'|'unload')=>Promise<void>}=$props();
  let pending=$state(false),error=$state('');
  const value=$derived(textSettings(settings));
  const kimodoComponents=$derived(engine?.components.filter(c=>c.id.startsWith('kimodo-'))??[]);
  const kimodoMissing=$derived(kimodoComponents.filter(c=>c.state!=='installed'&&c.downloadable));
  const kimodoBytes=$derived(kimodoMissing.reduce((sum,c)=>sum+(c.downloadBytes??0),0));
  const setup=$derived(engine?setupPlan(engine):null);
  async function change(extra:Partial<Settings>){if(busy||pending)return;pending=true;error='';try{await onsave(extra);await onrefresh();}catch(e){error=String(e);}finally{pending=false;}}
  async function importFile(id:string,folder:boolean){pending=true;error='';try{await onimport(id,folder);await onrefresh();}catch(e){error=String(e);}finally{pending=false;}}
  async function download(id:string){if(busy||pending)return;pending=true;error='';try{await ondownload(id);await onrefresh();}catch(e){error=String(e);}finally{pending=false;}}
  async function installKimodo(){if(busy||pending)return;pending=true;error='';try{await onsetup();await onrefresh();}catch(e){error=String(e);}finally{pending=false;}}
</script>
<section class="settings-section text-ai-settings" aria-label="Text to Pose engine">
  <h3>Text to Pose · Kimodo</h3><p>Generate body poses locally. Kimodo's text encoder runs on CPU; body generation uses your NVIDIA GPU.</p>
  <HandShapeSettings enabled={value.textHandShapes} disabled={busy||pending} onchange={enabled=>change({textHandShapes:enabled})}/>
  <Qualification records={runtime?.capabilities}/>
  <p class="setting-note">Refine generated poses in Pose Studio. Floor support and partner contacts remain experimental. No character scale or identity changes.</p>
  <KimodoControls runtime={runtime?.kimodo} busy={busy||pending} {stage} desktop={api.desktop} onruntime={onkimodo}/>
  <div class="text-setup-actions"><button class="primary" disabled={busy||pending||!setup?.pending.length||!!setup.unavailable.length} onclick={installKimodo}><Download size={15}/>{!kimodoComponents.length?'Open desktop app to check components':setup?.pending.length?'Set up Text to Pose':'Kimodo components installed'}</button></div>
  <p class="setting-note">{#if kimodoComponents.length}{bytes(kimodoBytes)} remaining for Kimodo. Setup also installs missing shared PoseSnap components.{:else}Open the desktop app to check component sizes and portable locations.{/if} No cloud inference or CPU motion fallback.</p>
  <div class="engine-components">{#each kimodoComponents as component}<EngineComponentCard {component} locked={busy||pending||!api.desktop} category="Kimodo · Optional" ondownload={download} onimport={importFile}/>{/each}</div>
  {#if error}<p class="text-error" role="alert">{error}</p>{/if}
</section>
