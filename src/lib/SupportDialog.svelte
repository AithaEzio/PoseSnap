<script lang="ts">
  import {onMount} from 'svelte';
  import {X,Heart,ArrowUpRight} from 'lucide-svelte';
  import {closingSeconds,creatorLinks,supportCopy,type SupportKind} from './support';
  import CreatorLogo from './CreatorLogo.svelte';
  let {kind,ondismiss}:{kind:SupportKind;ondismiss:()=>void}=$props();
  let dialog:HTMLDialogElement,heading:HTMLHeadingElement;
  let seconds=$state(5);
  const copy=$derived(supportCopy[kind]);
  function dismiss(){if(seconds===0)ondismiss();}
  function trapFocus(event:KeyboardEvent){
    if(event.key!=='Tab')return;
    const controls=Array.from(dialog.querySelectorAll<HTMLElement>('a[href],button:not(:disabled)')),first=controls[0],last=controls.at(-1);
    if(event.shiftKey&&(document.activeElement===first||document.activeElement===heading)){event.preventDefault();last?.focus();}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
  }
  onMount(()=>{
    const trigger=document.activeElement as HTMLElement|null,deadline=performance.now()+5000;
    dialog.showModal();heading.focus();
    const update=()=>seconds=closingSeconds(deadline,performance.now());
    const timer=setInterval(update,100);document.addEventListener('visibilitychange',update);
    return()=>{clearInterval(timer);document.removeEventListener('visibilitychange',update);dialog.close();requestAnimationFrame(()=>{const restore=trigger?.isConnected&&!trigger.matches('body,html')&&!trigger.closest('[inert]')?trigger:document.querySelector<HTMLButtonElement>('button[aria-label="Settings"]');restore?.focus();});};
  });
</script>

<dialog bind:this={dialog} class="support-dialog" aria-labelledby="support-title" aria-describedby="support-body" onkeydown={trapFocus} oncancel={event=>{event.preventDefault();dismiss();}}>
  <div class="support-heading"><CreatorLogo/><span>Made with care. Kept growing by you.</span><button class="icon-button" disabled={seconds>0} aria-label="Close support reminder" onclick={dismiss}>{#if seconds>0}<span class="close-count" aria-hidden="true">{seconds}s</span>{:else}<X size={18}/>{/if}</button></div>
  <div class="support-body"><h2 id="support-title" bind:this={heading} tabindex="-1">{copy.title}</h2><p id="support-body">{copy.body}</p></div>
  <div class="support-actions"><a class="primary" href={creatorLinks.kofi} target="_blank" rel="noreferrer"><Heart size={16}/> Support on Ko-fi <ArrowUpRight size={15}/></a><button class="secondary" disabled={seconds>0} onclick={dismiss}>Maybe later{#if seconds>0}<span aria-hidden="true"> · {seconds}s</span>{/if}</button></div>
  <div class="support-footer"><a href={creatorLinks.github} target="_blank" rel="noreferrer">More by Aitha <ArrowUpRight size={12}/></a><p>Support is optional. Thanks for using PoseSnap.</p><span class="close-status" aria-live="polite">{seconds>0?'Closing will be available in a moment.':'You can close this window now.'}</span></div>
</dialog>

<style>
  .support-dialog{position:fixed;inset:0;margin:auto;width:min(440px,calc(100vw - 32px));max-height:calc(100dvh - 32px);overflow:auto;padding:0;background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:15px;box-shadow:0 24px 90px #0007;font-family:inherit}
  .support-dialog::backdrop{background:#080912b8;backdrop-filter:blur(4px)}
  .support-heading{display:flex;align-items:center;gap:13px;padding:20px 22px 17px;border-bottom:1px solid var(--line)}
  .support-heading>span{font-size:11px;line-height:1.7;color:var(--muted);max-width:170px}.support-heading>button{margin-left:auto;align-self:flex-start}
  .close-count{font-size:11px;font-variant-numeric:tabular-nums}
  .support-body{padding:24px 24px 21px}.support-body h2{font-size:23px;font-weight:550;letter-spacing:-.6px;line-height:1.3;outline:none}.support-body p{margin-top:12px;font-size:12px;line-height:1.85;color:var(--muted)}
  .support-actions{display:grid;gap:10px;padding:0 24px}.support-actions>a{display:flex;align-items:center;justify-content:center;gap:8px;text-decoration:none;min-height:42px}.support-actions>button{min-height:39px}.support-actions span{font-variant-numeric:tabular-nums}
  .support-footer{padding:20px 24px;text-align:center}.support-footer>a{display:inline-flex;align-items:center;gap:5px;color:var(--accent);font-size:11px;text-decoration:none}.support-footer a:hover{text-decoration:underline}.support-footer p{font-size:10px;line-height:1.7;color:var(--muted);margin-top:14px}.close-status{display:block;font-size:10px;color:var(--muted);margin-top:6px}
  a:focus-visible{outline:2px solid var(--accent);outline-offset:3px;border-radius:6px}
</style>
