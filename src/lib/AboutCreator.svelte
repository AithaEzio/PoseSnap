<script lang="ts">
  import {onMount} from 'svelte';
  import {Heart,ArrowUpRight} from 'lucide-svelte';
  import {desktop} from './api';
  import {creatorLinks,supportEvent} from './support';
  import CreatorLogo from './CreatorLogo.svelte';
  import {appVersion} from './version';
  let activations=0,disabled=$state(false),saving=false,message=$state('');
  onMount(()=>{if(desktop)void supportEvent({kind:'status'}).then(value=>disabled=value.disabled).catch(()=>{});});
  async function activate(){
    if(disabled||saving||!desktop)return;
    activations++;
    if(activations<33)return;
    saving=true;
    try{const result=await supportEvent({kind:'disable'});disabled=result.disabled;message=disabled?'Automatic support reminders are off.':'';}
    catch{activations=32;message='Could not save this preference. Try again.';}
    finally{saving=false;}
  }
</script>
<section class="about"><img src="/logo.svg" alt=""/><div><h3>PoseSnap <span>v{appVersion}</span></h3><p>Convert photos into Genesis 8 and 9 poses locally for DAZ Studio.</p><small>Company: <button class="company-name" onclick={activate} onkeydown={event=>{if(event.repeat)event.preventDefault();}}>Aitha</button></small></div></section>
{#if message}<p class="creator-message" role="status">{message}</p>{/if}
<section class="creator-support" aria-labelledby="creator-support-title">
  <div class="creator-heading"><CreatorLogo/><div><h3 id="creator-support-title">Want to support the creator?</h3><p>A little support helps Aitha keep PoseSnap growing.</p></div></div>
  <a class="primary creator-action" href={creatorLinks.kofi} target="_blank" rel="noreferrer"><Heart size={15}/> Support on Ko-fi <ArrowUpRight size={14}/></a>
  <a class="creator-github" href={creatorLinks.github} target="_blank" rel="noreferrer">Explore Aitha’s projects on GitHub <ArrowUpRight size={12}/></a>
</section>
<style>
  .company-name{display:inline;background:none;color:inherit;padding:0;border:0;border-radius:2px;font:inherit;line-height:inherit;vertical-align:baseline}
  .creator-message{font-size:11px;color:var(--muted);line-height:1.7;margin:12px 0}
  .creator-support{border:1px solid var(--line);border-radius:12px;background:var(--deep);padding:16px;margin:22px 0 26px}
  .creator-heading{display:flex;align-items:center;gap:13px;margin-bottom:16px}
  .creator-heading h3{font-size:13px;font-weight:600;line-height:1.5}.creator-heading p{font-size:11px;color:var(--muted);line-height:1.7;margin-top:5px}
  .creator-action{display:flex;align-items:center;justify-content:center;gap:8px;text-decoration:none;min-height:39px}.creator-github{display:flex;align-items:center;justify-content:center;gap:5px;font-size:11px;color:var(--accent);text-decoration:none;margin-top:14px;line-height:1.7}.creator-github:hover{text-decoration:underline}
  a:focus-visible{outline:2px solid var(--accent);outline-offset:3px;border-radius:6px}
</style>
