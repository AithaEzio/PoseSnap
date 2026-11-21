<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { ArrowRight } from 'lucide-svelte';
  import { dismissTooltips } from './tooltip';
  import { appVersion } from './version';
  let { progress, label, ready, workspaceReady=false, engineLabel='Checking components', checksLabel=null, attention=false, reduced = false, onclose }: { progress: number | null; label: string; ready: boolean; workspaceReady?:boolean; engineLabel?:string; checksLabel?:string|null; attention?:boolean; reduced?: boolean; onclose: () => void } = $props();
  let revealing = $state(false), entered = $state(false), timer: ReturnType<typeof setTimeout>, entryTimer: ReturnType<typeof setTimeout>, skip: HTMLButtonElement;
  onMount(() => { dismissTooltips(); skip.focus(); entryTimer = setTimeout(() => entered = true, 3000); });
  $effect(() => { if (ready && entered && !revealing) { revealing = true; timer = setTimeout(onclose, reduced || matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 520); } });
  onDestroy(() => { clearTimeout(timer); clearTimeout(entryTimer); });
</script>
<div class="curtain" class:revealing role="dialog" aria-modal="true" aria-label="Starting PoseSnap">
  <div class="curtain-pane left"></div><div class="curtain-pane right"></div>
  <div class="curtain-content">
    <div class="curtain-brand"><div class="curtain-logo"><img src="/logo.svg" alt="PoseSnap"/></div><h1>Pose<span>Snap</span></h1><p>A moment. A pose. Yours.</p></div>
    <div class="curtain-launch"><span class="eyebrow">YOUR LOCAL POSE STUDIO</span><div class="startup-progress" role="status" aria-live="polite"><span>{label}</span>{#if !attention}<progress max="100" value={progress ?? undefined} aria-label="Completed startup checks"></progress>{/if}{#if checksLabel}<small>{checksLabel}</small>{/if}</div>
      <div class="startup-checks"><span class:complete={workspaceReady}><i></i>Workspace <b>{workspaceReady?'Ready':'Preparing'}</b></span><span class:complete={engineLabel==='Ready'} class:attention><i></i>Engine <b>{engineLabel}</b></span></div>
      <button class="curtain-skip" bind:this={skip} onclick={onclose}>{attention?'Open engine setup':'Open workspace'} <ArrowRight size={15}/><kbd>Esc</kbd></button>
      <p class="curtain-credit">Made by <strong>Aitha</strong> and AI<span>💕</span>.</p><small>v{appVersion} · Everything stays on your PC</small>
    </div>
  </div>
</div>
