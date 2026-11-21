<script lang="ts">
  import { onMount } from 'svelte';
  import { Smile, ImagePlus, FolderOpen, ScanFace, ArrowUpRight, Download, Link2, LoaderCircle, X, ChevronDown, ChevronLeft, ChevronRight, ShieldCheck, Save, AlertCircle } from 'lucide-svelte';
  import HeadPreview from './HeadPreview.svelte';
  import ExpressionControls from './ExpressionControls.svelte';
  import PreviewNotice from '../PreviewNotice.svelte';
  import { tooltip } from '../tooltip';
  import {formatElapsed} from '../completionTime';
  import {recordCreation} from '../support';
  import * as api from '../api';
  import type { Photo, RigId, Theme, HistoryItem } from '../types';
  import type { EngineStatus } from '../engine';
  import { FaceEngine, faceImageUrl } from './engine';
  import { sourceFromFace, shownActions } from './face';
  import { defaultOptions, type Face, type FaceProfile, type ExpressionOptions, type ExpressionSource, type TargetExpression } from './types';
  import { waitForDaz } from './handoff';
  let {active,theme,engine,dazExecutable,onengine,onsettings,onhistory,onprofiles,onstate=()=>{},onsupportblocked=()=>{},ontask}:{active:boolean;theme:Theme;engine:EngineStatus|null;dazExecutable:string;onengine:()=>void;onsettings:()=>void;onhistory:()=>void;onprofiles:(profiles:Partial<Record<RigId,FaceProfile>>)=>void;onstate?:(source:ExpressionSource|null)=>void;onsupportblocked?:(blocked:boolean)=>void;ontask:(busy:boolean,label:string)=>void}=$props();
  const labels:Record<RigId,string>={g8f:'Genesis 8 Female',g8m:'Genesis 8 Male',g9:'Genesis 9'};
  let photo=$state<Photo|null>(null),faces=$state<Face[]>([]),selected=$state<number|null>(null),source=$state<ExpressionSource|null>(null),target=$state<TargetExpression|null>(null);
  let rig=$state<RigId>('g8f'),options=$state<ExpressionOptions>(defaultOptions()),profiles=$state<Partial<Record<RigId,FaceProfile>>>({});
  let busy=$state(false),stage=$state(''),percent=$state(0),error=$state(''),notice=$state(''),neutral=$state(false),details=$state(false),overlay=$state(false);
  let referenceCollapsed=$state(false),previewCollapsed=$state(false),controlsCollapsed=$state(false),actionsCollapsed=$state(false);
  let headMounted=$state(false);
  let reference:HTMLDivElement,size=$state({width:300,height:400}),fileInput:HTMLInputElement;
  let revision=0,currentJob='',originalUrl='',ownedUrl='',refitTimer:ReturnType<typeof setTimeout>|null=null;
  let numberFocused=false,disposed=false;
  let notesTrigger=$state<HTMLButtonElement>();
  const faceEngine=new FaceEngine();
  const installed=$derived(api.desktop?engine?.runtimeReady===true&&engine.components.find(c=>c.id==='expression')?.state==='installed':true);
  const connected=$derived(!!profiles[rig]),canExport=$derived(api.desktop&&!busy&&!!target&&target.rigId===rig);
  const imageSize=$derived(photo?{width:Math.min(size.width,size.height*photo.width/photo.height),height:Math.min(size.height,size.width*photo.height/photo.width)}:{width:0,height:0});
  const actions=$derived(shownActions(source,options,neutral));
  const supportedActions=$derived(target&&!neutral?target.previewActions:actions);
  const extractionNotes=$derived([...new Set([...(source?.warnings??[]),...(target?.warnings??[])])]);
  $effect(()=>onprofiles(profiles));
  $effect(()=>onsupportblocked(!!error||details));
  const authoredScene='text-'+crypto.randomUUID().replaceAll('-','');
  $effect(()=>{const actions=shownActions(source,options);onstate(source?{version:2,kind:'text',engine:'text-intent-v1',sceneId:source.sceneId??authoredScene,face:{id:1,box:[],landmarks:[],matrix:[],actions:Object.fromEntries(Object.keys(source.face.actions).map(key=>[key,actions[key]??0])),extras:{tongueOut:actions.tongueOut??0}},unknown:source.unknown,warnings:[]}:null);});
  $effect(()=>{if(active)headMounted=true;});
  function progress(label:string,value:number){stage=label;percent=value;ontask(true,label);}
  function begin(label:string){busy=true;error='';notice='';progress(label,0);currentJob=crypto.randomUUID();}
  function finish(){busy=false;currentJob='';ontask(false,'');}
  async function request<T>(method:string,payload:unknown):Promise<T>{return api.request<T>(method,payload,currentJob||crypto.randomUUID());}
  async function requestInDaz<T>(method:string,payload:unknown):Promise<T>{const job=currentJob;return waitForDaz(request<T>(method,payload),()=>currentJob===job?api.cancel():Promise.resolve());}
  export async function cancel(){revision++;faceEngine.cancel();if(refitTimer){clearTimeout(refitTimer);refitTimer=null;}try{if(api.desktop)await api.cancel();}catch(e){error=String(e);}finally{finish();notice='Cancelled. Your previous expression is preserved.';}}
  export function closeNotes(){if(!details)return false;details=false;notesTrigger?.focus();return true;}
  export async function adoptText(value:import('../text/types').TextExpression){if(busy)return;revision++;photo=null;faces=[];selected=value.actorId;source=value.source;target=value.target;rig=value.rigId;options=defaultOptions();neutral=false;details=false;overlay=false;notice='Text-authored expression ready to refine.';await refreshProfiles();if(!target)await fit();}
  function selectFace(face:Face){if(busy)return;revision++;selected=face.id;source=null;target=null;options={...options,adjustments:{}};neutral=false;details=false;overlay=false;notice='Face '+face.id+' selected. Extract its expression when ready.';}
  async function detect(image:Photo,url:string){
    const token=++revision;begin('Opening the original photograph');
    try{const result=await faceEngine.run('detect',url,progress);if(token!==revision)return;
      const img=new Image();img.src=image.url;await img.decode();if(token!==revision)return;
      const nextFaces=(result.faces??[]).map(face=>{const canvas=document.createElement('canvas');canvas.width=80;canvas.height=80;const scale=img.naturalWidth/image.width;canvas.getContext('2d')?.drawImage(img,face.box[0]*scale,face.box[1]*scale,(face.box[2]-face.box[0])*scale,(face.box[3]-face.box[1])*scale,0,0,80,80);return {...face,thumbnail:canvas.toDataURL('image/jpeg',.8)};});
      faces=nextFaces;selected=faces.length===1?faces[0].id:null;source=null;target=null;photo=image;originalUrl=url;details=false;overlay=false;neutral=false;
      options={...options,adjustments:{}};
      if(!faces.length)notice='No readable face found. Try a sharper or more frontal reference.';
      else notice=faces.length>1?'Choose a numbered face. Only that person’s expression will be extracted.':'Face found. Extract its expression.';
    }catch(e){if(token===revision)error=String(e);}finally{if(token===revision)finish();}
  }
  export async function loadPath(path:string){if(busy)return;if(!installed){onengine();return;}const token=++revision;try{begin('Importing reference');const image=await request<Photo>('import_image',{path});if(token!==revision)return;finish();await detect(image,faceImageUrl(image.id));}catch(e){if(token===revision){error=String(e);finish();}}}
  export async function open(){if(busy)return;if(!installed){onengine();return;}if(!api.desktop){fileInput.click();return;}try{const path=await api.pickImage();if(typeof path==='string')await loadPath(path);}catch(e){error=String(e);}}
  export async function paste(){if(!api.desktop||busy)return;try{await loadPath(await api.clipboard());}catch(e){error=String(e);}}
  async function browserFile(event:Event){
    const file=(event.currentTarget as HTMLInputElement).files?.[0];if(!file||busy)return;let candidateUrl='';
    try{
      if(file.size>100*1024**2)throw Error('Choose an image smaller than 100 MB.');
      candidateUrl=URL.createObjectURL(file);const img=new Image();img.src=candidateUrl;await img.decode();
      if(img.naturalWidth*img.naturalHeight>40_000_000)throw Error('Resize this reference below 40 megapixels.');
      const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await file.arrayBuffer()))).map(v=>v.toString(16).padStart(2,'0')).join('').slice(0,24);
      await detect({id:hash,name:file.name,width:img.naturalWidth,height:img.naturalHeight,url:candidateUrl,people:[]},candidateUrl);
      if(photo?.url===candidateUrl){if(ownedUrl)URL.revokeObjectURL(ownedUrl);ownedUrl=candidateUrl;}
    }catch(e){error=String(e);}finally{if(candidateUrl&&candidateUrl!==ownedUrl)URL.revokeObjectURL(candidateUrl);fileInput.value='';}
  }
  async function localTestPortrait(){const url='/__expression-assets/test-portrait';const img=new Image();img.src=url;await img.decode();await detect({id:'0123456789abcdef01234567',name:'Official local test portrait',width:img.naturalWidth,height:img.naturalHeight,url,people:[]},url);}
  export async function extract(){
    if(busy||!photo||selected===null)return;if(!installed){onengine();return;}
    const chosen=faces.find(f=>f.id===selected);if(!chosen)return;
    const token=++revision,started=performance.now(),operationId=crypto.randomUUID();begin('Extracting the selected expression');
    try{const result=await faceEngine.run('extract',originalUrl,progress,chosen);if(token!==revision||!result.face)return;
      const next=sourceFromFace(photo.id,{...result.face,selectionBox:chosen.selectionBox??chosen.box,observationId:chosen.observationId});let fitted:TargetExpression|null=null;
      if(api.desktop&&profiles[rig]){progress('Fitting supported facial controls',85);fitted=await request('retarget_expression',{source:next,options,rigId:rig});}
      if(token!==revision)return;
      if(api.desktop){await request('save_expression',{source:next,options,rigId:rig});if(token!==revision)return;onhistory();}
      source=next;target=fitted;neutral=false;
      recordCreation(operationId);
      notice='Expression extracted in '+formatElapsed(performance.now()-started)+'. '+(connected?'Inspect the face, then send or save.':'Connect a matching DAZ face to enable export.');
    }catch(e){if(token===revision)error=String(e);}finally{if(token===revision)finish();}
  }
  async function fit(){
    if(refitTimer){clearTimeout(refitTimer);refitTimer=null;}
    if(disposed||numberFocused||!source||!profiles[rig]||!api.desktop||busy)return;const token=++revision;begin('Fitting '+labels[rig]+' facial controls');
    try{const result=await request<TargetExpression>('retarget_expression',{source,options,rigId:rig});if(token!==revision)return;target=result;}catch(e){if(token===revision){target=null;error=String(e);}}finally{if(token===revision)finish();}
  }
  function queueRefit(){
    if(refitTimer){clearTimeout(refitTimer);refitTimer=null;}
    if(disposed||numberFocused||busy||!source||!profiles[rig]||!api.desktop)return;
    refitTimer=setTimeout(()=>{refitTimer=null;void fit();},160);
  }
  function numberFocus(focused:boolean){numberFocused=focused;if(focused){if(refitTimer)clearTimeout(refitTimer);refitTimer=null;}else if(!target)queueRefit();}
  function changeOptions(next:ExpressionOptions){options=next;target=null;queueRefit();}
  async function changeGeneration(value:RigId){if(busy)return;rig=value;target=null;await fit();}
  export async function connect(generation:RigId=rig){
    if(!api.desktop||busy)return;if(!dazExecutable){onsettings();return;}
    const token=++revision;let linked=false;begin('Connecting the selected '+labels[generation]+' face');
    try{const result=await requestInDaz<{profile:FaceProfile;figure:string}>('connect_expression_figure',{rigId:generation,executable:dazExecutable});if(token!==revision)return;profiles={...profiles,[generation]:result.profile};linked=true;notice=new Set(result.profile.mappings.map(m=>m.action)).size+' facial movements connected from '+result.figure+'.';}catch(e){if(token===revision)error=String(e);}finally{if(token===revision)finish();}if(linked&&token===revision)await fit();
  }
  async function saveHistory(){if(!source||busy||!api.desktop)return;const token=++revision;begin('Saving expression locally');try{await request('save_expression',{source,options,rigId:rig});if(token!==revision)return;onhistory();notice='Expression saved in History → Expressions.';}catch(e){if(token===revision)error=String(e);}finally{if(token===revision)finish();}}
  async function zeroInDaz(){
    if(!api.desktop||busy)return;if(!dazExecutable){onsettings();return;}
    const token=++revision;begin('Zeroing PoseSnap controls on the selected '+labels[rig]);
    try{const result=await requestInDaz<{figure:string;zeroed:number;tracked:number}>('zero_expression',{rigId:rig,executable:dazExecutable});if(token!==revision)return;notice=result.zeroed?'PoseSnap’s applied controls were zeroed on '+result.figure+'. Other DAZ settings were kept. Undo is available in DAZ.':result.tracked?'PoseSnap’s applied controls are already zero on '+result.figure+'. Other DAZ settings were kept.':'No PoseSnap-applied controls are recorded on '+result.figure+'. Apply an expression once to enable this scoped reset.';}catch(e){if(token===revision)error=String(e);}finally{if(token===revision)finish();}
  }
  async function output(apply:boolean){
    if(!canExport||!target)return;if(apply&&!dazExecutable){onsettings();return;}
    const token=++revision,accepted=target;begin(apply?'Applying expression in DAZ Studio':'Choose an expression file location');
    try{const path=apply?null:await api.saveExpression((photo?.name.replace(/\.[^.]+$/,'')??'PoseSnap')+'-expression-'+rig);if(token!==revision||!apply&&!path)return;
      progress(apply?'Applying expression in DAZ Studio':'Saving expression DUF',0);const result=await (apply?requestInDaz:request)<{figure?:string;maximumError?:number;path?:string;warnings?:string[]}>(apply?'apply_expression':'export_expression',{expression:accepted,executable:dazExecutable,path});if(token!==revision)return;
      notice=apply?'Applied to '+result.figure+' · facial channels verified.'+(result.warnings?.length?' '+result.warnings.join(' '):''):'Expression DUF saved. Body, position and head orientation are preserved.';
    }catch(e){if(token===revision)error=String(e);}finally{if(token===revision)finish();}
  }
  export async function restore(item:HistoryItem){if(busy||item.faceId===undefined)return;const token=++revision;begin('Opening saved expression');try{const record=await request<{photo:Photo|null;source:ExpressionSource;options:ExpressionOptions;rigId:RigId}>('read_expression',{imageId:item.id,faceId:item.faceId,observationId:item.observationId});if(token!==revision)return;photo=record.photo;source=record.source;options=record.options;rig=record.rigId;faces=record.photo?[record.source.face]:[];selected=item.faceId;originalUrl=record.photo?faceImageUrl(record.photo.id):'';target=null;neutral=false;details=false;overlay=false;notice='Saved expression restored.';}catch(e){if(token===revision)error=String(e);}finally{if(token===revision)finish();}if(token===revision)await fit();}
  export async function refreshProfiles(){if(api.desktop)try{profiles=await api.request('expression_profiles');}catch(e){error=String(e);}}
  onMount(()=>{
    const observer=new ResizeObserver(()=>{if(reference){const r=reference.getBoundingClientRect();size={width:Math.max(1,r.width-32),height:Math.max(1,r.height-32)};}});observer.observe(reference);
    let unlisten=()=>{};void api.progress(v=>{if(v.jobId===currentJob)progress(v.label,v.percent);}).then(stop=>unlisten=stop);
    return()=>{disposed=true;observer.disconnect();faceEngine.cancel();unlisten();if(refitTimer)clearTimeout(refitTimer);if(ownedUrl)URL.revokeObjectURL(ownedUrl);};
  });
</script>

<div class="expression-workspace" hidden={!active} inert={!active}>
  <input class="visually-hidden" type="file" accept="image/*" bind:this={fileInput} onchange={browserFile} tabindex="-1" aria-label="Local expression reference"/>
  <div class="expression-pair" class:reference-hidden={referenceCollapsed} class:preview-hidden={previewCollapsed}>
    <section class="reference-panel canvas-panel" class:collapsed={referenceCollapsed} aria-label="Expression reference photograph">
      <div class="panel-heading"><div><button class="icon-button panel-toggle" aria-label={referenceCollapsed?'Open expression reference':'Collapse expression reference'} aria-expanded={!referenceCollapsed} aria-controls="expression-reference-content" use:tooltip={'Show or hide your expression reference.'} onclick={()=>referenceCollapsed=!referenceCollapsed}>{#if referenceCollapsed}<ChevronRight size={15}/>{:else}<ChevronLeft size={15}/>{/if}</button><span class="step-number">01</span><h2>Face reference</h2></div>{#if !referenceCollapsed}{#if photo}<button class="text-button recheck" disabled={busy} use:tooltip={'Check the original image at multiple scales and recover rotated faces. Choose a numbered face afterwards.'} onclick={()=>photo&&detect(photo,originalUrl)}><ScanFace size={13}/> Recheck faces</button>{:else}<span class="panel-detail">Start with an image</span>{/if}{/if}</div>
      <div class="panel-body" id="expression-reference-content" hidden={referenceCollapsed} inert={referenceCollapsed}>
        <div class="reference-canvas" bind:this={reference}>
          {#if photo}<div class="reference-image" style:width={imageSize.width+'px'} style:height={imageSize.height+'px'}><img src={photo.url} alt="Expression reference"/>{#each faces as face}<button class="face-box" class:selected={selected===face.id} style:left={face.box[0]/photo.width*100+'%'} style:top={face.box[1]/photo.height*100+'%'} style:width={(face.box[2]-face.box[0])/photo.width*100+'%'} style:height={(face.box[3]-face.box[1])/photo.height*100+'%'} aria-label={'Select face '+face.id} aria-pressed={selected===face.id} disabled={busy} use:tooltip={'Choose face '+face.id+'. Only its expression is extracted.'} onclick={()=>selectFace(face)}><span>{face.id}</span></button>{/each}{#if overlay&&source}<svg class="face-landmarks" viewBox={'0 0 '+photo.width+' '+photo.height} aria-label="Extracted facial landmarks">{#each source.face.landmarks as point,index}{#if index%3===0}<circle cx={point[0]} cy={point[1]} r={Math.max(1,photo.width/650)}/>{/if}{/each}</svg>{/if}</div>{:else}<div class="drop-zone"><div class="import-symbol"><ImagePlus size={36} strokeWidth={1.3}/></div><h1>Your reference.<br/><span>Your next expression.</span></h1><p>Drop a photo here to begin.<br/>Everything stays on your PC.</p><button class="primary" disabled={busy} onclick={open} use:tooltip={'Open an original photograph with a clear face · Ctrl+O'}><FolderOpen size={16}/> Open image</button><span class="file-hint">or paste with Ctrl+V</span>{#if import.meta.env.DEV&&!api.desktop}<button class="text-button" onclick={localTestPortrait} use:tooltip={"Development-only: load the official local validation portrait."}>Use local test portrait</button>{/if}</div>{/if}
        </div>
        {#if faces.length}<div class="person-picker"><div class="picker-heading"><span><Smile size={14}/>{selected===null?'Choose a face':`Face ${selected} selected`}</span><span>{faces.length} detected</span></div><div class="people">{#each faces as face}<button class:selected={selected===face.id} disabled={busy} aria-pressed={selected===face.id} aria-label={'Choose face '+face.id} use:tooltip={'Extract face '+face.id+' only.'} onclick={()=>selectFace(face)}>{#if face.thumbnail}<img src={face.thumbnail} alt=""/>{/if}<span>{face.id}</span></button>{/each}</div></div>{/if}
        <div class="reference-footer">{#if photo}<span use:tooltip={photo.name}>{photo.name}</span><span>{photo.width} × {photo.height}</span>{:else}<ShieldCheck size={13}/><span>Local photos. Private processing.</span>{/if}</div>
      </div>
    </section>
    <section class="preview-panel canvas-panel" class:collapsed={previewCollapsed}>
      <div class="panel-heading"><div><button class="icon-button panel-toggle" aria-label={previewCollapsed?'Open expression preview':'Collapse expression preview'} aria-expanded={!previewCollapsed} aria-controls="expression-preview-content" use:tooltip={'Show or hide the expression preview.'} onclick={()=>previewCollapsed=!previewCollapsed}>{#if previewCollapsed}<ChevronLeft size={15}/>{:else}<ChevronRight size={15}/>{/if}</button><span class="step-number">02</span><h2>Expression preview</h2>{#if !previewCollapsed}<span class="state-tag">{source?.kind==='text'?'Text authored':source?'Extracted':'Neutral'}</span>{/if}</div></div>
      <div class="panel-body" id="expression-preview-content" hidden={previewCollapsed} inert={previewCollapsed}>
        <div class="face-stage" class:controls-collapsed={controlsCollapsed}>
          {#if headMounted}<HeadPreview actions={supportedActions} referenceMatrix={source?.face.matrix??[]} {theme} active={active&&!previewCollapsed}/>{/if}
          <span class="preview-label face-preview-label" use:tooltip={'Face Sculpting 108th (female) by ComputerCat, adapted under CC BY 4.0. Actual Genesis facial shapes and limits can differ. Full credit is in Settings → About.'}>Expression face · adapted preview rig</span>
          <ExpressionControls {source} {options} {target} profile={profiles[rig]} rigLabel={labels[rig]} {busy} desktop={api.desktop} {neutral} bind:collapsed={controlsCollapsed} onChange={changeOptions} onNumberFocus={numberFocus} onCompare={()=>neutral=!neutral} onReset={()=>{neutral=false;changeOptions(defaultOptions());}} onOpen={open} onZeroDaz={zeroInDaz}/>
          {#if source}
            <button bind:this={notesTrigger} class="notes-button expression-notes" class:active={details} aria-label="Expression notes" aria-expanded={details} aria-controls="expression-notes" use:tooltip={'Review extraction evidence, unsupported movements and limitations.'} onclick={()=>details=!details}><AlertCircle size={14}/> Expression notes {#if extractionNotes.length}<span>{extractionNotes.length}</span>{/if}</button>
          {/if}
          {#if details&&source}
            <aside class="notes-popover expression-notes-popover" id="expression-notes" aria-label="Expression notes">
              <div class="expression-notes-heading"><h3>Expression notes</h3><button class="icon-button" aria-label="Close expression notes" onclick={closeNotes} use:tooltip={'Close expression notes · Escape.'}><X size={14}/></button></div>
              {#if source.kind!=='text'}<p>{source.face.landmarks.length} model landmarks. Their presence does not prove that every point is visible.</p>{:else}<p>Text-authored facial actions. No image landmarks or detection confidence.</p>{/if}
              <p>Movement values describe amounts, not accuracy. Hidden facial detail remains estimated.</p>
              {#if extractionNotes.length}<ul>{#each extractionNotes as warning}<li>{warning}</li>{/each}</ul>{/if}
              {#if photo}<label class="editor-check"><input type="checkbox" bind:checked={overlay} use:tooltip={'Show estimated landmark positions on the reference photograph.'}/> Show extracted landmarks</label>{/if}
              <p>Left and right follow the person’s anatomy. Head orientation and body pose are preserved.</p>
            </aside>
          {/if}
        </div>
        <PreviewNotice kind="expression"/>
        <div class="canvas-footer"><span>Drag to orbit · Scroll to zoom</span><span>Expression only</span></div>
      </div>
    </section>
    {#if referenceCollapsed&&previewCollapsed}<div class="workspace-rest"><Smile size={30}/><h3>Panels collapsed</h3><button class="secondary" use:tooltip={'Restore both workspace panels.'} onclick={()=>{referenceCollapsed=false;previewCollapsed=false;}}>Show both panels</button></div>{/if}
  </div>
  <section class="action-dock expression-dock" class:collapsed={actionsCollapsed} aria-label="Extract and export expression">
    <div class="dock-message" class:error={!!error} role="status" aria-live="polite">{#if busy}<LoaderCircle size={15}/><span>{stage}</span><progress max="100" value={percent} aria-label="Expression progress"></progress><button class="text-button" onclick={cancel} use:tooltip={"Stop local analysis. Your previous accepted expression is kept."}><X size={13}/> Cancel</button>{:else if error}<AlertCircle size={15}/><span>{error}</span><button class="icon-button" aria-label="Dismiss expression error" onclick={()=>error=''} use:tooltip={"Dismiss this message."}><X size={14}/></button>{:else}<ShieldCheck size={14}/><span>{notice||'Choose a clear face. Extract locally. Apply only its expression.'}</span>{/if}<button class="icon-button dock-toggle" aria-label={actionsCollapsed?'Expand expression actions':'Collapse expression actions'} aria-controls="expression-dock-controls" aria-expanded={!actionsCollapsed} use:tooltip={actionsCollapsed?'Show generation, connection and export actions.':'Collapse the action bar; task status remains visible.'} onclick={()=>actionsCollapsed=!actionsCollapsed}><ChevronDown size={15}/></button></div>
    <div class="dock-controls" id="expression-dock-controls" hidden={actionsCollapsed} inert={actionsCollapsed}><div class="dock-fields"><label>Export figure<select value={rig} disabled={busy} onchange={e=>changeGeneration(e.currentTarget.value as RigId)} use:tooltip={'Changing generation refits cached facial movements, without another neural extraction.'}>{#each Object.entries(labels) as [id,label]}<option value={id}>{label}</option>{/each}</select></label><button class="secondary face-connect" disabled={!api.desktop||busy} use:tooltip={api.desktop?'Select a matching '+labels[rig]+' figure in DAZ. Read its facial drivers without changing the scene.':'Face connection is available in the desktop app.'} onclick={()=>connect()}><Link2 size={14}/>{connected?'Refresh face':'Connect selected face'}</button>{#if !installed}<button class="secondary" onclick={onengine} use:tooltip={"Open Engine settings to download or import verified facial assets."}><Download size={14}/> Get face engine</button>{/if}</div><div class="dock-actions"><button class="secondary" disabled={!api.desktop||!source||busy} use:tooltip={'Save strength and regions in History → Expressions.'} onclick={saveHistory}><Save size={14}/> Save expression</button><button class={source?'secondary':'primary'} disabled={!photo||selected===null||busy||!installed} use:tooltip={!photo?'Open a face reference first.':selected===null?'Choose a numbered face first.':'Extract the selected face locally on the CPU · Ctrl+Enter'} onclick={extract}><ScanFace size={15}/>{source?'Extract again':'Extract expression'}</button><button class={source?'primary':'secondary'} disabled={!canExport} use:tooltip={canExport?'Apply supported expression drivers to the selected matching figure as one undo operation. Body, placement and head rotation stay intact.':'Extract an expression and connect this generation’s selected face first.'} onclick={()=>output(true)}><ArrowUpRight size={15}/> Open in DAZ Studio</button><button class="secondary" disabled={!canExport} use:tooltip={canExport?'Save supported facial channels as a DUF. Disabled and unknown regions are omitted.':'Connect this generation’s facial controls and extract first.'} onclick={()=>output(false)}><Download size={15}/> Save DUF</button></div></div>
  </section>
</div>
