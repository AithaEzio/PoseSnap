<script lang="ts">
  import {onMount,untrack} from 'svelte';
  import {Sparkles,ChevronDown,ChevronLeft,ChevronRight,ArrowRight,X,Check,Undo2,LoaderCircle,Download,ArrowUpRight,Settings2,MessageSquareText,Cpu,Info,BookOpen,AlertCircle} from 'lucide-svelte';
  import KimodoControls from './KimodoControls.svelte';
  import HandShapeSettings from './HandShapeSettings.svelte';
  import PoseThumbnail from './PoseThumbnail.svelte';
  import Preview from '../Preview.svelte';
  import HeadPreview from '../expression/HeadPreview.svelte';
  import PreviewNotice from '../PreviewNotice.svelte';
  import {tooltip} from '../tooltip';
  import {waitForDaz} from '../expression/handoff';
  import * as api from '../api';
  import {recordCreation} from '../support';
  import type {Pose,RigId,Settings,Theme,HistoryItem} from '../types';
  import {textSettings,actorsFromPoses,canVaryPreview,profiles,type PoseCharacter,type TextActor,type TextRuntime,type TextResult,type TextIntent,type TextExpression} from './types';
  let {active,watchRuntime=false,theme,settings,dazExecutable,onsettings,onpromptguide,onpreferences,ondaz,onbody,onexpression,onhistory,onstatus,onsupportblocked=()=>{},ontask}:{active:boolean;watchRuntime?:boolean;theme:Theme;settings:Partial<Settings>;dazExecutable:string;onsettings:()=>void;onpromptguide:()=>void;onpreferences:(value:Partial<Settings>)=>Promise<void>;ondaz:()=>void;onbody:(poses:Pose[])=>void;onexpression:(value:TextExpression)=>void;onhistory:()=>void;onstatus:(status:TextRuntime|null)=>void;onsupportblocked?:(blocked:boolean)=>void;ontask:(busy:boolean,label:string)=>void}=$props();
  let prompt=$state('');
  let promptCollapsed=$state(false),previewCollapsed=$state(false);
  let actors=$state<TextActor[]>([{id:1,rigId:'g8f'}]);
  let busy=$state(false),stage=$state(''),percent=$state(0),error=$state(''),notice=$state(''),runtime=$state<TextRuntime|null>(null);
  let interpreted=$state<TextIntent|null>(null),candidate=$state<TextResult|null>(null),accepted=$state<TextResult|null>(null),undo=$state<TextResult[]>([]);
  let variationBatch=$state<{id:string;signature:string}[]>([]);
  let style=$state<PoseCharacter>('natural'),choices=$state<TextResult[]>([]),notesOpen=$state(false);
  let selected=$state(1),previewMode=$state<'pose'|'expression'>('pose'),view=$state('front'),cameraProfile=$state<string|null>('front'),reset=$state(0),placement=$state<'keep'|'floor'>('floor');
  let currentJob='',revision=0,validationShown=false;
  let notesTrigger=$state<HTMLButtonElement>(),notesClose=$state<HTMLButtonElement>();
  const labels:Record<RigId,string>={g8f:'Genesis 8 Female',g8m:'Genesis 8 Male',g9:'Genesis 9'};
  const handShapes=$derived(textSettings(settings).textHandShapes);
  const shown=$derived(candidate??accepted);
  const displayedActors=$derived(shown?.poses.map(p=>({id:p.personId,rigId:p.rigId}))??[]);
  const canVary=$derived(canVaryPreview(actors,shown,prompt,style,handShapes));
  const selectedPose=$derived(shown?.poses.find(p=>p.personId===selected)??null);
  const selectedExpression=$derived(shown?.expressions.find(e=>e.actorId===selected)??null);
  const canExport=$derived(!!accepted&&!candidate&&shown?.id===accepted.id&&!!selectedPose);
  const examples=$derived(actors.length===2?['Both holding hands','Both in a front hug','Person 1 left hand on Person 2 right shoulder']:['A relaxed standing pose','She is jumping with both hands up','A confident pose']);
  const fingerprint=$derived(JSON.stringify([prompt,actors,style,handShapes]));
  let previewFingerprint=$state('');
  $effect(()=>{if(displayedActors.length&&!displayedActors.some(a=>a.id===selected))selected=displayedActors[0].id;});
  $effect(()=>{if(notesOpen)notesClose?.focus();});
  $effect(()=>{if(candidate&&previewFingerprint!==fingerprint){candidate=null;choices=[];interpreted=null;notice='Inputs changed. Preview again before applying.';}});
  $effect(()=>onsupportblocked(!!candidate||!!error||notesOpen));
  $effect(()=>{if(active)untrack(()=>{void refresh();if(import.meta.env.DEV&&!api.desktop)void developmentChoices();});});
  $effect(()=>{if((active||watchRuntime)&&runtime?.kimodo.ready&&!busy){const timer=setTimeout(()=>void refresh(),61000);return()=>clearTimeout(timer);}});
  export async function refresh(){if(!api.desktop)return;try{runtime=await api.request<TextRuntime>('text_status');onstatus(runtime);}catch(e){if(active)error=String(e);}}
  async function developmentChoices(){
    if(validationShown||new URLSearchParams(location.search).get('scenario')!=='text-choices')return;
    validationShown=true;
    try{const params=new URLSearchParams(location.search);const response=await fetch('/__text-choices?output=pose&generator=kimodo&sample='+encodeURIComponent(params.get('sample')??'dance-1'));if(!response.ok)throw Error('Generate the isolated Kimodo validation fixture first.');const result:TextResult=await response.json();prompt=result.prompt;actors=actorsFromPoses(result.poses);choices=(result.alternatives??[result]).map(c=>({...c,output:'pose',expressions:[]}));candidate=choices[0];variationBatch=choices.map(c=>({id:c.id,signature:c.signature}));interpreted=candidate.intent;previewFingerprint=fingerprint;if(params.get('state')==='accepted'){accepted=candidate;candidate=null;choices=[];}notice='Development preview of real worker candidates. Apply and DAZ remain desktop-only.';reset++;}catch(e){error=String(e);}
  }
  export async function manageKimodo(operation:'load'|'unload'){
    const result=await work<TextRuntime>(operation==='load'?'Loading Kimodo':'Unloading Kimodo',()=>request('text_kimodo_'+operation,{}));
    if(result){runtime=result;onstatus(result);notice=operation==='load'?'Kimodo loaded. Inspect the body preview before Apply.':'Kimodo unloaded. Installed files and accepted results are kept.';}else await refresh();
  }
  function progress(label:string,value:number){stage=label;percent=value;ontask(true,label);}
  async function work<T>(label:string,fn:()=>Promise<T>):Promise<T|null>{if(busy)return null;busy=true;error='';notice='';currentJob=crypto.randomUUID();const token=++revision;progress(label,0);try{const result=await fn();return token===revision?result:null;}catch(e){if(token===revision)error=String(e);return null;}finally{if(token===revision){busy=false;currentJob='';ontask(false,'');}}}
  async function request<T>(method:string,payload:unknown){if(!busy||!currentJob)throw Error('Cancelled. Your accepted result is kept.');const job=currentJob,token=revision,result=await api.request<T>(method,payload,job);if(job!==currentJob||token!==revision)throw Error('Cancelled result ignored.');return result;}
  export async function cancel(){
    revision++;currentJob='';
    try{if(api.desktop)await api.cancel();notice='Cancelled. Your accepted result and prompt are kept.';}
    catch(e){error='Cancellation could not be confirmed. The engine may still be finishing; your accepted result and prompt are kept. '+String(e);}
    finally{busy=false;stage='';ontask(false,'');}
    await refresh();
  }
  export function closeNotes(){if(!notesOpen)return false;notesOpen=false;notesTrigger?.focus();return true;}
  function count(value:number){if(busy)return;actors=value===1?actors.slice(0,1):[actors[0],{id:2,rigId:actors[0].rigId}];selected=1;candidate=null;choices=[];interpreted=null;notice='Characters changed. Preview again before applying.';}
  async function changeHands(value:boolean){await work('Saving hand-shape preference',()=>onpreferences({textHandShapes:value}));}
  export async function preview(variation=false){
    if(!prompt.trim()||busy||variation&&!canVary)return;
    const start=fingerprint,variationSource=variation?shown:null,operationId=crypto.randomUUID(),actorCount=actors.length;
    const previousChoices=variationSource?(variationBatch.some(c=>c.id===variationSource.id)?variationBatch:[{id:variationSource.id,signature:variationSource.signature}]):[];
    const result=await work<TextResult|null>('Preparing your body direction',async()=>{
      const payload={output:'pose',mode:'create',actors:actors.map(({id,rigId})=>({id,rigId})),prompt,bodyGenerator:'kimodo',creative:true,candidateCount:3,style,handShapes,variationOf:variationSource?{id:variationSource.id,signature:variationSource.signature,choices:previousChoices.map(c=>({id:c.id,signature:c.signature}))}:undefined,variationSeed:crypto.getRandomValues(new Uint32Array(1))[0]};
      const planned=await request<{intent:TextIntent;contextSignature:string;runtime:TextRuntime}>('text_plan',payload);runtime=planned.runtime;onstatus(runtime);interpreted=planned.intent;
      if(planned.intent.status!=='plan')return null;
      progress('Fitting your body preview',40);
      return request<TextResult>('text_generate',{...payload,intent:planned.intent,contextSignature:planned.contextSignature});
    });
    if(result&&start===fingerprint){choices=result.alternatives??[result];candidate=choices[0];variationBatch=choices.map(c=>({id:c.id,signature:c.signature}));previewFingerprint=start;selected=1;previewMode='pose';reset++;recordCreation(operationId,actorCount);notice=result.choiceDiagnostics&&result.choiceDiagnostics.returned<result.choiceDiagnostics.requested?`${choices.length} distinct ${choices.length===1?'choice fits':'choices fit'} these constraints. Your accepted result is kept until Apply.`:'Preview only. Choose a result, then Apply or Cancel.';await refresh();}
  }
  async function apply(){if(!candidate)return;const value=candidate;const result=await work<TextResult>('Keeping your result',()=>request('text_accept',{id:value.id,signature:value.signature}));if(result){if(accepted)undo=[...undo.slice(-19),accepted];accepted=result;candidate=null;choices=[];notice='Body pose accepted. Open it in Pose Studio to refine the joints.';onhistory();}}
  function undoResult(){if(busy||!undo.length)return;accepted=undo.at(-1)!;undo=undo.slice(0,-1);candidate=null;actors=actorsFromPoses(accepted.poses);selected=actors[0]?.id??1;previewMode='pose';reset++;notice='Previous accepted result restored.';}
  async function saveOutput(applyDaz:boolean){if(!accepted||!canExport||busy)return;if(applyDaz&&!dazExecutable){ondaz();return;}const value=accepted;
    await work('Preparing the selected actor for DAZ',async()=>{const path=applyDaz?null:await api.savePose('PoseSnap-text-'+selected);if(!applyDaz&&!path)return;const args={id:value.id,actorId:selected,placement,path,executable:dazExecutable};const result=applyDaz?await waitForDaz(request('text_apply',args),()=>api.cancel()):await request('text_export',args);notice=applyDaz?'Selected actor applied. DAZ has one Undo step for this result.':'Selected actor saved as a DUF.';return result;});
  }
  export async function restore(item:HistoryItem){const value=await work<TextResult>('Opening text history',()=>request('text_read',{id:item.id}));if(value){if(!value.poses.length&&value.expressions[0]){onexpression(value.expressions[0]);return;}accepted=value;candidate=null;choices=[];interpreted=null;prompt=value.prompt;actors=actorsFromPoses(value.poses);selected=actors[0]?.id??1;previewMode='pose';reset++;}}
  onMount(()=>{let stop=()=>{};void api.progress(v=>{if(v.jobId===currentJob)progress(v.label,v.percent);}).then(fn=>stop=fn);return()=>stop();});
</script>

<div class="text-workspace" class:prompt-hidden={promptCollapsed} class:preview-hidden={previewCollapsed} hidden={!active} inert={!active}>
  <section class="text-prompt-panel canvas-panel" class:collapsed={promptCollapsed}>
    <div class="panel-heading"><div><button class="panel-toggle icon-button" aria-label={promptCollapsed?'Expand Text to Pose':'Collapse Text to Pose'} aria-expanded={!promptCollapsed} aria-controls="text-prompt-content" use:tooltip={promptCollapsed?'Restore your prompt and character options.':'Collapse the prompt panel. Your direction and options are kept.'} onclick={()=>promptCollapsed=!promptCollapsed}>{#if promptCollapsed}<ChevronRight size={15}/>{:else}<ChevronLeft size={15}/>{/if}</button><span class="step-number">01</span><h2>Text to Pose</h2></div>{#if !promptCollapsed}<span class="panel-detail">Local creation</span>{/if}</div>
    <div class="panel-body" id="text-prompt-content" hidden={promptCollapsed} inert={promptCollapsed}>
    <div class="text-prompt-body">
      <div class="text-intro"><h3>A thought. A pose. Yours.</h3><p>Describe a moment. Create a body pose of your own.</p></div>
      <div class="text-body-notice"><Info size={16}/><p><strong>Body poses with Kimodo</strong>Generate body poses, with optional approximate hand shapes. For faces, use Expression studio.</p></div>
      <div class="text-direction-heading"><label for="text-prompt" class="text-prompt-label">Your direction <span>{prompt.length} / 2,000</span></label><button class="text-button" aria-haspopup="dialog" aria-controls="workspace-drawer" onclick={onpromptguide}><BookOpen size={12}/> Prompt guide</button></div>
      <textarea id="text-prompt" bind:value={prompt} maxlength="2000" rows="5" disabled={busy} placeholder="She is jumping, both feet in the air and both hands overhead."></textarea>
      <div class="text-examples" aria-label="Prompt examples">{#each examples as example}<button class="compact-button" disabled={busy} onclick={()=>prompt=example}>{example}</button>{/each}</div>
      <details class="text-reference"><summary>Pose character <span>Optional</span><ChevronDown size={13}/></summary><fieldset class="text-segments text-profile-grid" disabled={busy}><legend>How should it feel?</legend>{#each profiles as option}<label class:active={style===option}><input type="radio" name="creative-style" checked={style===option} onchange={()=>style=option}/>{option[0].toUpperCase()+option.slice(1)}</label>{/each}</fieldset><p>Body-language presets guide unspecified details. Your explicit directions take priority.</p></details>
      <div class="text-actor-heading"><strong>Characters</strong><div role="group" aria-label="Characters for next generation"><button class="compact-button" class:active={actors.length===1} aria-pressed={actors.length===1} disabled={busy} onclick={()=>count(1)}>One</button><button class="compact-button" class:active={actors.length===2} aria-pressed={actors.length===2} disabled={busy} onclick={()=>count(2)}>Two</button></div></div>
      {#each actors as actor,index}<label class="text-actor" for={'text-rig-'+actor.id}><span>Person {actor.id}</span><select id={'text-rig-'+actor.id} value={actor.rigId} disabled={busy} onchange={e=>actors=actors.map((a,i)=>i===index?{...a,rigId:e.currentTarget.value as RigId}:a)}>{#each Object.entries(labels) as [id,label]}<option value={id}>{label}</option>{/each}</select></label>{/each}
      <section class="text-hand-option"><HandShapeSettings enabled={handShapes} disabled={busy} compact onchange={changeHands}/></section>
      {#if actors.length===2}<p class="text-helper">Each body is generated separately, then fitted together. Partner contacts are experimental; inspect palms and spacing in Pose Studio.</p>{/if}
      <section class="text-ai-panel" aria-label="Kimodo engine"><div class="text-ai-heading"><strong>Kimodo engine</strong><button class="text-button" onclick={onsettings}><Settings2 size={13}/> Engine settings</button></div>
        <p class="editor-caption">Floor support is experimental. Inspect support and refine joints in Pose Studio.</p>
        {#if runtime?.kimodo.phase==='missing'}<div class="text-setup-card"><Cpu size={18}/><div><strong>Add the optional Kimodo engine</strong><p>Download or import its components in Engine settings.</p><button class="secondary" onclick={onsettings}>View components</button></div></div>{:else}<KimodoControls runtime={runtime?.kimodo} {busy} {stage} desktop={api.desktop} compact onruntime={manageKimodo}/>{/if}
      </section>
      {#if interpreted}<div class="text-understood" role="status"><strong>{interpreted.status==='plan'?'Understood changes':interpreted.status==='clarify'?'One detail to clarify':'Try another direction'}</strong><p>{interpreted.message??interpreted.summary}</p></div>{/if}
    </div>
    <div class="text-prompt-footer">{#if busy}<div class="text-job" role="status"><LoaderCircle size={15}/><span>{stage}</span><progress value={percent>=0?percent:undefined} max="100"></progress></div><button class="secondary" onclick={cancel}><X size={14}/> Cancel</button>{:else}<button class="primary wide" disabled={!prompt.trim()||!api.desktop||runtime?.kimodo.phase==='missing'} onclick={()=>preview()}><Sparkles size={15}/> Preview result <ArrowRight size={15}/></button>{/if}</div>
    </div>
  </section>
  <section class="text-preview-panel canvas-panel" class:collapsed={previewCollapsed}>
    <div class="panel-heading"><div><button class="panel-toggle icon-button" aria-label={previewCollapsed?'Expand Text pose preview':'Collapse Text pose preview'} aria-expanded={!previewCollapsed} aria-controls="text-preview-content" use:tooltip={previewCollapsed?'Restore the pose preview and choices.':'Collapse the preview. Your choices and accepted result are kept.'} onclick={()=>previewCollapsed=!previewCollapsed}>{#if previewCollapsed}<ChevronLeft size={15}/>{:else}<ChevronRight size={15}/>{/if}</button><span class="step-number">02</span><h2>{previewMode==='expression'?'Expression':'Pose'} preview</h2>{#if !previewCollapsed}<span class="state-tag">{candidate?'Preview only':accepted?'Accepted':'Ready to create'}</span>{/if}</div>{#if shown&&!previewCollapsed}<button class="icon-button" aria-label="Undo text result" disabled={busy||!undo.length} onclick={undoResult}><Undo2 size={15}/></button>{/if}</div>
    <div class="panel-body" id="text-preview-content" hidden={previewCollapsed} inert={previewCollapsed}>
    <div class="text-preview-stage">
      {#if shown?.poses.length&&previewMode==='pose'}<Preview active={active&&!previewCollapsed} pose={selectedPose} companions={shown.poses.filter(p=>p.personId!==selected)} {theme} {view} {reset} onCameraProfile={value=>cameraProfile=value}/>
      {:else if selectedExpression&&previewMode==='expression'}<HeadPreview actions={selectedExpression.target?.previewActions??{...selectedExpression.source.face.actions,...selectedExpression.source.face.extras}} {theme} {active}/>
      {:else}<div class="empty-state"><div class="empty-icon"><Sparkles size={28}/></div><h3>Give the moment a direction.</h3><p>Your preview appears here.<br/>Nothing changes in DAZ until you send it.</p></div>{/if}
      {#if shown}<div class="text-preview-toolbar" role="group" aria-label="Displayed actors">{#each displayedActors as actor}<button class="compact-button" class:active={selected===actor.id} aria-pressed={selected===actor.id} disabled={busy} onclick={()=>selected=actor.id}>Person {actor.id}</button>{/each}{#if shown.poses.length&&shown.expressions.length}<button class="compact-button" onclick={()=>previewMode=previewMode==='pose'?'expression':'pose'}>{previewMode==='pose'?'View face':'View body'}</button>{/if}</div>
        {#if previewMode==='pose'}<div class="text-camera" role="group" aria-label="Text preview camera views">{#each ['front','side','back'] as profile}<button class="compact-button" class:active={cameraProfile===profile} aria-pressed={cameraProfile===profile} onclick={()=>{view=profile;reset++;}}>{profile[0].toUpperCase()+profile.slice(1)}</button>{/each}</div>{/if}
        <button bind:this={notesTrigger} class="notes-button text-notes-button" class:active={notesOpen} aria-expanded={notesOpen} aria-controls="text-notes" onclick={()=>notesOpen?closeNotes():notesOpen=true}><MessageSquareText size={13}/> Text notes</button>
        {#if notesOpen}<aside id="text-notes" class="text-notes" aria-label="Text notes"><strong>Text notes</strong><button bind:this={notesClose} class="icon-button" aria-label="Close text notes" onclick={closeNotes}><X size={13}/></button>{#each [...new Set([...(shown.intent.assumptions??[]),...(selectedPose?.warnings??[]),...(selectedExpression?.target?.warnings??selectedExpression?.source.warnings??[])])] as note}<p>{note}</p>{:else}<p>No additional notes for this result.</p>{/each}</aside>{/if}
      {/if}
    </div>
    {#if candidate&&choices.length>1}<div class="text-pose-choices" role="group" aria-label="Pose alternatives">{#each choices as choice,index}<button class:active={candidate.id===choice.id} aria-pressed={candidate.id===choice.id} disabled={busy} onclick={()=>{candidate=choice;interpreted=choice.intent;}}><div class="text-choice-cues"><PoseThumbnail poses={choice.poses}/></div><span>Choice {index+1}{#if candidate.id===choice.id}<Check size={13}/>{/if}</span></button>{/each}</div>{/if}
    <PreviewNotice kind={previewMode==='expression'?'expression':'pose'}/>
    <div class="text-result-actions">
      {#if candidate}<span>Inspect this preview before keeping it.</span>{:else if accepted}<span>Accepted · Person {selected}</span>{:else}<span>Quick preview · Local processing</span>{/if}
      {#if shown?.poses.length}<button class="secondary" disabled={busy||!api.desktop||!canVary} use:tooltip={!api.desktop?'Fresh generation runs in the desktop app.':canVary?'Generate fresh choices with this direction and pose character.':'Preview the current direction and options first.'} onclick={()=>preview(true)}><Sparkles size={14}/> More like this</button>{/if}
      {#if candidate}<button class="secondary" disabled={busy} onclick={()=>{candidate=null;choices=[];notice='Preview discarded. Your accepted result is kept.';}}>Cancel preview</button><button class="primary" disabled={busy||!api.desktop} onclick={apply}><Check size={15}/> Apply</button>
      {:else if accepted&&shown?.id===accepted.id}{#if accepted.poses.length}<button class="secondary" disabled={busy} onclick={()=>onbody(accepted!.poses)}>Edit in Pose Studio</button>{/if}{#if selectedExpression}<button class="secondary" disabled={busy} onclick={()=>onexpression(selectedExpression!)}>Edit in Expression Studio</button>{/if}{/if}
    </div>
    {#if notice}<p class="text-notice" role="status">{notice}</p>{/if}
    </div>
  </section>
  {#if promptCollapsed&&previewCollapsed}<div class="workspace-rest"><Sparkles size={30}/><h3>Panels collapsed</h3><button class="secondary" use:tooltip={'Restore both workspace panels.'} onclick={()=>{promptCollapsed=false;previewCollapsed=false;}}>Show both panels</button></div>{/if}
  {#if busy&&promptCollapsed}<section class="action-dock text-output-dock text-task-dock" aria-label="Text task"><div class="text-job" role="status"><LoaderCircle size={15}/><span>{stage}</span><progress value={percent>=0?percent:undefined} max="100" aria-label="Text task progress"></progress></div><button class="secondary" onclick={cancel}><X size={14}/> Cancel</button></section>{/if}
  {#if accepted||error}
    <section class="action-dock text-output-dock" aria-label={accepted?'Export accepted pose':'Text to Pose status'}>
      {#if error}<div class="task-line" role="alert"><AlertCircle size={15}/><span class="task-error">{error}</span><button class="icon-button" aria-label="Dismiss Text to Pose error" use:tooltip={'Dismiss this error message.'} onclick={()=>error=''}><X size={14}/></button></div>{/if}
      {#if accepted}
        <div class="dock-controls">
          <div class="output-fields">{#if accepted.poses.length}<div class="field"><span class="editor-caption">Accepted export actor</span><strong>{#each accepted.poses.filter(p=>p.personId===selected) as actor}Person {actor.personId} · {labels[actor.rigId]}{:else}Choose an accepted actor{/each}</strong></div><div class="field"><label for="text-placement">Placement in DAZ</label><select id="text-placement" bind:value={placement} disabled={busy||!canExport}><option value="floor">Use preview position</option><option value="keep">Keep scene position</option></select></div>{#if accepted.poses.length>1&&placement==='keep'}<p class="text-helper">Keeping each figure’s scene position can separate partner contacts. Use preview position for this interaction.</p>{/if}{/if}</div>
          <div class="dock-actions"><button class="primary" disabled={busy||!canExport||!api.desktop} onclick={()=>saveOutput(true)}><ArrowUpRight size={16}/> Open in DAZ Studio</button><button class="secondary" disabled={busy||!canExport||!api.desktop} onclick={()=>saveOutput(false)}><Download size={16}/> Save DUF</button></div>
        </div>
      {/if}
    </section>
  {/if}
</div>

<style>
  .text-direction-heading{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.text-direction-heading .text-prompt-label{flex:1;min-width:125px;gap:10px}.text-direction-heading button{font-size:10px;min-height:24px;gap:5px}
</style>
