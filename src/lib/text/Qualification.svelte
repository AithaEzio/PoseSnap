<script lang="ts">
  import { ChevronDown } from 'lucide-svelte';
  import type { CapabilityQualification } from './types';
  let {records=[]}:{records?:CapabilityQualification[]}=$props();
</script>
{#if records.length}
  <details class="component-fallback" aria-label="Workflow qualification">
    <summary>Workflow qualification <ChevronDown size={13}/></summary>
    <p>Engine readiness confirms loading and health. Each workflow has its own tested scope.</p>
    {#each records as record}
      <div class="qualification-row"><strong>{record.label}</strong><span class:qualified={record.status==='qualified'}>{record.status==='qualified'?'Qualified':record.status==='unavailable'?'Unavailable':'Experimental'}</span></div>
      <p>{record.scope} {record.limits.join(' ')}</p>
    {/each}
  </details>
{/if}
<style>
  .qualification-row{display:flex;justify-content:space-between;gap:12px;margin-top:15px;font-size:11px}.qualification-row span{color:var(--muted)}.qualification-row span.qualified{color:var(--success,#64d69c)}p{font-size:11px;line-height:1.55;color:var(--muted);margin:6px 0}
</style>
