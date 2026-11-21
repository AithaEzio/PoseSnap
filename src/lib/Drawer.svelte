<script lang="ts">
  import { onMount } from 'svelte';
  import { X, ChevronDown } from 'lucide-svelte';
  import { tooltip } from './tooltip';
  import type { Snippet } from 'svelte';
  let { title, subtitle = '', onclose, children, navigation, reveal=0, returnFocus }: { title: string; subtitle?: string; onclose: () => void; children: Snippet; navigation?: Snippet; reveal?:number;returnFocus?:HTMLElement } = $props();
  let heading: HTMLHeadingElement, trigger: HTMLElement | undefined;
  let previousTitle: string | undefined;
  let collapsed=$state(false);
  $effect(()=>{reveal;collapsed=false;});
  $effect(() => { if (previousTitle !== undefined && title !== previousTitle) { collapsed=false;trigger = document.activeElement as HTMLElement; heading?.focus(); } previousTitle = title; });
  onMount(() => { trigger = document.activeElement as HTMLElement; heading.focus(); return () => {const target=returnFocus??trigger;if(target?.isConnected)target.focus();}; });
</script>
<div class="drawer" class:collapsed id="workspace-drawer" role="dialog" aria-modal="false" aria-label={title} tabindex="-1">
  <div class="drawer-heading"><div><h2 bind:this={heading} tabindex="-1">{title}</h2><p>{subtitle}</p></div><div class="drawer-buttons"><button class="icon-button" aria-label={(collapsed?'Expand ':'Collapse ')+title} aria-expanded={!collapsed} aria-controls="drawer-content" use:tooltip={(collapsed?'Expand ':'Collapse ')+title+' without closing it.'} onclick={()=>collapsed=!collapsed}><ChevronDown size={16}/></button><button class="icon-button" aria-label={'Close ' + title} use:tooltip={'Close ' + title + ' · Escape'} onclick={onclose}><X size={18}/></button></div></div>
  {#if navigation}<div class="drawer-navigation" hidden={collapsed} inert={collapsed}>{@render navigation()}</div>{/if}
  <div class="drawer-body" id="drawer-content" hidden={collapsed} inert={collapsed}>{@render children()}</div>
</div>
