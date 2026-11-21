<script lang="ts">
  import {onDestroy} from 'svelte';
  import {Copy,Check} from 'lucide-svelte';
  let {text,label='Copy prompt',ariaLabel}:{text:string;label?:string;ariaLabel?:string}=$props();
  let pending=$state(false),copied=$state(false),error=$state('');
  let timer:ReturnType<typeof setTimeout>|undefined;
  async function copy(){
    if(pending)return;
    pending=true;copied=false;error='';clearTimeout(timer);
    try{
      if(!navigator.clipboard?.writeText)throw Error('Clipboard unavailable');
      await navigator.clipboard.writeText(text);
      copied=true;timer=setTimeout(()=>copied=false,3000);
    }catch{error='Couldn’t copy. Select the text and copy it manually.';}
    finally{pending=false;}
  }
  onDestroy(()=>clearTimeout(timer));
</script>
<div class="copy-control">
  <button class="compact-button" aria-label={ariaLabel??label} disabled={pending} onclick={copy}>{#if copied}<Check size={12}/>{:else}<Copy size={12}/>{/if}{pending?'Copying…':label}</button>
  <span class="copy-status" role="status">{copied?'Copied to clipboard.':''}</span>
  {#if error}<span class="copy-error" role="alert">{error}</span>{/if}
</div>
<style>
  .copy-control{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.copy-control button{display:inline-flex;align-items:center;gap:6px;font-size:10px;min-height:30px}.copy-status,.copy-error{font-size:10px;line-height:1.6}.copy-status{color:var(--muted)}.copy-error{color:var(--error);flex-basis:100%}
</style>
