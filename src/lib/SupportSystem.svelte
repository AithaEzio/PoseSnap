<script lang="ts">
  import {onMount} from 'svelte';
  import {desktop} from './api';
  import {idleForReminder,supportEvent,type SupportClaim} from './support';
  import SupportDialog from './SupportDialog.svelte';
  let {ready,blocked,open=$bindable(false)}:{ready:boolean;blocked:boolean;open?:boolean}=$props();
  let claim=$state<SupportClaim|null>(null);
  onMount(()=>{
    if(!desktop){
      if(import.meta.env.DEV){
        const params=new URLSearchParams(location.search),kind=params.get('support');
        if(params.has('validation')&&(kind==='welcome'||kind==='frequent')){
          const timer=setInterval(()=>{if(ready&&!blocked){clearInterval(timer);claim={id:'development',kind};open=true;}},200);
          return()=>clearInterval(timer);
        }
      }
      return;
    }
    let disposed=false,checking=false,opened=false,disabled=false,lastActivity=performance.now(),nextCheck=0,wasBlocked=true;
    const pointers=new Set<number>();
    const activity=()=>lastActivity=performance.now();
    const down=(event:PointerEvent)=>{pointers.add(event.pointerId);activity();};
    const up=(event:PointerEvent)=>{pointers.delete(event.pointerId);activity();};
    const blur=()=>{pointers.clear();activity();};
    async function check(){
      const now=performance.now();
      const input=document.activeElement?.matches('input,textarea,select,[contenteditable="true"]')??false;
      const unavailable=!ready||blocked||input||pointers.size>0||document.visibilityState!=='visible'||!document.hasFocus();
      if(unavailable||wasBlocked)lastActivity=now;
      wasBlocked=unavailable;
      if(disposed||checking||disabled||!ready)return;
      if(now<nextCheck)return;
      checking=true;nextCheck=now+5000;
      try{
        if(!opened){await supportEvent({kind:'workspace'});opened=true;}
        const status=await supportEvent({kind:'status'});
        if(disposed)return;
        if(status.disabled){disabled=true;claim=null;open=false;return;}
        if(claim||!status.pending||status.waitMs>0||!idleForReminder(lastActivity,performance.now(),blocked||input||pointers.size>0,document.visibilityState==='visible'&&document.hasFocus()))return;
        const result=await supportEvent({kind:'claim'});
        if(result.claim){
          // No UI mutation can happen before the durable claim. If work starts
          // during IPC, consume it quietly rather than interrupt that work.
          if(disposed||!idleForReminder(lastActivity,performance.now(),blocked||pointers.size>0,document.visibilityState==='visible'&&document.hasFocus())){const id=result.claim.id;setTimeout(()=>void supportEvent({kind:'dismiss',claimId:id}).catch(()=>{}),5000);return;}
          claim=result.claim;open=true;
        }
      }catch{/* Optional service failure must never surface as an app error. */}
      finally{checking=false;}
    }
    const timer=setInterval(()=>void check(),1000);
    window.addEventListener('pointerdown',down,true);window.addEventListener('pointerup',up,true);window.addEventListener('pointercancel',up,true);
    window.addEventListener('keydown',activity,true);window.addEventListener('wheel',activity,{passive:true,capture:true});window.addEventListener('blur',blur);
    document.addEventListener('visibilitychange',activity);
    return()=>{disposed=true;clearInterval(timer);window.removeEventListener('pointerdown',down,true);window.removeEventListener('pointerup',up,true);window.removeEventListener('pointercancel',up,true);window.removeEventListener('keydown',activity,true);window.removeEventListener('wheel',activity,true);window.removeEventListener('blur',blur);document.removeEventListener('visibilitychange',activity);};
  });
  async function dismiss(){const id=claim?.id;if(!id)return;try{await supportEvent({kind:'dismiss',claimId:id});}catch{/* The durable claim still prevents repeats. */}claim=null;open=false;}
</script>
{#if claim}<SupportDialog kind={claim.kind} ondismiss={dismiss}/>{/if}
