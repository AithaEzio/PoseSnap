<script lang="ts">
  import {onMount,tick} from 'svelte';
  import type {HistoryItem} from './types';
  let {item,busy,onconfirm,oncancel}:{item:HistoryItem;busy:boolean;onconfirm:()=>Promise<boolean>;oncancel:()=>void}=$props();
  let cancel:HTMLButtonElement;
  let pending=$state(false);
  let failure=$state('');
  const scope=$derived(item.kind==='text'?'This saved text result will be deleted.':item.kind==='expression'?'This saved expression will be deleted.':item.kind==='pose'?'This saved Studio draft will be deleted.':'This cached reference and its saved edits will be deleted. Your original photo is kept.');
  async function confirm(){if(pending||busy)return;pending=true;failure='';try{if(!await onconfirm())failure='Removal could not be confirmed. Refresh History before trying again.';}catch{failure='Removal could not be confirmed. Refresh History before trying again.';}finally{pending=false;}}
  onMount(()=>{const trigger=document.activeElement as HTMLElement;cancel.focus();return()=>{void tick().then(()=>{const target=trigger?.isConnected?trigger:document.querySelector<HTMLElement>('[aria-label="Search history"]');if(target&&!target.closest('[inert]'))target.focus();});};});
</script>
<div class="history-removal" role="alertdialog" tabindex="-1" aria-labelledby="history-removal-title" aria-describedby="history-removal-scope">
  <h3 id="history-removal-title">Remove {item.name}?</h3>
  <p id="history-removal-scope">{scope} This cannot be undone.</p>
  {#if failure}<p role="alert">{failure}</p>{/if}
  <div><button bind:this={cancel} class="secondary" disabled={busy||pending} onclick={oncancel}>Keep it</button><button class="secondary" disabled={busy||pending} onclick={confirm}>{pending?'Removing…':'Remove from history'}</button></div>
</div>
<style>
  .history-removal{padding:16px;border:1px solid var(--line);border-radius:10px;background:var(--deep);margin-bottom:16px}
  h3{font-size:13px;overflow-wrap:anywhere}p{font-size:12px;color:var(--muted);line-height:1.7;margin:8px 0 14px}.history-removal>div{display:flex;gap:8px;flex-wrap:wrap}
</style>
