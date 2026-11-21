<script lang="ts">
  import { Download, ShieldCheck, X, ChevronDown, Cpu, LoaderCircle } from 'lucide-svelte';
  import type { EngineStatus } from './engine';
  import { bytes, engineIndicator, setupPlan, verificationStatus, type SetupProfile } from './engine';
  import EngineLight from './EngineLight.svelte';
  import EngineComponentCard from './EngineComponentCard.svelte';
  import ClueSettings from './ClueSettings.svelte';
  import { tooltip } from './tooltip';
  let { engine, disabled=false, desktop=false, busy=false, stage='', clueEnabled=false, oncluechange, ondownload, onsetup, onimport, onverify, onpause }: {
    engine:EngineStatus|null; disabled?:boolean; desktop?:boolean; busy?:boolean; stage?:string;
    ondownload:(id?:string)=>void; onimport:(id:string,folder:boolean)=>void; onverify:()=>void; onpause:()=>void;
    onsetup:(profile:SetupProfile)=>void;
    clueEnabled?:boolean;oncluechange:(value:boolean)=>void;
  }=$props();
  const locked=$derived(disabled||!!engine?.active||!desktop);
  const indicator=$derived(engineIndicator(engine,desktop,busy,stage));
  const verification=$derived(verificationStatus(engine?.verification));
  let profile=$state<SetupProfile>('all');
  const plan=$derived(engine?setupPlan(engine,profile):null);
</script>
<section class="settings-section engine-settings">
  <h3>Engine &amp; downloads</h3>
  <div class="engine-overview" data-state={indicator.state}>
    <Cpu size={23}/><div><strong use:tooltip={indicator.detail}><EngineLight state={indicator.state} label={'Engine · '+indicator.label}/></strong><p aria-live="polite">{indicator.detail}</p></div>
  </div>
  <p class="setting-note">Download once. Process locally. All components stay inside your portable folder.</p>
  {#if engine}
    {#if engine.gpu}<p class="engine-gpu">GPU: {engine.gpu}</p>{/if}
    {#if engine.active}
      <div class="engine-task" role="status"><LoaderCircle class="engine-spinner" size={16}/><span>{engine.message}</span></div>
      {#if engine.verification?.stage}<div class="engine-transfer"><progress max="1" value={verification.fraction} aria-label="Current component verification progress"></progress><small>{verification.detail}</small></div>{/if}
      {#each engine.transfers as transfer}<div class="engine-transfer"><span>{transfer.label.split(/[\\/]/).pop()}</span><progress max={transfer.total} value={transfer.bytes} aria-label={'Download '+transfer.label}></progress><small>{bytes(transfer.bytes)} / {bytes(transfer.total)}{transfer.bytesPerSecond>0?' · '+bytes(transfer.bytesPerSecond)+'/s':''}</small></div>{/each}
      <button class="secondary wide" onclick={onpause} use:tooltip={'Pause the component task. Partial downloads can resume; working installed files are preserved.'}><X size={15}/> Pause setup</button>
    {:else}
      <div class="engine-setup-profile" role="group" aria-label="PoseSnap setup features">
        <button class="secondary" class:active={profile==='all'} aria-pressed={profile==='all'} disabled={locked} onclick={()=>profile='all'}>All modes</button>
        <button class="secondary" class:active={profile==='pose-expression'} aria-pressed={profile==='pose-expression'} disabled={locked} onclick={()=>profile='pose-expression'}>Pose + Expression</button>
        <button class="secondary" class:active={profile==='guidance'} aria-pressed={profile==='guidance'} disabled={locked} onclick={()=>profile='guidance'}>Image guidance</button>
      </div>
      <p class="setting-note">{profile==='all'?'Extract pose, Pose Studio, Expression Studio and Kimodo Text to Pose.':profile==='guidance'?'Optional CPU depth, normals and albedo maps, including Detailed processing.':'Extract pose, Pose Studio and Expression Studio. Add Kimodo later.'} {plan?.pending.length?bytes(plan.downloadBytes)+' to download · '+bytes(plan.installedBytes)+' to install.':'The selected components are installed.'}</p>
      {#if plan?.unavailable.length}<p class="component-message" role="alert">Setup is incomplete: {plan.unavailable.join(', ')}. Use the current PoseSnap release or the recovery options below.</p>{/if}
      <div class="engine-actions"><button class="primary" onclick={()=>onsetup(profile)} disabled={locked||!plan?.pending.length||!!plan.unavailable.length} use:tooltip={locked?'Finish the current task first.':plan?.pending.length?'Download, verify and install every component for the selected modes.':'All selected components are installed.'}><Download size={15}/>{plan?.pending.length?(profile==='guidance'?'Set up image guidance':'Set up PoseSnap'):'Components installed'}</button><button class="secondary" onclick={onverify} disabled={locked} use:tooltip={'Hash every declared file again and check the private worker. This can take a minute for large runtimes.'}><ShieldCheck size={15}/> Verify all</button></div>
    {/if}
    <div class="engine-components">
      {#each engine.components.filter(c=>!c.id.startsWith('kimodo-')) as component}
        <EngineComponentCard {component} {locked} {ondownload} {onimport}>
          {#if component.id==='clue-body'}<ClueSettings enabled={clueEnabled} disabled={disabled||!!engine.active} installed={component.state==='installed'} onchange={oncluechange}/>{/if}
        </EngineComponentCard>
      {/each}
    </div>
    <details class="component-fallback"><summary use:tooltip={'Recovery options for unavailable sources, offline setup and paused downloads.'}>Offline &amp; recovery options <ChevronDown size={13}/></summary><p>Retry resumes checked partial files. Import folder remains available for offline setup from a matching PoseSnap copy. Component sources and licences are listed above. CLUE is optional and may need separate upstream access.</p><p>The private browser can be repaired before the workspace opens: launch <code>PoseSnap.exe --engine-setup</code>. No system runtime is installed.</p><p>Moving the entire PoseSnap folder preserves installed components and your data. Setup needs temporary free space for verification and safe replacement.</p></details>
  {/if}
</section>
