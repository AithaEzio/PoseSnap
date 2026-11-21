<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { appVersion,developmentBuild } from './lib/version';
  import { MessageSquareText, Smile, ImagePlus, ClipboardPaste, ScanLine, Box, RotateCcw, Grid2X2, ChevronDown, ChevronLeft, ChevronRight, Plus, Save, ArrowUpRight, Download, Check, ShieldCheck, Cpu, X, Settings2, Sun, Moon, Zap, FolderOpen, History, Search, Trash2, Maximize2, AlertCircle, LoaderCircle, Users, CircleHelp, Link2, ArrowRight } from 'lucide-svelte';
  import Preview from './lib/Preview.svelte';
  import PoseEditor from './lib/PoseEditor.svelte';
  import Drawer from './lib/Drawer.svelte';
  import HistoryRemoval from './lib/HistoryRemoval.svelte';
  import HelpTopics from './lib/HelpTopics.svelte';
  import Curtain from './lib/Curtain.svelte';
  import SupportSystem from './lib/SupportSystem.svelte';
  import AboutCreator from './lib/AboutCreator.svelte';
  import {recordCreation} from './lib/support';
  import RefineMatch from './lib/RefineMatch.svelte';
  import ClueSettings from './lib/ClueSettings.svelte';
  import CroppedJointsSettings from './lib/CroppedJointsSettings.svelte';
  import ImageGuidanceControl from './lib/ImageGuidanceControl.svelte';
  import ReferenceMaps from './lib/ReferenceMaps.svelte';
  import ReferenceDepthControls from './lib/ReferenceDepthControls.svelte';
  import {guidanceStatus,type GuidanceMode,type ReferenceKind} from './lib/guidance';
  import {handleExternalLink} from './lib/externalLinks';
  import {formatElapsed} from './lib/completionTime';
  import EnginePanel from './lib/EnginePanel.svelte';
  import EngineLight from './lib/EngineLight.svelte';
  import SettingsTabs from './lib/SettingsTabs.svelte';
  import ExpressionWorkspace from './lib/expression/ExpressionWorkspace.svelte';
  import TextWorkspace from './lib/text/TextWorkspace.svelte';
  import TextSettings from './lib/text/TextSettings.svelte';
  import {textIndicator,type TextRuntime,type TextExpression} from './lib/text/types';
  import PreviewNotice from './lib/PreviewNotice.svelte';
  import type { FaceProfile,ExpressionSource } from './lib/expression/types';
  import type { SettingsCategory } from './lib/settings';
  import { workspaceEngineIndicator, setupPlan, type SetupProfile, type EngineStatus } from './lib/engine';
  import { tooltip } from './lib/tooltip';
  import { helpTopics, helpMatches } from './lib/help';
  import { startupState } from './lib/startup';
  import { initialPreferences, rememberDevelopmentPreferences } from './lib/preferences';
  import { extractionFor, individualAfterInteraction, methodLabel } from './lib/extraction';
  import { togglePin, clearPins, preservePins } from './lib/pinning';
  import { chooserGroup } from './lib/jointSearch';
  import * as api from './lib/api';
  import { setFacing, floorClearance, setFloorClearance, type FacingPreset } from './lib/figureSetup';
  import { blankPose, copyPoses, snapshot, matchingJoint, limbParents, addedFixture, type EditSnapshot, figureKey, moveFigure, rotateJoint, resetSelection, zeroSelection, isReachJoint, type EditTool, type JointGroup, type EditAxis } from './lib/editor';
  import type { Theme, Rig, RigId, Placement, Photo, Pose, Person, HistoryItem, Status, Settings, Interaction, Contact, Support, SideGuidance } from './lib/types';
  const rigLabels: Record<RigId, string> = { g8f: 'Genesis 8 Female', g8m: 'Genesis 8 Male', g9: 'Genesis 9' };
  let jointSelector=$state<'buttons'|'map'>('buttons');
  const initial=initialPreferences();
  let extractionMethod=$state(initial.extractionMethod),clueEnabled=$state(initial.clueEnabled),zeroCroppedJoints=$state(initial.zeroCroppedJoints);
  let imageGuidance=$state<GuidanceMode>(initial.imageGuidance),inputCategory=$state<'photo'|'depth'>('photo');
  let depthInputType=$state<'relative'|'metric'>(initial.depthInputType);
  const depthImportKind=$derived<ReferenceKind>(depthInputType==='metric'?'metric-depth':'relative-depth');
  const refinement='accurate';let qualityOpen=$state(false),overlay=$state(false);
  let theme = $state<Theme>(initial.theme), motion = $state<'auto'|'reduced'>(initial.motion), status = $state<Status|null>(null);
  let engine=$state<EngineStatus|null>(null),engineAction=$state(false),setupPaused=false;
  let settingsCategory=$state<SettingsCategory>('appearance'),settingsReveal=$state(0);
  let photo = $state<Photo|null>(null), pose = $state<Pose|null>(null), people = $state<Person[]>([]);
  let selected = $state<number|null>(null), rig = $state<RigId>('g8f'), placement = $state<Placement>('keep');
  let busy = $state(false), activeJob = $state(''), percent = $state(0), stage = $state(''), error = $state(''), notice = $state('');
  let drawer = $state<'help'|'history'|'settings'|'interaction'|'refine'|null>(null), history = $state<HistoryItem[]>([]), historySearch = $state(''), helpSearch = $state('');
  let helpOpenTopic=$state(''),helpTrigger=$state.raw<HTMLElement|undefined>(undefined);
  let historyTab=$state<'extractions'|'edits'|'expressions'|'text'>('extractions');
  let expressionWorkspace:ExpressionWorkspace;
  let supportOpen=$state(false),expressionPending=$state(false),textPending=$state(false);
  let historyRemoval=$state<HistoryItem|null>(null);
  $effect(()=>{if(drawer!=='history')historyRemoval=null;});
  let textWorkspace:TextWorkspace;
  let textRuntime=$state<TextRuntime|null>(null),expressionBaseline=$state<ExpressionSource|null>(null);
  let faceProfiles=$state<Partial<Record<RigId,FaceProfile>>>({});
  const historyCategory=(item:HistoryItem)=>item.kind==='text'?'text':item.kind==='expression'?'expressions':item.kind==='pose'?'edits':'extractions';
  const historyLabels={extractions:'Extractions',edits:'Pose edits',expressions:'Expressions',text:'Text results'};
  function historyKey(event:KeyboardEvent){if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const tabs=['extractions','edits','expressions','text'] as const,index=tabs.indexOf(historyTab);historyTab=event.key==='Home'?tabs[0]:event.key==='End'?tabs[3]:tabs[(index+(event.key==='ArrowRight'?1:3))%4];(event.currentTarget as HTMLElement).parentElement?.querySelector<HTMLButtonElement>('#history-'+historyTab)?.focus();}
  async function refreshHistory(){if(api.desktop)history=await api.request('history');}
  let interaction = $state<Interaction|null>(null), interactionChoices = $state<Record<number,{chosen:boolean;rigId:RigId}>>({}), interactionBuild = $state('');
  let lastRefinement=$state<Interaction|null>(null);
  let pendingRefinement=$state<Interaction|null>(null),showOriginal=$state(false);
  let pendingInput:Pose[]=[],pendingSnapshot:EditSnapshot|null=null,previousRefineView='front',refinementRevision=0;
  let mode=$state<'extract'|'editor'|'expression'|'text'>('extract'), editPoses=$state<Pose[]>([]), editBaseline=$state<Pose[]>([]), undoStack=$state<EditSnapshot[]>([]), redoStack=$state<EditSnapshot[]>([]);
  let selectedBone=$state(figureKey), editTool=$state<EditTool>('select'), editSpace=$state<'local'|'world'>('local'), editSnap=$state(false), linked=$state(false);
  let editAxis=$state<EditAxis>('all'),jointHandles=$state(true),ghostPartners=$state(true),jointGroup=$state<JointGroup>('body'),jointFocus=$state(0);
  let editRevision=0,dragStart=$state.raw<EditSnapshot|null>(null);
  let referenceCollapsed=$state(false),previewCollapsed=$state(false),actionsCollapsed=$state(false),devRigs=$state<Partial<Record<RigId,Rig>>>({});
  let view = $state('front'), cameraProfile = $state<string|null>(null), grid = $state(true), reset = $state(0), notesOpen = $state(false);
  let dazExecutable = $state(''), referenceWidth = $state(35), dragOver = $state(false), firstHint = $state(false), sourceAvailable = $state(false),connectionRig=$state<RigId|null>(null);
  let curtain = $state(true), preferencesReady = $state(false), historyReady = $state(false), bootLabel = $state('Opening your workspace'), previewReady = $state(false), loaded = $state(false), visible = $state(true);
  let referenceCanvas: HTMLDivElement, referenceSize = $state({ width: 300, height: 400 });
  const acceptedPoses = $derived(editPoses.length?editPoses:interaction?interaction.poses:pose&&pose.rigId===rig?[pose]:[]);
  const displayPoses = $derived(pendingRefinement?.poses??acceptedPoses);
  const finalPose = $derived(displayPoses.find(p=>p.personId===selected)??null);
  const floorHeight = $derived(mode==='editor'&&selected!==null?floorClearance(displayPoses,selected,linked):0);
  const manualPose=$derived(finalPose?.origin==='editor'&&!finalPose.studioSource);
  const sourceSelection=$derived(finalPose?.studio?finalPose.studioSource?.personId??null:selected);
  const referenceLayout=$derived(displayPoses.length>0&&displayPoses.every(p=>p.layout?.reference));
  const companions = $derived(displayPoses.filter(p=>p.personId!==selected));
  const groupActive=$derived(!!interaction||editPoses.length>1);
  const generationLocked=$derived(!!photo?.detachedPose||busy||!!pendingRefinement||mode!=='editor'&&groupActive&&!editPoses.length);
  const confidence = $derived(finalPose?.quality?.detection ?? (finalPose ? people.find(p=>p.id===selected)?.score : undefined));
  const engineDisplay=$derived(mode==='text'?textIndicator(textRuntime,busy,stage,api.desktop,engine):workspaceEngineIndicator(mode,engine,api.desktop,busy,stage));
  const startup=$derived(startupState(engine,api.desktop,{preferences:preferencesReady,history:historyReady,transport:loaded,preview:previewReady},bootLabel));
  function dismissStartup(){curtain=false;if(api.desktop&&engine?.phase==='attention')openSettings('engine');}
  const visibleAgreement = $derived(finalPose?.quality?.visible);
  const chosenMembers = $derived(people.filter(p=>interactionChoices[p.id]?.chosen).map(p=>({personId:p.id,rigId:interactionChoices[p.id].rigId})));
  const connected = $derived(status?.rigs.includes(rig) ?? false);
  const bodyConnections = $derived(status?.connectedRigs ?? []);
  const filteredHistory = $derived(history.filter(item => historyCategory(item)===historyTab&&item.name.toLowerCase().includes(historySearch.toLowerCase())));
  const filteredHelp = $derived(helpTopics.filter(item => helpMatches(item,helpSearch)));
  const imageSize = $derived(photo ? { width: Math.min(referenceSize.width, referenceSize.height * photo.width / photo.height), height: Math.min(referenceSize.height, referenceSize.width * photo.height / photo.width) } : { width: 0, height: 0 });
  const extractDisabled = $derived(!api.desktop || busy || !!pendingRefinement || !photo || selected === null || !connected || !status?.ready || !engine?.ready);
  const extractHint = $derived(!api.desktop ? 'Launch the desktop app to extract locally.' : busy ? 'Wait for this task or use Cancel.' : !photo ? 'Open or paste a reference first.' : selected === null ? 'Choose a numbered person in the reference first.' : !status?.ready ? 'Local models are unavailable. Check Settings.' : !connected ? 'Built-in Genesis rig metadata is unavailable. Re-extract the current app into a new folder.' : 'Extract this person’s body and fingers on your GPU · Ctrl+Enter');
  const outputHint = $derived(!api.desktop ? 'Export is available in the desktop app.' : busy ? 'Finish or cancel the current task first.' : !finalPose ? 'Extract a pose or choose New pose before exporting.' : 'Export the exact pose shown in the mannequin preview.');
  async function refreshStatus() { if (api.desktop) status = await api.request<Status>('status'); }
  async function manageEngine(action:'check'|'verify'|'install',id?:string,source?:string){
    if(!api.desktop||busy||engineAction)return;
    engineAction=true;setupPaused=false;error='';
    try{engine=await api.engineTask(action,id,source);await refreshStatus();if(engine.runtimeReady)history=await api.request('history');}
    catch(e){error=String(e);try{engine=await api.engineStatus();}catch{if(engine)engine={...engine,active:false,ready:false,phase:'attention',message:error};}}
    finally{engineAction=false;}
  }
  async function downloadComponents(id?:string,profile:SetupProfile='all'){
    if(!engine||engine.active||engineAction||busy)return;
    const plan=setupPlan(engine,profile);
    if(!id&&plan.unavailable.length){error='Setup cannot finish: '+plan.unavailable.join(', ')+'. Use the current PoseSnap release.';return;}
    const components=id?engine.components.filter(c=>c.id===id):plan.pending;
    setupPaused=false;
    for(const component of components){if(setupPaused)break;await manageEngine('install',component.id);if(setupPaused||error)break;}
    if(!id&&!setupPaused&&!error){await manageEngine('check');if(!error)notice='Your selected PoseSnap components are installed and checked.';}
  }
  async function importComponent(id:string,folder:boolean){if(!api.desktop||busy||engineAction)return;try{const source=await api.pickComponent(folder);if(typeof source==='string')await manageEngine('install',id,source);}catch(e){error=String(e);}}
  async function pauseSetup(){setupPaused=true;await api.enginePause();}
  async function saveSettings(extra: Partial<Settings> = {}) {
    rememberDevelopmentPreferences({theme,motion,extractionMethod,clueEnabled,zeroCroppedJoints,imageGuidance,depthInputType});
    if (!api.desktop) { if(import.meta.env.DEV&&status)status={...status,settings:{...status.settings,...extra}}; return; }
    const saved = await api.request<Settings>('settings', { theme, motion, jointSelector, dazExecutable, refinement, extractionMethod, clueEnabled, zeroCroppedJoints,imageGuidance,depthInputType, ...extra });
    if (status) status = { ...status, settings: saved };
  }
  async function changeExtraction(value: typeof extractionMethod){
    if(busy||engineAction||engine?.active||interactionBuild||pendingRefinement)return;
    const previous=extractionMethod;extractionMethod=value;
    try{await saveSettings();await refreshStatus();if(api.desktop)engine=await api.engineStatus();notice=methodLabel[value]+' selected for the next extraction. Your current pose is kept.';}
    catch(e){extractionMethod=previous;error=String(e);}
  }
  async function changeClue(value:boolean){
    if(busy||engineAction||engine?.active||pendingRefinement)return;
    const previous=clueEnabled;clueEnabled=value;
    try{await saveSettings();notice='CLUE diagnostics '+(value?'on':'off')+' for the next extraction. Saved poses are kept.';}
    catch(e){clueEnabled=previous;error=String(e);}
  }
  async function changeCroppedJoints(value:boolean){
    if(busy||engineAction||engine?.active||interactionBuild||pendingRefinement)return;
    const previous=zeroCroppedJoints;zeroCroppedJoints=value;
    try{await saveSettings();notice='Zero cropped joints '+(value?'on':'off')+' for the next Smart Fit extraction. Your current pose is kept.';}
    catch(e){zeroCroppedJoints=previous;error=String(e);}
  }
  async function changeGuidance(value:GuidanceMode){
    if(busy||engineAction||pendingRefinement||interactionBuild)return;
    const previous=imageGuidance;imageGuidance=value;
    try{await saveSettings();notice='Image guidance updated for the next extraction. Your current pose is kept.';}
    catch(e){imageGuidance=previous;error=String(e);}
  }
  async function changeTheme(value: Theme) { theme = value; try { await saveSettings(); } catch (e) { error = String(e); } }
  async function dismissHint() { firstHint = false; try { await saveSettings({ onboarded: true }); } catch (e) { error = String(e); } }
  function closeDrawer(){if(drawer==='refine')void cancelRefinement();drawer=null;}
  function showHelp(query=helpSearch,topic=''){
    helpTrigger=document.activeElement instanceof HTMLElement?document.activeElement:undefined;
    if(drawer==='refine')void cancelRefinement();
    helpSearch=query;helpOpenTopic=topic;settingsReveal++;drawer='help';
    void tick().then(()=>{document.getElementById('drawer-content')?.scrollTo({top:0});document.getElementById('workspace-drawer')?.querySelector<HTMLElement>('h2')?.focus();});
  }
  function toggleDrawer(value: typeof drawer) { if(value==='help'){if(drawer==='help')closeDrawer();else showHelp();return;}if(drawer==='refine')void cancelRefinement();if(value==='history'&&drawer!=='history')historyTab=mode==='text'?'text':mode==='expression'?'expressions':mode==='editor'?'edits':'extractions';drawer = drawer === value ? null : value; }
  function selectSettingsCategory(value:SettingsCategory){settingsCategory=value;if(value==='engine'&&!busy)void textWorkspace?.refresh();document.getElementById('drawer-content')?.scrollTo({top:0});}
  function openSettings(category:SettingsCategory){if(category==='daz')void expressionWorkspace?.refreshProfiles();if(drawer==='refine')void cancelRefinement();selectSettingsCategory(category);settingsReveal++;drawer='settings';}
  function explainConfidence(){showHelp('confidence');}
  async function discardPreview(pending:Interaction){if(api.desktop&&pending.previewId)try{await api.request('refine',{version:2,policyVersion:1,operation:pending.operation,action:'cancel',imageId:pending.imageId,previewId:pending.previewId});}catch(e){console.warn(e);}}
  async function cancelRefinement(){
    refinementRevision++;const pending=pendingRefinement;pendingRefinement=null;showOriginal=false;pendingInput=[];pendingSnapshot=null;
    if(pending){view=previousRefineView;reset++;await discardPreview(pending);}
  }
  async function previewRefinement(contacts:Contact[],support:Support[],guidance:SideGuidance[],operation?:'spacing'){
    if(!api.desktop||busy||!photo||photo.detachedPose||!acceptedPoses.length)return;
    await cancelRefinement();
    const imageId=photo.id,revision=editRevision,previewRevision=refinementRevision,input=copyPoses(acceptedPoses);
    const before=captureEdit(input,editBaseline.length?editBaseline:input);
    const result=await job<Interaction>('refine',{version:2,policyVersion:1,operation,action:'preview',imageId,currentPoses:input,automatic:true,contacts,support,guidance});
    if(!result)return;
    if(photo?.id!==imageId||revision!==editRevision||previewRevision!==refinementRevision||drawer!=='refine'){await discardPreview(result);return;}
    pendingInput=input;pendingSnapshot=before;previousRefineView=view;pendingRefinement=result;showOriginal=false;view='side';reset++;
    notice='Preview only. Compare Side and Reference, then Apply or Cancel. Your accepted pose is unchanged.';
  }
  async function applyRefinement(){
    if(!api.desktop||busy||!photo||!pendingRefinement?.previewId||!pendingSnapshot)return;
    const imageId=photo.id,revision=editRevision,before=pendingSnapshot,previewId=pendingRefinement.previewId,input=copyPoses(pendingInput);
    if(editPoses.some(p=>p.edited)){const saved=await job('retarget',{editorOperation:'save_draft',imageId,poses:editPoses});if(!saved)return;}
    if(pendingRefinement?.previewId!==previewId||photo?.id!==imageId||revision!==editRevision)return;
    const result=await job<Interaction>('refine',{version:2,policyVersion:1,operation:pendingRefinement.operation,action:'apply',imageId,currentPoses:input,previewId,contacts:pendingRefinement.contacts??[]});
    if(!result||photo?.id!==imageId||revision!==editRevision)return;
    lastRefinement=result;
    undoStack=[...undoStack.slice(-39),before];redoStack=[];editBaseline=copyPoses(result.poses);editPoses=copyPoses(result.poses);interaction=result.poses.length>1?result:null;editRevision++;syncEdits();drawer=null;view='reference';reset++;
    pendingRefinement=null;pendingInput=[];pendingSnapshot=null;showOriginal=false;
    notice='Refinement applied. Inspect Reference and Side views. Undo restores the previous accepted pose.';
  }
  function adoptScene(next:Pose[],keepWorkspace=false){
    clearPose();selected=next[0].personId;editPoses=copyPoses(next);editBaseline=copyPoses(next);syncEdits();
    selectedBone=figureKey;editTool='select';jointGroup='body';drawer=null;reset++;
    if(!keepWorkspace){
      mode='editor';referenceCollapsed=!photo;previewCollapsed=false;actionsCollapsed=false;historyTab='edits';
    }
    if(view==='reference'&&!next[0].referenceCamera)view='front';
  }
  async function addMannequin(){
    if(busy||pendingRefinement||photo?.detachedPose)return;if(!finalPose){await newPose();return;}if(displayPoses.length>=4){notice='Four mannequins per studio keeps the workspace lightweight. Start a new pose for another scene.';return;}
    if(api.desktop&&!connected){error=status&&engine?.runtimeReady!==false?'Genesis rig metadata is unavailable. Re-extract the current app into a new folder.':'Set up the local engine in Settings to start posing.';return;}
    startEditing();const before=captureEdit();
    const result=api.desktop?await job<{poses:Pose[];selected:number}>('retarget',{editorOperation:'add_mannequin',poses:editPoses,rigId:rig}):devRigs[rig]?addedFixture(editPoses,devRigs[rig]!):null;
    if(!result)return;
    const baseline=result.poses.map(p=>{const base=before.baseline.find(b=>b.personId===p.personId);return base?{...copyPoses([base])[0],imageId:p.imageId,origin:p.origin,studio:p.studio,studioSource:p.studioSource,layout:undefined}:copyPoses([p])[0];});
    undoStack=[...undoStack.slice(-39),before];redoStack=[];editBaseline=baseline;editPoses=copyPoses(result.poses);selected=result.selected;interaction=null;editRevision++;syncEdits();selectedBone=figureKey;editTool='translate';reset++;notice='Mannequin added. Select any mannequin in the tray; Export figure converts the selected one.';
    if(api.desktop)try{history=await api.request('history');}catch(e){error=String(e);}
  }
  function removeMannequin(){if(busy||editPoses.length<2||!editPoses[0].studio)return;const id=selected;recordEdit(editPoses.filter(p=>p.personId!==id).map(p=>({...p,layout:undefined})),editBaseline.filter(p=>p.personId!==id));interaction=null;reset++;notice='Mannequin removed from this studio. Undo brings it back.';}
  async function newPose(){
    if(busy||pendingRefinement||mode==='expression'||mode==='text')return;
    if(api.desktop&&!connected){error=status&&engine?.runtimeReady!==false?'Genesis rig metadata is unavailable. Re-extract the current app into a new folder.':'Set up the local engine in Settings to start posing.';return;}
    if(api.desktop&&editPoses.length&&finalPose&&!photo?.detachedPose){const saved=await job('retarget',{editorOperation:'save_draft',imageId:finalPose.imageId,poses:editPoses});if(!saved)return;}
    const next=api.desktop?await job<Pose>('retarget',{editorOperation:'new_pose',rigId:rig}):devRigs[rig]?blankPose(devRigs[rig]!,crypto.randomUUID()):null;
    if(!next)return;
    photo=null;people=[];interactionChoices={};adoptScene([next],true);
    notice='Neutral '+rigLabels[rig]+' pose ready. '+(mode==='editor'?'Choose a body part to begin.':'Open Pose studio to edit.');
    if(api.desktop)try{history=await api.request('history');}catch(e){error=String(e);}
  }
  function clearEdits(){editPoses=[];editBaseline=[];undoStack=[];redoStack=[];dragStart=null;selectedBone=figureKey;editRevision++;}
  function startEditing(){if(editPoses.length||!finalPose||photo?.detachedPose)return;editPoses=copyPoses(displayPoses);editBaseline=copyPoses(displayPoses);selectedBone=figureKey;}
  function syncEdits(){if(!editPoses.length)return;if(!editPoses.some(p=>p.personId===selected))selected=editPoses[0].personId;const active=editPoses.find(p=>p.personId===selected)!;rig=active.rigId;pose=active;sourceAvailable=!photo?.detachedPose&&(!!active.studioSource||active.origin!=='editor');placement=active.layout?'reference':'floor';if(selectedBone!==figureKey&&!active.rig.nodes.some(n=>n.id===selectedBone)){selectedBone=figureKey;editTool='translate';}}
  function switchMode(value:typeof mode){const started=import.meta.env.DEV?performance.now():0;if(busy||pendingRefinement)return;qualityOpen=false;notesOpen=false;if(drawer==='refine'||drawer==='interaction')drawer=null;mode=value;if(value==='editor')startEditing();if(value==='expression')void expressionWorkspace?.refreshProfiles();if(import.meta.env.DEV&&new URLSearchParams(location.search).has('profile'))void tick().then(()=>requestAnimationFrame(()=>{const shell=document.querySelector<HTMLElement>('.app-shell');if(shell)shell.dataset.switchMs=(performance.now()-started).toFixed(2);}));}
  function editGeneratedBody(poses:Pose[]){photo=null;people=[];adoptScene(poses);}
  function editGeneratedExpression(value:TextExpression){mode='expression';void expressionWorkspace.adoptText(value);}
  async function downloadTextComponent(id:string){await downloadComponents(id);if(error)throw Error(error);}
  function recordEdit(next:Pose[],baseline=editBaseline,protectPins=true){if(busy||pendingRefinement)return;startEditing();if(!editPoses.length)return;if(protectPins)next=next.map(p=>preservePins(p,p.personId===selected?selectedBone:figureKey));const key=(poses:Pose[])=>JSON.stringify(poses.map(p=>[p.personId,p.rigId,p.rotations,p.translation,p.rootRotation,p.layout,p.pins]));if(key(next)===key(editPoses))return;if(!dragStart){undoStack=[...undoStack.slice(-39),captureEdit()];redoStack=[];}editBaseline=copyPoses(baseline);editPoses=copyPoses(next);editRevision++;syncEdits();}
  function editPosition(values:number[]){if(selected===null)return;startEditing();recordEdit(moveFigure(editPoses,selected,values,linked));}
  function editFacing(value:FacingPreset){if(selected===null||busy||pendingRefinement)return;startEditing();const next=setFacing(editPoses,editBaseline,selected,value,linked);if(next===editPoses)return;recordEdit(next.map((p,i)=>p===editPoses[i]?p:preservePins(p,figureKey)),editBaseline,false);}
  function editFloorOffset(value:number){if(selected===null||busy||pendingRefinement)return;startEditing();const next=setFloorClearance(editPoses,selected,value,linked);if(next===editPoses)return;recordEdit(next.map((p,i)=>p===editPoses[i]?p:preservePins(p,figureKey)),editBaseline,false);}
  function editRotation(values:number[]){if(!finalPose||finalPose.pins?.[selectedBone]?.rotation)return;startEditing();recordEdit(editPoses.map(p=>p.personId===selected?rotateJoint(p,selectedBone,values):p));}
  function gizmoEdit(next:Pose){if(busy)return;startEditing();
    const members=selectedBone===figureKey&&editTool==='translate'?moveFigure(editPoses,next.personId,next.translation,linked).map(p=>p.personId===next.personId?next:preservePins(p)):editPoses.map(p=>p.personId===next.personId?next:p);
    // Preview already constrained this drag before placing the visible gizmo.
    recordEdit(members,editBaseline,false);
  }
  function dragEdit(active:boolean){if(active){startEditing();if(!dragStart&&editPoses.length)dragStart=captureEdit();}else if(dragStart){if(JSON.stringify(dragStart.poses.map(p=>[p.rotations,p.translation,p.rootRotation]))!==JSON.stringify(editPoses.map(p=>[p.rotations,p.translation,p.rootRotation]))){undoStack=[...undoStack.slice(-39),dragStart];redoStack=[];}dragStart=null;}}
  function captureEdit(poses=editPoses,baseline=editBaseline):EditSnapshot{
    return {...snapshot(poses,baseline,selected,selectedBone),refinement:lastRefinement,interaction};
  }
  function restoreSnapshot(next:EditSnapshot){editPoses=copyPoses(next.poses);editBaseline=copyPoses(next.baseline);lastRefinement=next.refinement??null;interaction=next.interaction??null;selected=next.selected;selectedBone=next.bone;editRevision++;syncEdits();if(editTool==='translate'&&selectedBone!==figureKey&&!isReachJoint(selectedBone))editTool='rotate';notice='Previous accepted pose restored.';error='';}
  function undoEdit(){if(busy||pendingRefinement||!undoStack.length)return;redoStack=[...redoStack,captureEdit()];const next=undoStack.at(-1)!;undoStack=undoStack.slice(0,-1);restoreSnapshot(next);}
  function redoEdit(){if(busy||pendingRefinement||!redoStack.length)return;undoStack=[...undoStack,captureEdit()];const next=redoStack.at(-1)!;redoStack=redoStack.slice(0,-1);restoreSnapshot(next);}
  function resetEdit(all:boolean){if(busy)return;startEditing();const base=editBaseline.find(p=>p.personId===selected);if(!base)return;
    const next=all?copyPoses(editBaseline.filter(p=>editPoses.some(e=>e.personId===p.personId))).map(p=>clearPins(p)):editPoses.map(p=>p.personId===selected?clearPins(resetSelection(p,base,selectedBone),selectedBone===figureKey?undefined:isReachJoint(selectedBone)?limbParents(p,selectedBone).at(-1)?.id??selectedBone:selectedBone,true):p);
    recordEdit(next,editBaseline,false);notice='Reset applied. Affected pins cleared; Undo restores pose and pins.';
  }
  function zeroEdit(withChildren:boolean){if(busy||pendingRefinement)return;startEditing();const next=editPoses.map(p=>p.personId===selected?clearPins(zeroSelection(p,selectedBone,withChildren),selectedBone===figureKey?undefined:selectedBone,true):p);if(next.every((p,i)=>p===editPoses[i]))return;recordEdit(next,editBaseline,false);notice='Zeroing applied · '+(withChildren?'Selected joint and children':'Selected only')+' · Affected pins cleared · Undo restores this edit.';error='';}
  function pinJoint(component:'position'|'rotation'){if(!finalPose||busy||pendingRefinement)return;startEditing();recordEdit(editPoses.map(p=>p.personId===selected?togglePin(p,selectedBone,component):p),editBaseline,false);}
  function unpinAll(){if(busy||pendingRefinement)return;startEditing();recordEdit(editPoses.map(p=>p.personId===selected?clearPins(p):p),editBaseline,false);}
  function chooseJoint(bone:string){if(busy)return;startEditing();selectedBone=bone;const member=editPoses.find(p=>p.personId===selected)??finalPose;if(member)jointGroup=chooserGroup(member,bone,jointGroup);editTool=bone===figureKey||isReachJoint(bone)?'translate':'rotate';editAxis='all';}
  function selectJoint(person:number,bone:string){if(busy)return;void selectPerson(person);chooseJoint(bone);}
  async function reachTarget(target:number[]){if(!api.desktop||busy||pendingRefinement||!finalPose||target.some(v=>!Number.isFinite(v)))return;startEditing();const revision=editRevision,person=selected,imageId=finalPose.imageId;const result=await job<{pose:Pose;distanceCm:number;reached:boolean}>('retarget',{editorOperation:'reach',pose:finalPose,poses:editPoses,bone:selectedBone,target});if(!result||revision!==editRevision||person!==selected||imageId!==finalPose?.imageId)return;recordEdit(editPoses.map(p=>p.personId===person?result.pose:p));notice=result.reached?'Reach target fitted · '+result.distanceCm.toFixed(2)+' cm from target.':'Closest bounded fit is '+result.distanceCm.toFixed(2)+' cm from target. Move the figure or choose a nearer target; Undo restores the limb.';}
  async function saveDraft(){if(!api.desktop||busy||pendingRefinement||!finalPose)return;startEditing();if(!editPoses.length)return;const result=await job('retarget',{editorOperation:'save_draft',imageId:finalPose.imageId,poses:editPoses});if(result){notice='Studio draft saved locally in History → Pose edits.';historyTab='edits';try{history=await api.request('history');}catch(e){error=String(e);}}}
  async function loadDraft(){if(!api.desktop||busy||pendingRefinement||!finalPose)return;const imageId=finalPose.imageId,revision=editRevision;const result=await job<{poses:Pose[]}>('retarget',{editorOperation:'load_draft',imageId});if(!result||finalPose?.imageId!==imageId||revision!==editRevision)return;adoptScene(result.poses);notice='Local studio draft restored. Inspect all views before exporting.';}
  async function job<T>(method: string, payload: unknown): Promise<T|null> {
    if(engineAction||engine?.active){notice='Finish engine setup before starting a pose task.';return null;}
    const id = crypto.randomUUID(); activeJob = id; busy = true; percent = 0; error = ''; notice = '';
    const operation=(payload as {editorOperation?:string})?.editorOperation;
    stage = operation==='convert_pose'?'Converting edited pose':operation==='add_mannequin'?'Adding a mannequin':operation==='new_pose'?'Starting a neutral pose':operation==='save_draft'?'Saving studio draft':operation==='load_draft'?'Restoring studio draft':method === 'refine' ? 'Refining image match and contacts' : method === 'detect' ? 'Finding people' : method === 'solve' ? 'Preparing local extraction' : method === 'connect_figure' ? 'Reading the selected DAZ figure' : method === 'retarget' ? 'Retargeting the cached pose' : 'Working locally';
    try { const result = await api.request<T>(method, payload, id); return activeJob === id ? result : null; }
    catch (e) { if (activeJob === id) error = String(e); return null; }
    finally { if (activeJob === id) { activeJob = ''; busy = false; stage = ''; } }
  }
  async function stop() { if(!activeJob&&mode==='text'){await textWorkspace.cancel();return;}if(!activeJob&&mode==='expression'){await expressionWorkspace.cancel();return;}interactionBuild = ''; activeJob = ''; error = '';try{await api.cancel();notice = 'Cancelled. Your reference and saved results are kept.';}catch(e){error='Cancellation could not be confirmed. Your reference and saved results are kept. '+String(e);}finally{busy=false;stage='';} }
  function clearPose() { void cancelRefinement();clearEdits(); interaction = null;lastRefinement=null;qualityOpen=false; if(placement==='reference')placement='keep'; pose = null; sourceAvailable = false; notesOpen = false; }
  async function loadPath(path: string) {
    if(mode==='text')return;if(mode==='expression'){await expressionWorkspace.loadPath(path);return;}
    if (busy) await stop();
    const image = await job<Photo>('import_image', { path,kind:inputCategory==='photo'?'photo':depthImportKind }); if (!image) return;
    if(!await findPeople(image,false,true))return;
    referenceCollapsed=false;previewCollapsed=false;actionsCollapsed=false;historyTab='extractions';
    try { history = await api.request('history'); } catch (e) { error = String(e); }
  }
  async function openImage() { if(busy||engineAction||engine?.active)return;if(mode==='text')return;if(mode==='expression'){await expressionWorkspace.open();return;}if (!api.desktop) return; try { const path = await api.pickImage(); if (typeof path === 'string') await loadPath(path); } catch (e) { error = String(e); } }
  async function paste() { if(busy||engineAction||engine?.active)return;if(mode==='text')return;if(mode==='expression'){await expressionWorkspace.paste();return;}if (!api.desktop) return;if(mode==='extract'&&inputCategory==='depth'&&depthInputType==='metric'){error='Import the original PNG or TIFF for metric depth. Clipboard images can lose numeric precision.';return;} try { await loadPath(await api.clipboard()); } catch (e) { error = String(e); } }
  async function selectPerson(id: number) { if (selected === id) return; if (busy) await stop();
    const member=editPoses.find(p=>p.personId===id)??interaction?.poses.find(p=>p.personId===id);if(editPoses[0]?.studio&&!member){notice='This reference person is not in the studio. Open their extraction from History to start editing it.';return;}selected = id;selectedBone=figureKey;editTool='translate';
    if(member){pose=member;rig=member.rigId;sourceAvailable=!photo?.detachedPose&&(!!member.studioSource||member.origin!=='editor');notesOpen=false;}else clearPose();
    error = ''; if(!photo?.detachedPose)notice = (people.find(p => p.id === id)?.score ?? 1) < .6 ? 'Lower-confidence detection. Check this subject and inspect hidden limbs after extraction.' : ''; }
  async function extract() {
    if (extractDisabled || !photo || selected === null) return;
    const started=performance.now(),operationId=crypto.randomUUID();
    const method=extractionFor(extractionMethod),policyChanged=!groupActive&&pose?.extractionMethod==='smart'&&method==='smart'&&(pose.cropPolicy?.enabled??false)!==zeroCroppedJoints;
    const refresh=pose!==null&&!policyChanged,wasGroup=groupActive;
    const result = await job<Pose>('solve', { imageId: photo.id, personId: selected, rigId: rig, refresh,refinement,zeroCroppedJoints,currentPoses:policyChanged&&pose?[pose]:[],extractionMethod:method,imageGuidance });
    if (result) { clearEdits();if(wasGroup)clearPose();notice='Pose extracted in '+formatElapsed(performance.now()-started)+'.'+guidanceStatus([result])+' Inspect the preview before exporting.';lastRefinement=null;pose = result; sourceAvailable = true; interactionChoices={...interactionChoices,[selected]:{chosen:true,rigId:rig}};reset++;recordCreation(operationId); try { history = await api.request('history'); } catch (e) { error = String(e); } }
  }
  function arrangeInteraction(){
    if(busy || pendingRefinement || people.length<2)return;
    interactionChoices=Object.fromEntries(people.map((p,i)=>[p.id,interactionChoices[p.id]??{chosen:i<4,rigId:rig}]));drawer='interaction';
  }
  async function buildInteraction(){
    if(!api.desktop || busy || !photo || chosenMembers.length<2 || chosenMembers.length>4)return;
    const members=chosenMembers.map(m=>({...m,sourceGuidance:undefined as Pose['sourceGuidance']})),method=extractionFor(extractionMethod,true);
    const missing=members.find(m=>!status?.rigs.includes(m.rigId));
    if(missing){error=status&&engine?.runtimeReady!==false?'Genesis rig metadata is unavailable for '+rigLabels[missing.rigId]+'. Re-extract the current app into a new folder.':'Set up the local engine in Settings to start posing.';return;}
    const started=performance.now(),imageId=photo.id,buildId=crypto.randomUUID();interactionBuild=buildId;
    try {
    for(const member of members){
      const extracted=await job<{personId:number;sourceReady:boolean;sourceGuidance?:Pose['sourceGuidance']}>('solve',{imageId,...member,refinement,extractionMethod:method,zeroCroppedJoints,extractionContext:'interaction',prepareInteraction:true,imageGuidance});
      if(!extracted || interactionBuild!==buildId || photo?.id!==imageId)return;
      member.sourceGuidance=extracted.sourceGuidance;
    }
    const result=await job<Interaction>('retarget',{imageId,members,extractionMethod:method,zeroCroppedJoints,imageGuidance,currentPoses:interaction?.imageId===imageId?interaction.poses:[],contacts:interaction?.imageId===imageId?interaction.contacts??[]:[]});
    if(!result || interactionBuild!==buildId || photo?.id!==imageId)return;
    clearPose();interactionBuild='';interaction=result;lastRefinement=result;selected=members.some(m=>m.personId===selected)?selected:members[0].personId;
    pose=result.poses.find(p=>p.personId===selected)!;rig=pose.rigId;sourceAvailable=true;placement='reference';drawer=null;reset++;
    recordCreation(buildId,members.length);
    notice='Interaction extracted in '+formatElapsed(performance.now()-started)+'.'+guidanceStatus(result.poses)+' Select each person here and the matching figure in DAZ, then apply using Reference layout.';
    } finally {if(interactionBuild===buildId)interactionBuild='';}
  }
  async function exitInteraction(){
    if(!api.desktop||busy||pendingRefinement||!photo||selected===null||!connected)return;
    const selection={imageId:photo.id,personId:selected,rigId:rig},preference=extractionMethod,revision=editRevision;
    try{
      const result=await individualAfterInteraction(selection,preference,payload=>job<Pose>('solve',payload),
        ()=>photo?.id===selection.imageId&&selected===selection.personId&&rig===selection.rigId&&extractionMethod===preference&&editRevision===revision);
      if(!result)return;
      clearEdits();interaction=null;lastRefinement=null;qualityOpen=false;
      pose=result;sourceAvailable=true;placement='keep';notesOpen=false;reset++;
      notice='Individual extraction · '+methodLabel[result.extractionMethod!]+' · Keep scene position.';
    }catch(e){error=String(e);}
  }
  async function retargetCached() {
    if (!sourceAvailable || !photo || photo.detachedPose || selected === null || !connected) return;
    const result = await job<Pose>('retarget', { imageId: photo.id, personId: selected, rigId: rig, extractionMethod:pose?.extractionMethod??extractionMethod,sourceGuidance:pose?.sourceGuidance??{version:1,id:'original'} });
    if (result) { pose = result; reset++; }
  }
  async function changeRig(target:RigId){
    if(generationLocked)return;
    if((mode==='editor'||editPoses.length>0)&&finalPose){
      const current=finalPose;if(target===current.rigId)return;
      if(api.desktop&&!status?.rigs.includes(target)){error=status&&engine?.runtimeReady!==false?'Genesis rig metadata is unavailable for '+rigLabels[target]+'. Your current edits are kept. Re-extract the current app into a new folder.':'Set up the local engine in Settings to start posing. Your current edits are kept.';return;}
      startEditing();const baseline=editBaseline.find(p=>p.personId===selected)??current,revision=editRevision,chosenTool=editTool;
      let result:{pose:Pose;baseline:Pose}|null=null;
      if(api.desktop)result=await job('retarget',{editorOperation:'convert_pose',pose:current,poses:editPoses,baseline,baselines:editBaseline,rigId:target});
      else if(import.meta.env.DEV){busy=true;error='';try{const response=await fetch('/__studio-convert',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pose:current,baseline,rigId:target})});const converted=await response.json();if(!response.ok)throw Error(converted.error);result=converted;}catch(e){error=String(e);}finally{busy=false;}}
      if(!result||revision!==editRevision)return;
      const bone=matchingJoint(current,result.pose,selectedBone);recordEdit(editPoses.map(p=>p.personId===current.personId?result!.pose:p),editBaseline.map(p=>p.personId===current.personId?result!.baseline:p));selectedBone=bone;editTool=chosenTool==='translate'&&bone!==figureKey&&!isReachJoint(bone)?'rotate':chosenTool;reset++;notice='Edited pose converted to '+rigLabels[target]+'. Position and partner poses kept.'+(Object.keys(current.pins??{}).length?' Pins recaptured for this rig.':'')+' Undo restores the previous generation.';return;
    }
    rig=target;clearEdits();if(selected!==null)interactionChoices={...interactionChoices,[selected]:{chosen:true,rigId:rig}};if(!pose&&!sourceAvailable)return;await retargetCached();
  }
  async function chooseDaz() { if (!api.desktop || busy) return; try { const path = await api.pickDaz(); if (typeof path === 'string') { dazExecutable = path; await saveSettings(); } } catch (e) { error = String(e); } }
  async function connectFigure() {
    if (!api.desktop || busy) return;
    if (!dazExecutable) { await chooseDaz(); if (!dazExecutable) return; }
    const target=connectionRig??rig;
    const result = await job<{ rigId: RigId }>('connect_figure', { rigId: target, executable: dazExecutable });
    if (result) { try { await refreshStatus(); if(target===rig&&!editPoses.length&&!photo?.detachedPose){clearEdits();interaction=null;if(placement==='reference')placement='keep';pose=null;await retargetCached();} notice = rigLabels[result.rigId] + ' connected. Its metadata is cached inside PoseSnap.'; } catch (e) { error = String(e); } }
  }
  async function saveDuf() {
    if (!finalPose || busy || pendingRefinement || !api.desktop) return;
    try { const path = await api.savePose((photo?.name.replace(/\.[^.]+$/, '') ?? 'PoseSnap') + '-person-' + selected + '-' + rig); if (path) { const result = await job<{ path: string }>('export', { path, pose: finalPose, placement }); if (result) notice = 'Saved ' + result.path; } } catch (e) { error = String(e); }
  }
  async function applyDaz() {
    if (!finalPose || busy || pendingRefinement || !api.desktop) return;
    if (!dazExecutable) { openSettings('daz'); error = 'Choose DAZ Studio 6’s application, then retry.'; return; }
    const result = await job<{ figure: string; maximumError: number; warnings?: string[] }>('apply', { pose: finalPose, placement, executable: dazExecutable });
    if (result) notice = ['Applied to ' + result.figure + ' · verified within ' + result.maximumError.toFixed(3) + '°', ...(result.warnings ?? [])].join(' · ');
  }
  async function openHistory(item: HistoryItem) {
    if (busy||pendingRefinement) return;
    if(item.kind==='text'){switchMode('text');drawer=null;await textWorkspace.restore(item);return;}
    if(item.kind==='expression'){switchMode('expression');drawer=null;await expressionWorkspace.restore(item);return;}
    if(item.kind==='pose'){
      const result=await job<{poses:Pose[]}>('retarget',{editorOperation:'load_draft',imageId:item.id});if(!result)return;
      if(result.poses[0].origin==='editor'){const source=result.poses.find(p=>p.studioSource)?.studioSource;if(source){const image=await job<Photo>('read_image',{imageId:source.imageId});if(!image)return;photo=image;people=image.people;}else{photo=null;people=[];}adoptScene(result.poses);}
      else {const image=await job<Photo>('read_image',{imageId:item.id});if(!image)return;clearPose();photo=image;people=image.people;editPoses=copyPoses(result.poses);editBaseline=copyPoses(result.poses);selected=result.poses[0].personId;syncEdits();mode='editor';drawer=null;referenceCollapsed=false;previewCollapsed=false;actionsCollapsed=false;reset++;}
      notice='Local pose draft opened.';return;
    }
    const result = await job<Photo>('read_image', { imageId: item.id, restorePose: true, rigId: rig });
    if(!result)return;
    const {historyResult,...reference}=result;
    clearPose();
    photo=historyResult?.detached?{...reference,people:[],detachedPose:true}:reference;
    people=photo.people;interactionChoices={};
    selected=people.length===1?people[0].id:null;
    if(mode==='expression'||mode==='text')mode='extract';
    referenceCollapsed=false;previewCollapsed=false;drawer=null;reset++;
    if(historyResult){
      const {poses,result:saved,refined}=historyResult;
      pose=poses[0];selected=pose.personId;rig=pose.rigId;sourceAvailable=!historyResult.detached;
      if(historyResult.detached)overlay=false;
      interaction=poses.length>1?saved??null:null;
      if(!historyResult.detached)interactionChoices=Object.fromEntries(poses.map(p=>[p.personId,{chosen:true,rigId:p.rigId}]));
      placement=interaction?'reference':(pose.footSupport??[]).some(foot=>foot.state==='air')?'floor':'keep';
      if(saved){
        lastRefinement=saved;
      }
      if(view==='reference'&&!pose.referenceCamera)view='front';
      notice=historyResult.detached?'Saved pose restored. Recheck people to start a new extraction from this reference.':refined?'Saved refinement restored.':'Saved pose restored.';
    }else{
      notice=item.solved?'The saved pose is unavailable. The reference and people were restored.':'Reference restored.';
    }
  }
  async function findPeople(image: Photo, refresh = false, adopt = false) {
    const found = await job<Person[]>('detect', { imageId: image.id, refresh });
    if (!found||!adopt&&photo?.id!==image.id)return false;
    clearPose();selected=found.length===1?found[0].id:null;interactionChoices={};people = found; photo = { ...image, people: found, detachedPose: false }; if (!found.length) notice = 'No people found. Try a clearer reference with more visible anatomy.';
    if (found?.some(p => p.detector === 'yolox-s')) notice = 'Basic detector active. The interaction-aware local checkpoint is missing; touching people may be missed. Check Settings.';
    return true;
  }
  async function recheckPeople() { if (photo && !busy && api.desktop) await findPeople(photo, true); }
  async function removeHistory(item: HistoryItem) {
    if(busy)return false;
    busy=true;error='';
    try{
      if(item.kind==='text')await api.request('text_remove',{id:item.id});
      else await api.request('remove_history',{imageId:item.id,kind:item.kind,...(item.kind==='expression'?{faceId:item.faceId,observationId:item.observationId}:{})});
      await refreshHistory();
      if(item.kind!=='text'&&item.kind!=='expression'&&(item.kind!=='pose'&&photo?.id===item.id||manualPose&&finalPose?.imageId===item.id)){
        photo=null;clearPose();people=[];selected=null;referenceCollapsed=false;
      }
      return true;
    }catch(e){error=String(e);return false;}
    finally{busy=false;}
  }
  function resizeReference(event: PointerEvent) {
    event.preventDefault(); (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
    const bounds = (event.currentTarget as HTMLElement).parentElement!.getBoundingClientRect();
    const move = (e: PointerEvent) => setReferenceWidth((e.clientX-bounds.left)/bounds.width*100);
    const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); window.removeEventListener('pointercancel',up); };
    window.addEventListener('pointermove', move); window.addEventListener('pointerup', up); window.addEventListener('pointercancel',up);
  }
  function setReferenceWidth(value:number){referenceWidth=Math.max(25,Math.min(55,value));}
  function keyboard(event: KeyboardEvent) {
    if (event.defaultPrevented) return;
    if(supportOpen){if(event.ctrlKey||event.metaKey)event.preventDefault();return;}
    if (event.key === 'Escape') { event.preventDefault(); if (curtain) dismissStartup(); else if (historyRemoval) {if(!busy)historyRemoval=null;} else if (drawer) closeDrawer(); else if (mode==='expression'&&expressionWorkspace?.closeNotes()) return; else if (mode==='text'&&textWorkspace?.closeNotes()) return; else if (qualityOpen) qualityOpen = false; else if (notesOpen) notesOpen = false; else if (busy) void stop(); return; }
    if (event.key === 'F1') { event.preventDefault(); showHelp(); return; }
    if (curtain) return;
    const textEntry=event.target instanceof HTMLInputElement||event.target instanceof HTMLTextAreaElement||event.target instanceof HTMLSelectElement;
    if(mode==='editor'&&!drawer&&!textEntry&&!busy){if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='z'){event.preventDefault();event.shiftKey?redoEdit():undoEdit();return;}if(!event.ctrlKey&&!event.metaKey&&!event.altKey&&['q','w','e'].includes(event.key.toLowerCase())){event.preventDefault();if(event.key.toLowerCase()==='q')editTool='select';else if(event.key.toLowerCase()==='w'){if(selectedBone!==figureKey&&!isReachJoint(selectedBone))selectedBone=figureKey;editTool='translate';}else editTool='rotate';return;}}
    if (event.ctrlKey || event.metaKey) {
      const key = event.key.toLowerCase(), textEntry = event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement;
      if (key === 'o') { event.preventDefault(); void openImage(); }
      else if (key === 'n' && !textEntry && (mode==='extract'||mode==='editor')) { event.preventDefault(); void newPose(); }
      else if (key === 'v' && !textEntry) { event.preventDefault(); void paste(); }
      else if (key === 'enter') { event.preventDefault(); if(mode==='text')void textWorkspace.preview();else if(mode==='expression')void expressionWorkspace.extract();else void extract(); }
    }
  }
  onMount(() => {
    let unlisten = () => {}, undrop = () => {}, unengine=()=>{}, disposed = false;
    const observer = new ResizeObserver(() => { const r = referenceCanvas.getBoundingClientRect(); referenceSize = { width: Math.max(1, r.width - 32), height: Math.max(1, r.height - 32) }; });
    observer.observe(referenceCanvas); window.addEventListener('keydown', keyboard);
    const openLink=(event:MouseEvent)=>{void handleExternalLink(event,api.desktop,api.openExternalUrl,value=>error=String(value));};
    document.addEventListener('click',openLink);document.addEventListener('auxclick',openLink);
    const visibility = () => visible = document.visibilityState === 'visible'; document.addEventListener('visibilitychange', visibility);
    (async () => {
      try {
        bootLabel = api.desktop ? 'Checking the private runtime' : 'Opening the development preview';
        if(api.desktop){
          unengine=await api.engineEvents(value=>engine=value);
          engine=await api.engineStatus();
          await manageEngine('check');
          if(disposed){unengine();return;}
        }
        await refreshStatus();
        bootLabel = 'Restoring local preferences';
        if (status) { theme = status.settings.theme; motion = status.settings.motion ?? 'auto'; jointSelector=status.settings.jointSelector??'buttons'; extractionMethod=status.settings.extractionMethod??'auto'; clueEnabled=status.settings.clueEnabled??false; zeroCroppedJoints=status.settings.zeroCroppedJoints??true; imageGuidance=status.settings.imageGuidance??'auto'; depthInputType=status.settings.depthInputType??'relative'; dazExecutable = status.settings.dazExecutable; firstHint = !status.settings.onboarded; }
        preferencesReady=true;bootLabel = 'Loading local history';
        if (api.desktop&&engine?.runtimeReady) history = await api.request('history');
        historyReady=true;
        if (import.meta.env.DEV) {
          const params = new URLSearchParams(location.search), preset = params.get('theme');
          if (preset === 'dark' || preset === 'neon' || preset === 'light') theme = preset;
          if (params.has('validation')) {
            const query=new URLSearchParams();if(params.get('scenario')==='dancing')query.set('dancing','1');else if(params.get('scenario')==='posture-preview')query.set('posture','1');else if(params.has('refinement'))query.set('refinement','1');if(params.has('pure'))query.set('pure','1');
            if(params.has('targetFit'))query.set('targetFit','1');
            const response = await fetch('/__validation?'+query); if (!response.ok) throw new Error('The local development fixture is unavailable.');
            const fixture = await response.json();devRigs=fixture.rigs??{}; photo = fixture.photo; people = fixture.photo.people; selected = fixture.pose.personId; rig = fixture.pose.rigId; pose = fixture.pose; sourceAvailable = true;
            if(['interaction','posture-preview'].includes(params.get('scenario')??'') && fixture.interaction){interaction=fixture.interaction;placement='reference';interactionChoices=Object.fromEntries(interaction!.poses.map(p=>[p.personId,{chosen:true,rigId:p.rigId}]));}
            if(params.get('scenario')==='posture-preview'&&fixture.preview){pendingInput=copyPoses(fixture.interaction.poses);pendingSnapshot=snapshot(pendingInput,pendingInput,selected,selectedBone);pendingRefinement=fixture.preview;drawer='refine';view='side';notice='Development preview of a real isolated worker fit. Apply is available in the desktop app.';}
            status = { version: appVersion, root: 'Development preview', models: {}, ready: true, rigs: ['g8f','g8m','g9'], settings: { theme, motion, dazExecutable: '', onboarded: true }, python: 'Private runtime', offline: true };
            if (params.get('scenario') === 'empty') { photo = null; people = []; selected = null; clearPose(); }
            if (params.get('scenario') === 'unselected') { selected = null; pose = null; }
            if (params.get('scenario') === 'single' && photo) { people = people.filter(p => p.id === selected); photo = { ...photo, people }; }
            if(params.get('scenario')==='interaction'&&params.has('building')){drawer='interaction';busy=true;stage='Building interaction · development preview';percent=62;}
            if (params.get('scenario') === 'processing') { busy = true; stage = 'Refining body and fingers · development state'; percent = 62; }
            if (params.get('scenario') === 'error') error = 'DAZ did not acknowledge the pose. Close any blocking dialogs, check the selected figure and retry.';
            if (params.get('scenario') === 'startup-error') throw new Error('Private runtime unavailable. Restore the app runtime folder, then relaunch PoseSnap.');
            if (params.has('hint')) firstHint = true;
            if(params.get('scenario')?.startsWith('engine-')){const response=await fetch('/__engine-validation'+(params.get('scenario')==='engine-missing'?'?missing=1':''));if(!response.ok)throw Error('Engine UI fixture unavailable');engine=await response.json();if(params.get('scenario')==='engine-running'){busy=true;stage='Refining body and fingers · development fixture';percent=62;}openSettings('engine');}
          }
          if (params.get('motion') === 'reduced') motion = 'reduced';
          if (params.has('curtain')) { bootLabel = 'Development startup preview'; return; }
        }
        bootLabel = 'Preparing the mannequin';
        unlisten = await api.progress(value => { if (value.jobId === activeJob) { percent = value.percent; stage = value.label; } });
        if (api.desktop) { const { getCurrentWebviewWindow } = await import('@tauri-apps/api/webviewWindow'); undrop = await getCurrentWebviewWindow().onDragDropEvent(event => { dragOver = event.payload.type === 'over'; if (event.payload.type === 'drop') { dragOver = false; const path = event.payload.paths[0]; if (path) void loadPath(path); } }); }
        if (disposed) { unlisten(); undrop(); unengine(); } else loaded = true;
      } catch (e) { error = String(e); dismissStartup(); }
    })();
    return () => { disposed = true; observer.disconnect(); unlisten(); undrop(); unengine(); window.removeEventListener('keydown', keyboard); document.removeEventListener('visibilitychange', visibility);document.removeEventListener('click',openLink);document.removeEventListener('auxclick',openLink); };
  });
</script>

<div class="app" data-theme={theme} data-motion={motion} data-visible={visible}>
  <div class="app-shell" inert={curtain||supportOpen}>
    <header class="topbar">
      <div class="brand"><img src="/logo.svg" alt="PoseSnap"/><span>Pose<b>Snap</b><small>PHOTO TO POSE</small></span></div>
      <div class="file-actions">
        {#if mode!=='expression'&&mode!=='text'}<button class="header-button new-pose" aria-disabled={busy||!api.desktop&&!devRigs[rig]} use:tooltip={busy?'Finish or cancel the current task first.':'Start a neutral '+rigLabels[rig]+' pose. Edit it in Pose studio · Ctrl+N'} onclick={newPose}><Plus size={16}/> New pose</button>{/if}
        <span class="tip-host" use:tooltip={mode==='text'?'Text to Pose accepts text. Use Extract pose or Expression studio for images.':busy ? 'Cancel the current task before opening another image.' : 'Choose a local photo or realistic render · Ctrl+O'}><button class="header-button" onclick={openImage} disabled={mode==='text'} aria-disabled={mode==='text'||busy || !api.desktop&&mode!=='expression'}><ImagePlus size={16}/> Open image</button></span>
        <span class="tip-host" use:tooltip={mode==='text'?'Text to Pose accepts text. Use Extract pose or Expression studio for images.':busy ? 'Cancel the current task before pasting another image.' : 'Import the image on your clipboard · Ctrl+V'}><button class="header-button subtle" onclick={paste} disabled={mode==='text'} aria-disabled={mode==='text'||busy || !api.desktop}><ClipboardPaste size={16}/> Paste</button></span>
      </div>
      <nav class="mode-switch" aria-label="Workspace mode">{#each [{id:'extract',label:'Extract pose'},{id:'editor',label:'Pose studio'},{id:'expression',label:'Expression studio'},{id:'text',label:'Text to Pose'}] as item}<button class:active={mode===item.id} aria-pressed={mode===item.id} aria-disabled={busy} use:tooltip={busy?'Finish or cancel the current task before switching tools.':item.id==='text'?'Create body poses with Kimodo. Optional approximate hand shapes.':item.id==='extract'?'Extract poses from your reference. Manual edits remain when switching modes.':item.id==='expression'?'Extract a selected face’s expression locally. Body poses and studio edits are kept.':'Refine figure position and joint rotations. Changes affect preview and export.'} onclick={()=>switchMode(item.id as typeof mode)}>{#if item.id==='text'}<MessageSquareText size={14}/>{:else if item.id==='extract'}<ScanLine size={14}/>{:else if item.id==='expression'}<Smile size={14}/>{:else}<Settings2 size={14}/>{/if}{item.label}</button>{/each}</nav>
      <div class="top-actions">
        <button class="header-button engine-badge" data-state={engineDisplay.state} aria-label={'Engine · '+engineDisplay.label} aria-expanded={drawer==='settings'&&settingsCategory==='engine'} aria-controls="workspace-drawer" use:tooltip={engineDisplay.detail+' Open Engine settings for components, downloads and recovery.'} onclick={()=>openSettings('engine')}><Cpu size={14}/><EngineLight state={engineDisplay.state} label={engineDisplay.label}/></button>
        <button class="header-button subtle" class:active={drawer === 'history'} aria-label="History" aria-expanded={drawer === 'history'} aria-controls="workspace-drawer" use:tooltip={"Reopen or search references saved locally."} onclick={() => toggleDrawer('history')}><History size={16}/> <span class="header-label">History</span> {#if history.length}<span class="count">{history.length}</span>{/if}</button>
        <button class="header-button help-button" class:active={drawer === 'help'} aria-label="Help" aria-expanded={drawer === 'help'} aria-controls="workspace-drawer" use:tooltip={"Feature guide, Quick start and troubleshooting · F1"} onclick={() => toggleDrawer('help')}><CircleHelp size={17}/> <span class="header-label">Help</span></button>
        <button class="icon-button" aria-label="Settings" aria-expanded={drawer==='settings'} aria-controls="workspace-drawer" use:tooltip={"Appearance, Pose studio, extractions, body and facial connections, and engine settings."} onclick={() => toggleDrawer('settings')}><Settings2 size={18}/></button>
      </div>
    </header>
    <main class="workspace">
      <ExpressionWorkspace bind:this={expressionWorkspace} active={mode==='expression'} {theme} {engine} {dazExecutable} onengine={()=>openSettings('engine')} onsettings={()=>openSettings('daz')} onhistory={()=>void refreshHistory()} onprofiles={value=>faceProfiles=value} onstate={value=>expressionBaseline=value} onsupportblocked={value=>expressionPending=value} ontask={(value,label)=>{busy=value;stage=label;}}/>
      <TextWorkspace bind:this={textWorkspace} active={mode==='text'} watchRuntime={drawer==='settings'&&settingsCategory==='engine'} {theme} settings={status?.settings??{}} {dazExecutable} onsettings={()=>openSettings('engine')} onpromptguide={()=>showHelp('Kimodo prompt guide','kimodo-start')} onpreferences={saveSettings} ondaz={()=>openSettings('daz')} onbody={editGeneratedBody} onexpression={editGeneratedExpression} onhistory={()=>void refreshHistory()} onstatus={value=>textRuntime=value} onsupportblocked={value=>textPending=value} ontask={(value,label)=>{busy=value;stage=label;}}/>
      {#if mode!=='expression'&&mode!=='text'&&api.desktop&&engine&&!engine.ready&&!engine.active}<div class="engine-onboarding"><Cpu size={18}/><p><strong>Set up your local engine.</strong> {engine.message}</p><button class="text-button" onclick={()=>openSettings('engine')} use:tooltip={'View required files, available downloads and offline import options.'}>Engine &amp; downloads <ArrowRight size={14}/></button></div>{/if}
      {#if firstHint}<div class="first-use"><span><Zap size={14}/> {mode==='text'?'New here? Choose your characters, describe a body pose, then preview and Apply.':mode==='expression'?'New here? Open a reference, choose a face, then extract its expression.':'New here? Open a reference, pick a person, then extract.'}</span><button class="text-button" use:tooltip={"Read the four-step guide in Help."} onclick={() => showHelp('')}>Quick start <ArrowRight size={14}/></button><button class="icon-button" aria-label="Dismiss first-use hint" use:tooltip={"Hide this hint. Help remains available."} onclick={dismissHint}><X size={14}/></button></div>{/if}
      <div class="canvas-pair" hidden={mode==='expression'||mode==='text'} inert={mode==='expression'||mode==='text'} class:refinement-open={drawer==='refine'} class:reference-hidden={referenceCollapsed} class:preview-hidden={previewCollapsed} style={'--reference-width:' + referenceWidth + '%'}>
        <section class="reference-panel" class:collapsed={referenceCollapsed} class:drag-over={dragOver} aria-label="Reference image">
          <div class="panel-heading"><div><button class="panel-toggle icon-button" aria-label={referenceCollapsed?'Expand Reference':'Collapse Reference'} aria-expanded={!referenceCollapsed} aria-controls="reference-content" use:tooltip={referenceCollapsed?'Reopen the photograph and people picker.':'Collapse the reference to give the preview more room. Your selection stays saved.'} onclick={()=>referenceCollapsed=!referenceCollapsed}>{#if referenceCollapsed}<ChevronRight size={15}/>{:else}<ChevronLeft size={15}/>{/if}</button><span class="step-number">01</span><h2>Reference</h2></div>{#if !referenceCollapsed}{#if photo}<button class="text-button recheck" use:tooltip={busy ? 'Finish or cancel the current task first.' : 'Run local person detection again. Clears the current selection and preview.'} aria-disabled={busy || !api.desktop} onclick={recheckPeople}><ScanLine size={13}/> Recheck people</button>{:else}<span class="panel-detail">Start with an image</span>{/if}{/if}</div>
          <div class="panel-body" id="reference-content" hidden={referenceCollapsed} inert={referenceCollapsed}>
          <div class="reference-scroll">
          {#if mode==='extract'}<div class="guidance-reference-controls"><ImageGuidanceControl value={imageGuidance} disabled={busy||!!pendingRefinement} onchange={changeGuidance}/><label class="guidance-kind">Add as<select aria-label="Input type for new images" disabled={busy} bind:value={inputCategory} use:tooltip={'Applies to the next image import. Depth originals retain their precision; no RGB depth predictor is run on an existing depth map.'}><option value="photo">Photo</option><option value="depth">Depth ({depthInputType==='metric'?'Metric':'Relative'})</option></select></label></div>{/if}
          <div class="reference-canvas" class:empty-reference={!photo} bind:this={referenceCanvas}>
            {#if photo}
              <div class="photo-wrapper" style={'width:' + imageSize.width + 'px;height:' + imageSize.height + 'px'}>
                <img src={photo.url} alt={photo.name}/>
                {#if overlay&&finalPose?.quality?.markers&&!finalPose.edited&&!finalPose.quality.stale}<svg class="photo-landmarks" viewBox={'0 0 '+photo.width+' '+photo.height} aria-label="Observed hand, foot and body landmarks">{#each finalPose.quality.markers as point}<circle cx={point.xy[0]} cy={point.xy[1]} r="5"/>{/each}</svg>{/if}
                {#each people as person}
                  <button class="person-box" class:chosen={person.id === selected} style={'left:' + person.box[0]/photo.width*100 + '%;top:' + person.box[1]/photo.height*100 + '%;width:' + (person.box[2]-person.box[0])/photo.width*100 + '%;height:' + (person.box[3]-person.box[1])/photo.height*100 + '%'} aria-label={'Select person ' + person.id} aria-pressed={person.id === selected} use:tooltip={'Select person ' + person.id + '. Use the head marker or thumbnail when boxes overlap.'} onclick={() => selectPerson(person.id)}>{#if !person.anchor}<span>{person.id}</span>{/if}</button>
                  {#if person.anchor}<button class="person-marker" class:chosen={person.id === selected} style={'left:' + person.anchor[0]/photo.width*100 + '%;top:' + person.anchor[1]/photo.height*100 + '%'} aria-label={'Select person ' + person.id + ' by head marker'} aria-pressed={person.id === selected} use:tooltip={'Person ' + person.id + ' · ' + Math.round(person.score*100) + '% detection confidence. Inspect occluded limbs after extraction.'} onclick={() => selectPerson(person.id)}>{person.id}</button>{/if}
                {/each}
              </div>
            {:else}<div class="drop-zone"><div class="import-symbol"><ImagePlus size={36} strokeWidth={1.3}/></div><h1>Your reference.<br/><span>Your next pose.</span></h1><p>Drop a photo here to begin.<br/>Everything stays on your PC.</p><button class="primary" use:tooltip={"Choose a local PNG, JPG, WEBP, BMP or TIFF."} onclick={openImage} aria-disabled={!api.desktop || busy}><FolderOpen size={16}/> Open image</button><span class="file-hint">or paste with Ctrl+V</span></div>{/if}
          </div>
          {#if photo?.detachedPose&&mode==='extract'&&acceptedPoses.length>1}
            <div class="person-picker">
              <div class="picker-heading"><span><Users size={14}/> Saved participants</span></div>
              <div class="studio-members" role="group" aria-label="Saved participants">
                {#each acceptedPoses as member (member.personId)}
                  <button class:active={member.personId===selected} aria-pressed={member.personId===selected}
                    disabled={busy} use:tooltip={'Select this saved pose for preview and export.'} onclick={()=>selectPerson(member.personId)}>
                    Person {member.personId} · {rigLabels[member.rigId]}
                  </button>
                {/each}
              </div>
            </div>
          {/if}
          {#if people.length}<div class="person-picker"><div class="picker-heading"><span><Users size={14}/>{sourceSelection === null ? (editPoses[0]?.studio?'Reference image':'Choose one person') : 'Person ' + sourceSelection + ' selected'}</span><span>{people.length} detected</span></div><div class="people">{#each people as person}<button class:selected={sourceSelection === person.id} aria-pressed={sourceSelection === person.id} use:tooltip={'Select person ' + person.id + (interaction ? ' to inspect and export their coordinated pose.' : ' for body and finger extraction.')} onclick={() => selectPerson(person.id)}><img src={person.thumbnail} alt=""/><span>{person.id}</span>{#if sourceSelection === person.id}<Check size={13}/>{/if}</button>{/each}</div>{#if people.length>1&&!editPoses[0]?.studio}<div class="interaction-actions"><button class="text-button" aria-disabled={busy} use:tooltip={busy ? 'Finish or cancel the current task first.' : 'Choose two to four people and their Genesis generations, then coordinate their placement and probable contacts.'} onclick={arrangeInteraction}><Users size={13}/>{groupActive ? 'Edit interaction' : 'Arrange interaction'}</button>{#if groupActive}<button class="text-button" aria-disabled={busy} use:tooltip={'Return to individual extraction and Keep scene position.'} onclick={exitInteraction}>Exit</button>{/if}</div>{/if}</div>{/if}
          {#if photo?.inputKind==='metric-depth'}{#key photo.id}<ReferenceDepthControls imageId={photo.id} {busy} {job}/>{/key}{/if}
          {#if photo}{#key photo.id}<ReferenceMaps imageId={photo.id} kind={photo.inputKind} {busy} {job} onsetup={()=>openSettings('engine')}/>{/key}{/if}
          <div class="reference-footer">{#if photo}<span use:tooltip={photo.name}>{photo.name}</span><span>{photo.width} × {photo.height}</span>{:else}<ShieldCheck size={13}/><span>Local photos. Private processing.</span>{/if}</div>
          </div>
          </div>
        </section>
        <button class="resize-handle" hidden={referenceCollapsed||previewCollapsed} aria-label="Resize reference panel" use:tooltip={"Drag to resize. When focused, use left/right arrows."} onpointerdown={resizeReference} onkeydown={(e) => { if (e.key === 'ArrowLeft') { e.preventDefault(); setReferenceWidth(referenceWidth-2); } if (e.key === 'ArrowRight') { e.preventDefault(); setReferenceWidth(referenceWidth+2); } }}><span></span></button>
        <section class="preview-panel" class:collapsed={previewCollapsed} aria-label="3D pose preview">
          <div class="panel-heading preview-heading">
            <div><button class="panel-toggle icon-button" aria-label={previewCollapsed?'Expand Pose preview':'Collapse Pose preview'} aria-expanded={!previewCollapsed} aria-controls="preview-content" use:tooltip={previewCollapsed?'Restore the mannequin and editing controls.':'Collapse the preview. Your pose and editor selection stay intact.'} onclick={()=>previewCollapsed=!previewCollapsed}>{#if previewCollapsed}<ChevronLeft size={15}/>{:else}<ChevronRight size={15}/>{/if}</button><span class="step-number">02</span><h2>Pose preview</h2>{#if !previewCollapsed}<span class="state-tag" use:tooltip={manualPose?'A pose started in the editor; no neural confidence score applies.':finalPose?.edited?'Manually edited pose. Extraction scores describe the source solve.':finalPose?'Ready for inspection and export.':'The source mannequin is in its original rest stance.'}>{manualPose?'Custom pose':finalPose?.edited?'Edited':finalPose?'Ready':'Neutral'}</span>{/if}</div>
            {#if !previewCollapsed}
              {#if finalPose&&!manualPose}<div class="pose-confidence" aria-label="Extraction measurements">{#if confidence!==undefined}<button class="confidence-stat" onclick={explainConfidence} use:tooltip={'Person detection confidence, not 3D pose accuracy.'}>Detection <b>{Math.round(confidence*100)}%</b></button>{/if}<button class="confidence-stat" aria-expanded={qualityOpen} aria-controls="pose-quality" onclick={()=>qualityOpen=!qualityOpen} use:tooltip={finalPose.edited||finalPose.quality?.stale?'Open extraction measurements from before these edits.':finalPose.quality?.version===2?'Open image agreement. Higher fit is better; depth remains uncertain.':finalPose.extractionMethod==='pure'?'SAM source-body agreement before Genesis retargeting; hands and feet are excluded.':'Open legacy body measurements. Hands and feet are excluded.'}>{finalPose.edited||finalPose.quality?.stale?'Fit before edits':finalPose.quality?.version===2?'Visible 2D fit':finalPose.extractionMethod==='pure'?'SAM body fit':'Legacy body fit'} <b>{visibleAgreement?.matched!=null?Math.round(visibleAgreement.matched*100)+'%':'Unavailable'}</b>{#if finalPose.quality?.coverage}<small>{finalPose.quality.coverage.observed}/{finalPose.quality.coverage.expected}</small>{/if}</button></div>{/if}
              <button class="icon-button" aria-label="Fit mannequin in view" use:tooltip={"Reframe the entire mannequin without changing its pose."} onclick={() => reset++}><Maximize2 size={16}/></button>
            {/if}
          </div>
          <div class="panel-body" id="preview-content" hidden={previewCollapsed} inert={previewCollapsed}>
          <div class="preview-stage" class:has-editor={mode==='editor'}><div class="preview-canvas"><Preview active={mode!=='expression'&&mode!=='text'&&!previewCollapsed} {overlay} pose={finalPose} {companions} originalPoses={pendingRefinement&&showOriginal?acceptedPoses:[]} {theme} {view} showGrid={grid} {reset} focus={jointFocus} editing={mode==='editor'&&!photo?.detachedPose&&!busy&&!pendingRefinement} {selectedBone} tool={editTool} space={editSpace} snap={editSnap} axis={editAxis} handles={jointHandles} {ghostPartners} {jointGroup} onSelect={selectJoint} onEdit={gizmoEdit} onDrag={dragEdit} onReady={problem=>{if(problem){error=problem;dismissStartup();}else previewReady=true;}} onCameraProfile={profile=>cameraProfile=profile}/>
            {#if qualityOpen&&finalPose?.quality}
              <div class="quality-popover" id="pose-quality" role="region" aria-label="Image agreement">
                <div class="quality-heading"><h3>Image agreement</h3><button class="icon-button" aria-label="Close image agreement" onclick={()=>qualityOpen=false} use:tooltip={"Close the fit breakdown · Escape."}><X size={14}/></button></div><p class="fit-reading"><b>Higher fit is better.</b> Lower pixel error is better.</p>
                <p>{finalPose.edited||finalPose.quality.stale?'These measurements describe the extraction before your edits.':finalPose.quality.version===2?'Measured on the final Genesis pose. Fit counts observed points within tolerance.':finalPose.extractionMethod==='pure'?'Pure measurement: sparse SAM source body only, before Genesis retargeting. Fingers and feet are not scored.':'Legacy measurement: source body only, before Genesis fitting.'}</p>
                {#if finalPose.quality.coverage}<p class="fit-coverage">Coverage: <b>{finalPose.quality.coverage.observed}/{finalPose.quality.coverage.expected}</b> landmarks observed. Missing points are excluded; a high fit with low coverage is less informative.</p>{/if}
                {#if finalPose.quality.fit}
                  {@const fit=finalPose.quality.fit}
                  <p class="fit-coverage"><b>{fit.outcome==='full'?'Full fit accepted':fit.outcome==='partial'?'Partial fit accepted':'Previous pose retained'}</b>{#if fit.outcome!=='full'}<br/>{fit.reason}{#if fit.placementPreserved} Placement alignment was preserved.{/if}{/if}</p>
                  {#each fit.regionalChanges.filter(change=>change.worsened) as change}<p>{change.region.replace('l_','Left ').replace('r_','Right ').replace('_',' ')} error increased during alignment: {change.beforeErrorPx.toFixed(1)} → {change.afterErrorPx.toFixed(1)} px. Inspect this region.</p>{/each}
                {/if}
                {#each Object.entries(finalPose.quality.regions??{}) as [region,score]}<div><span>{region.replace('l_','Left ').replace('r_','Right ')}</span><b>{score.matched==null?'Unknown':Math.round(score.matched*100)+'%'}</b><small>{score.count}/{score.expected} points · {score.meanErrorPx==null?'no evidence':score.meanErrorPx.toFixed(1)+' px error'}</small></div>{/each}
                {#if (lastRefinement??interaction)?.diagnostics.contactGaps?.length}<h3>Partner contacts</h3>{#each (lastRefinement??interaction)!.diagnostics.contactGaps??[] as contact}<div><span>Contact {contact.id.split(':').slice(0,2).join(' · ')}</span><b>{contact.gapCm.toFixed(1)} cm</b><small>{contact.gapCm>2?'Needs inspection':'Within 2 cm proxy gap'}</small></div>{/each}<p>Proxy overlap: {((lastRefinement??interaction)?.diagnostics.maximumProxyOverlapCm??0).toFixed(1)} cm.</p>{/if}
                {#if finalPose.quality.handAcceptance}<p>SAM hand fusion: left {finalPose.quality.handAcceptance.l?.accepted?'accepted':'rejected / uncertain'}, right {finalPose.quality.handAcceptance.r?.accepted?'accepted':'rejected / uncertain'}.</p>{/if}
                <p>Inspect Reference and Side views. Single-image depth and hidden anatomy remain uncertain.</p>
              </div>
            {/if}
            {#if !finalPose}<div class="neutral-label"><span>{mode==='editor'?'Start your next pose.':'Make the moment move.'}</span>{mode==='editor'?'Choose New pose to begin, or open a saved pose from History.':'Your extracted pose appears here.'}</div>{/if}
            </div>
            {#if mode==='editor'&&!photo?.detachedPose}<PoseEditor selectorStyle={jointSelector} pose={finalPose} baseline={editBaseline.find(p=>p.personId===selected)??null} {floorHeight} {selectedBone} bind:tool={editTool} bind:space={editSpace} bind:snap={editSnap} bind:axis={editAxis} bind:handles={jointHandles} bind:ghostPartners bind:jointGroup bind:linked group={groupActive} busy={busy||!!pendingRefinement} canUndo={undoStack.length>0} canRedo={redoStack.length>0} canDraft={api.desktop&&!!finalPose} canNew={api.desktop||!!devRigs[rig]} onNew={newPose} onSelect={chooseJoint} onFocus={()=>jointFocus++} onPosition={editPosition} onRotation={editRotation} onFacing={editFacing} onFloorOffset={editFloorOffset} onEditing={dragEdit} onUndo={undoEdit} onRedo={redoEdit} onReset={resetEdit} onZero={zeroEdit} onPin={pinJoint} onUnpinAll={unpinAll} onReach={reachTarget} onSave={saveDraft} onLoad={loadDraft}/>{/if}
            {#if mode==='editor'&&displayPoses.length}<div class="studio-tray" aria-label="Studio mannequins"><div class="studio-members">{#each displayPoses as member}<button class:active={member.personId===selected} aria-pressed={member.personId===selected} disabled={busy} use:tooltip={'Select mannequin '+member.personId+' · '+rigLabels[member.rigId]+'. Joint edits and export affect only this mannequin.'} onclick={()=>selectPerson(member.personId)}><Box size={13}/><span>{member.personId}</span><small>{member.rigId.toUpperCase()}</small></button>{/each}</div><button class="compact-button" disabled={busy||!!photo?.detachedPose||displayPoses.length>=4} onclick={addMannequin} use:tooltip={displayPoses.length>=4?'Four mannequins per lightweight studio. Start a new pose for another scene.':'Add a neutral mannequin beside these figures. Convert its generation using Export figure.'}><Plus size={13}/> Add mannequin</button><button class="icon-button" aria-label="Remove selected mannequin" disabled={busy||displayPoses.length<2||!editPoses[0]?.studio} use:tooltip={editPoses[0]?.studio?'Remove this mannequin from the studio. Undo brings it back.':'Add a mannequin to create an independent studio scene before removing reference participants.'} onclick={removeMannequin}><Trash2 size={13}/></button></div>{/if}
            <div class="preview-label" class:studio-label={mode==='editor'&&displayPoses.length>0} use:tooltip={!finalPose?'Neutral preview. Choose New pose to start editing, or extract a person from a photo.':groupActive ? 'Pearl is the selected person; violet mannequins show their partners. All use authoritative target channels.' : 'Original PoseSnap mannequin driven by the final target pose.'}><Box size={13}/>{mode==='editor'?(finalPose?'Mannequin '+finalPose.personId+' · '+rigLabels[finalPose.rigId]:'PoseSnap mannequin · Neutral preview'):groupActive ? 'Interaction · Person '+selected+' active' : 'PoseSnap mannequin'}</div>

            <div class="viewport-toolbar"><div class="camera-views" role="group" aria-label="Pose preview camera">{#each (finalPose?.referenceCamera?['reference','front','side','back']:['front','side','back']) as angle}<button class:active={cameraProfile === angle} aria-pressed={cameraProfile === angle} use:tooltip={'Inspect the pose from the ' + angle + ' camera.'} onclick={() => {view = angle;reset++;}}>{angle}</button>{/each}</div>{#if !photo?.detachedPose&&finalPose?.quality?.markers?.length}<button class:active={overlay} aria-label="Toggle landmark overlay" use:tooltip={"Show projected target landmarks. Reference view aligns them with the input camera."} onclick={()=>overlay=!overlay}><ScanLine size={15}/></button>{/if}<button class:active={grid} aria-pressed={grid} aria-label="Toggle floor grid" use:tooltip={"Show or hide the floor guide."} onclick={() => grid = !grid}><Grid2X2 size={15}/></button><button aria-label="Reset camera view" use:tooltip={"Reset the current camera position and zoom."} onclick={() => reset++}><RotateCcw size={15}/></button></div>
            {#if finalPose?.warnings.length}<button class="notes-button" class:active={notesOpen} aria-expanded={notesOpen} use:tooltip={"Review extraction and retargeting limitations before export."} onclick={() => notesOpen = !notesOpen}><AlertCircle size={14}/> Pose notes <span>{finalPose.warnings.length}</span></button>{/if}
            {#if notesOpen && finalPose}<div class="notes-popover"><h3>Pose notes</h3><ul>{#each finalPose.warnings as warning}<li>{warning}</li>{/each}</ul></div>{/if}
          </div>
          {#if mode==='extract'}<PreviewNotice kind="pose"/>{/if}
          <div class="preview-footer"><span><Cpu size={12}/>{!finalPose&&mode==='editor'?'Pose studio · Neutral preview':manualPose?'Manual pose · '+rigLabels[rig]:finalPose?.extractionMethod==='pure'?'Pure · SAM body + hands':finalPose?.extractionMethod==='smart'?'Genesis Smart Fit · Body + details':'Body + hand inference'}</span><span>{view==='reference'?'Reference camera locked · Front/Side to orbit':mode==='editor'&&finalPose?'Click a joint · Drag handles to edit':'Drag to orbit · Scroll to zoom'}</span></div>
          </div>
        </section>
        {#if referenceCollapsed&&previewCollapsed}<div class="workspace-rest"><Box size={30}/><h3>Panels collapsed</h3><button class="secondary" use:tooltip={'Restore both workspace panels.'} onclick={()=>{referenceCollapsed=false;previewCollapsed=false;}}>Show both panels</button></div>{/if}
      </div>
      <section class="action-dock" hidden={mode==='expression'||mode==='text'} inert={mode==='expression'||mode==='text'} class:collapsed={actionsCollapsed} aria-label="Extract and export">
        <div class="task-line" role="status" aria-live="polite" use:tooltip={error || notice || (busy ? stage + " · " + percent + "%" : "Local runtime and workflow status.")}>
          {#if error}<AlertCircle size={15}/><span class="task-error">{error}</span><button class="icon-button" aria-label="Dismiss error" use:tooltip={"Dismiss this error message."} onclick={() => error = ''}><X size={14}/></button>
          {:else if notice}<Check size={15}/><span>{notice}</span><button class="icon-button" aria-label="Dismiss notification" use:tooltip={"Dismiss this notification."} onclick={() => notice = ''}><X size={14}/></button>
          {:else if busy}<LoaderCircle size={14} class="spin"/><span>{stage}</span><strong>{percent}%</strong><progress max="100" value={percent} aria-label="Current task progress"></progress>
          {:else if !api.desktop}<ShieldCheck size={14}/><span>Development preview · Desktop launch enables local extraction and export.</span>
          {:else if !status||engine?.runtimeReady===false}<AlertCircle size={14}/><span>{engine?.runtimeReady ? 'Checking Genesis rig metadata…' : 'Set up the local engine in Settings to start posing.'}</span>
          {:else if !connected}<AlertCircle size={14}/><span>Genesis rig metadata is unavailable. Re-extract the current app into a new folder.</span>
          {:else if manualPose}<Box size={14}/><span>Edit your new pose, save a draft, or export it to DAZ.</span>
          {:else}<ShieldCheck size={14}/><span>{!photo ? 'Open a reference to begin.' : selected === null ? 'Choose a numbered person in your reference.' : finalPose ? 'Inspect the pose, then send it to DAZ or save a DUF.' : 'Ready to extract person ' + selected + '.'}</span>{/if}
          {#if busy&&actionsCollapsed}<button class="text-button" onclick={stop} use:tooltip={'Cancel this task while the actions are collapsed.'}>Cancel</button>{/if}
          <button class="icon-button dock-toggle" aria-label={actionsCollapsed?'Expand actions':'Collapse actions'} aria-controls="dock-controls" aria-expanded={!actionsCollapsed} use:tooltip={actionsCollapsed?'Show generation, placement and export actions.':'Collapse the action bar; task status remains visible.'} onclick={()=>actionsCollapsed=!actionsCollapsed}><ChevronDown size={15}/></button>
        </div>
        <div class="dock-controls" id="dock-controls" hidden={actionsCollapsed} inert={actionsCollapsed}>
          <div class="output-fields"><div class="field"><label for="generation">Export figure</label><select id="generation" value={rig} onchange={e=>{const target=e.currentTarget.value as RigId;e.currentTarget.value=rig;void changeRig(target);}} disabled={generationLocked} use:tooltip={busy?'Finish or cancel the current task first.':mode==='editor'?'Convert this mannequin’s current edited pose to another Genesis generation. Position and other mannequins stay intact.':groupActive?'Set generations in Edit interaction before rebuilding the layout.':'Retarget the extracted pose to this Genesis generation.'}><option value="g8f">Genesis 8 Female</option><option value="g8m">Genesis 8 Male</option><option value="g9">Genesis 9</option></select></div><div class="field"><label for="placement">Placement in DAZ</label><select id="placement" value={placement} onchange={e=>{if(referenceLayout)e.currentTarget.value='reference';else placement=e.currentTarget.value as Placement;}} onpointerdown={e=>{if(referenceLayout)e.preventDefault();}} onkeydown={e=>{if(referenceLayout && !['Tab','Escape'].includes(e.key))e.preventDefault();}} aria-disabled={referenceLayout} use:tooltip={referenceLayout ? 'Writes this person’s coordinated position around the DAZ scene origin. Apply every participant using this same layout. Exit interaction to use other placement policies.' : placement === 'keep' ? 'Preserve your DAZ figure’s scene position.' : placement === 'floor' ? 'Use the floor position displayed in the preview.' : 'Write the figure position as 0, 0, 0.'}>{#if referenceLayout}<option value="reference">Reference layout</option>{:else}<option value="keep">Keep scene position</option><option value="floor">{mode==='editor'?'Use studio position':'Match preview floor'}</option><option value="origin">Reset to origin</option>{/if}</select></div></div>
          <div class="dock-actions">
            {#if mode==='extract'&&!groupActive}<button class="extraction-method-badge" onclick={()=>openSettings('extractions')} use:tooltip={'Pure is recommended for a single person. Auto switches to Genesis Smart Fit when building interactions. Change the method in Settings.'}>{extractionMethod==='auto'?'Auto · ':''}{methodLabel[extractionFor(extractionMethod)]}</button>{/if}
            {#if finalPose&&photo&&!photo.detachedPose&&!manualPose&&(!finalPose.studio||acceptedPoses.length>1&&acceptedPoses.every(p=>p.referenceCamera))}<button class="secondary" disabled={busy||!api.desktop&&!import.meta.env.DEV} use:tooltip={api.desktop?'Automatically fit detected landmarks and partner contacts. Optional foot support controls are inside.':'Automatic refinement runs in the desktop app.'} onclick={()=>drawer='refine'}><Settings2 size={15}/> Refine match</button>{/if}
            {#if mode==='extract'&&undoStack.length}<button class="secondary" disabled={busy} onclick={undoEdit} use:tooltip={'Undo the last refinement as one operation.'}><RotateCcw size={14}/> Undo</button>{/if}
            {#if busy}<button class="secondary cancel-button" use:tooltip={"Stop this task and release the worker; preserve your reference."} onclick={stop}><X size={16}/> Cancel</button>{:else if mode==='editor'&&finalPose}<button class="secondary" onclick={saveDraft} disabled={!api.desktop||!!photo?.detachedPose} use:tooltip={api.desktop?'Save every mannequin in this studio to History → Pose edits.':'Draft saving is available in the desktop app.'}><Save size={15}/> Save draft</button>{:else if !manualPose}<span class="tip-host" use:tooltip={extractHint}><button class:primary={!finalPose} class:secondary={!!finalPose} onclick={extract} aria-disabled={extractDisabled}><ScanLine size={16}/>{finalPose ? 'Extract again' : 'Extract pose'}</button></span>{/if}
            <span class="tip-host" use:tooltip={finalPose && !busy && !pendingRefinement && api.desktop ? 'Apply to the selected matching figure in DAZ Studio 6. One undo step.' : outputHint}><button class:primary={!!finalPose} class:secondary={!finalPose} onclick={applyDaz} aria-disabled={busy || !!pendingRefinement || !finalPose || !api.desktop}><ArrowUpRight size={16}/> Open in DAZ Studio</button></span>
            <span class="tip-host" use:tooltip={finalPose && !busy && !pendingRefinement && api.desktop ? 'Save a local pose preset. DAZ need not be running once the rig is cached.' : outputHint}><button class="secondary" onclick={saveDuf} aria-disabled={busy || !!pendingRefinement || !finalPose || !api.desktop}><Download size={16}/> Save DUF</button></span>
          </div>
        </div>
      </section>
    </main>
    <footer class="app-footer"><span use:tooltip={"Photos, neural inference and local history remain on this PC."}><ShieldCheck size={12}/> Local & private</span><span class="creator">Made by Aitha and AI💕.</span><span use:tooltip={`PoseSnap v${appVersion} · Company: Aitha`}>v{appVersion}{developmentBuild?' · Development':''}</span></footer>
    {#if drawer}
      <Drawer title={drawer === 'help' ? 'Help' : drawer === 'history' ? 'History' : drawer === 'interaction' ? 'Arrange interaction' : drawer==='refine'?'Refine match':'Settings'} subtitle={drawer === 'help' ? 'Everything you need, right here.' : drawer === 'history' ? 'References and pose drafts, saved locally.' : drawer === 'interaction' ? 'One reference. One shared layout.' : drawer==='refine'?'Keep the posture. Refine the details.':'Make it yours.'} reveal={settingsReveal} returnFocus={drawer==='help'?helpTrigger:undefined} onclose={closeDrawer}>
        {#snippet navigation()}{#if drawer==='settings'}<SettingsTabs selected={settingsCategory} onselect={selectSettingsCategory}/>{/if}{/snippet}
        {#if drawer==='refine'&&photo}<RefineMatch canApply={api.desktop} {photo} poses={acceptedPoses} contacts={(lastRefinement??interaction)?.contacts??[]} support={(lastRefinement??interaction)?.supportOverrides??[]} guidance={lastRefinement?.guidance??[]} inferredSupport={(pendingRefinement??lastRefinement??interaction)?.diagnostics.support??[]} pending={pendingRefinement} {showOriginal} onOriginal={value=>showOriginal=value} {busy} hasEdits={editPoses.some(p=>p.edited)} onPreview={previewRefinement} onPreviewSpacing={contacts=>previewRefinement(contacts,[],[],'spacing')} onApply={applyRefinement} onChange={()=>void cancelRefinement()} onCancel={closeDrawer}/>
        {:else if drawer === 'help'}
          <div class="drawer-search"><Search size={16}/><input aria-label="Search Help" placeholder="Find a feature or answer…" bind:value={helpSearch} use:tooltip={"Search feature names, instructions and shortcuts."}/></div>
          {#if !helpSearch.trim()}<div class="quick-start-card"><span class="eyebrow">QUICK START</span><h3>{mode==='text'?'Your direction. Four simple steps.':mode==='expression'?'One face. Four simple steps.':'One photo. Four simple steps.'}</h3><ol><li>{mode==='text'?'Choose characters and figures':'Open a reference'}</li><li>{mode==='text'?'Describe your direction':mode==='expression'?'Choose your face':'Choose your person'}</li><li>{mode==='text'?'Preview, inspect and Apply':'Extract and inspect'}</li><li>Send to DAZ or save</li></ol><button class="secondary" use:tooltip={"Close Help and return to your workspace."} onclick={() => { drawer = null; void dismissHint(); }}>Got it, let’s start <ArrowRight size={14}/></button></div>{/if}
          <HelpTopics topics={filteredHelp} openTopic={helpOpenTopic} textMode={mode==='text'}/>
          {#if !filteredHelp.length}<p class="empty-copy">No matching topic. Try “floor”, “DAZ”, or “hands”.</p>{/if}
        {:else if drawer === 'history'}
          <div class="history-tabs" role="tablist" aria-label="History categories">{#each ['extractions','edits','expressions','text'] as category}<button id={'history-'+category} role="tab" aria-selected={historyTab===category} aria-controls="history-results" tabindex={historyTab===category?0:-1} class:active={historyTab===category} onclick={()=>historyTab=category as typeof historyTab} onkeydown={historyKey} use:tooltip={category==='text'?'Accepted text poses and expressions, with their original directions.':category==='expressions'?'Saved facial expressions, separate from body poses.':category==='edits'?'Saved editor drafts, including edits made from a photograph.':'Imported references and their original extractions.'}>{historyLabels[category as keyof typeof historyLabels]}<span>{history.filter(item=>historyCategory(item)===category).length}</span></button>{/each}</div>
          <div class="drawer-search"><Search size={16}/><input aria-label="Search history" placeholder={'Search '+historyLabels[historyTab].toLowerCase()+'…'} bind:value={historySearch} use:tooltip={'Search the '+historyLabels[historyTab]+' tab.'}/></div>
          {#if historyRemoval}<HistoryRemoval item={historyRemoval} {busy} oncancel={()=>historyRemoval=null} onconfirm={async()=>{const item=historyRemoval!;const removed=await removeHistory(item);if(removed)historyRemoval=null;return removed;}}/>{/if}
          <div id="history-results" inert={!!historyRemoval} role="tabpanel" aria-labelledby={'history-'+historyTab} tabindex="0">
            {#each filteredHistory as item ([item.kind??'reference',item.id,item.observationId??item.faceId??''].join('/'))}<article class="history-card"><button class="history-open" use:tooltip={item.kind==='text'?'Restore this accepted text result and its original direction.':item.kind==='expression'?'Restore this face’s expression, strength and regions. Body poses are kept.':item.kind==='pose'?'Restore this saved editor pose and its reference, if present.':item.solved?'Restore the saved pose and its reference.':'Reopen this reference and its detected people.'} onclick={() => openHistory(item)} aria-disabled={busy}><img src={item.thumbnail} alt=""/><span><strong>{item.name}</strong><small>{item.kind==='text'?'Text creation':item.kind==='expression'?'Facial expression':item.kind==='pose'?'Editor pose draft':item.solved?'Pose extracted':'Reference image'}</small></span></button><button class="icon-button" aria-label={'Remove ' + item.name + ' from local history'} use:tooltip={item.kind==='text'?'Remove this saved text result. Reference photos and Studio drafts are kept.':item.kind==='expression'?'Remove this saved expression. The photo, pose extraction and studio edits are kept.':item.kind==='pose'?'Remove this saved edit. Its original extraction and photo are kept.':'Remove this cached reference and its saved edits. Your original file is kept.'} onclick={() => {if(!busy)historyRemoval=item;}} disabled={busy}><Trash2 size={16}/></button></article>{/each}
            {#if !filteredHistory.length}<div class="drawer-empty"><History size={28}/><h3>{historySearch?'No matching items':historyTab==='text'?'Your text creations live here':historyTab==='expressions'?'Your expressions live here':historyTab==='edits'?'Your pose edits live here':'Your extractions live here'}</h3><p>{historySearch?'Try another name.':historyTab==='text'?'Preview a direction in Text to Pose, then Apply to keep it here.':historyTab==='expressions'?'Extract a face in Expression studio. Accepted expressions are saved locally.':historyTab==='edits'?'Choose New pose, or save a draft from Pose studio.':'Imported references and extractions will appear here.'}</p></div>{/if}
          </div>
        {:else if drawer === 'interaction'}
          <section class="interaction-guide"><span class="eyebrow">CHOOSE YOUR PARTICIPANTS</span><h3>Keep the moment together.</h3><p>Choose 2–4 people and the generation for each DAZ figure. Build extracts the chosen people locally, then fits a shared placement and probable contacts.</p></section>
          <div class="interaction-members">{#each people as person}<div class="interaction-member"><label use:tooltip={'Include person ' + person.id + ' in this interaction. Only checked people will be extracted.'}><input type="checkbox" checked={interactionChoices[person.id]?.chosen??false} disabled={busy || (!interactionChoices[person.id]?.chosen && chosenMembers.length>=4)} onchange={e=>interactionChoices={...interactionChoices,[person.id]:{rigId:interactionChoices[person.id]?.rigId??rig,chosen:e.currentTarget.checked}}}/><img src={person.thumbnail} alt=""/><span>Person {person.id}</span></label><select aria-label={'Generation for person ' + person.id} value={interactionChoices[person.id]?.rigId??rig} disabled={busy} use:tooltip={'Choose the generation of person ' + person.id + '’s target figure. Different generations can share the same interaction.'} onchange={e=>interactionChoices={...interactionChoices,[person.id]:{chosen:interactionChoices[person.id]?.chosen??false,rigId:e.currentTarget.value as RigId}}}>{#each Object.entries(rigLabels) as [id,label]}<option value={id}>{label}</option>{/each}</select></div>{/each}</div>
          <div class="interaction-info-card"><Link2 size={17}/><div><strong>Build locally. Connect optionally.</strong><p>Built-in Genesis rigs are ready to use. Optional figure connections are in <button class="inline-link" use:tooltip={'Read a selected figure’s rig without changing its scale or morphs.'} onclick={()=>openSettings('daz')}>Settings → DAZ Studio</button>. Current extractions from the chosen method are reused.</p><p><strong>{methodLabel[extractionFor(extractionMethod,true)]}</strong> · {extractionMethod==='auto'?'Auto chooses Smart Fit for partner contacts.':'Genesis Smart Fit is recommended for interactions.'} <button class="inline-link" onclick={()=>openSettings('extractions')} use:tooltip={'Choose Auto, Pure or Genesis Smart Fit for the next extraction.'}>Change method</button></p></div></div>
          <CroppedJointsSettings enabled={zeroCroppedJoints} disabled={busy||engineAction||!!engine?.active||!!pendingRefinement||!!interactionBuild} active={extractionFor(extractionMethod,true)==='smart'} onchange={changeCroppedJoints}/>
          <details class="interaction-details"><summary use:tooltip={'Read how hidden contacts and mannequin proportions affect the layout.'}>About depth &amp; contact estimates <ChevronDown size={13}/></summary><p>Hidden depth and contact are estimates. The mannequin follows rig proportions; custom Genesis morphs can need further adjustment. Use Pose studio and Side view to refine spacing and joints.</p></details>
          <div class="interaction-build-actions">
          <span class="tip-host" use:tooltip={busy ? 'Finish or cancel the current task first.' : !api.desktop ? 'Use the desktop app to build with local models.' : chosenMembers.length<2 ? 'Choose at least two people.' : 'Extract the checked participants and coordinate their target poses locally.'}><button class="primary wide" onclick={buildInteraction} aria-disabled={busy || !api.desktop || chosenMembers.length<2 || chosenMembers.length>4}><Users size={16}/>{busy ? 'Building locally…' : 'Build interaction'}</button></span>
          {#if busy}<button class="secondary wide" use:tooltip={'Cancel the complete interaction build and release GPU memory.'} onclick={stop}><X size={16}/> Cancel build</button>{/if}
          </div>
          <div class="interaction-export-guide"><h3>Apply one person at a time</h3><ol><li>Build and inspect the mannequins, especially from the side.</li><li>Choose a person thumbnail here and select their matching figure in DAZ.</li><li>Apply using Reference layout, then repeat for the other people.</li></ol><p>Use unparented figures. Your DAZ scales and character shapes stay intact. Reference layout writes shared positions around the scene origin; different proportions may need contact or floor adjustments. Separate DUFs carry those same positions. Each application has its own Undo step.</p></div>
        {:else}
          <div class="settings-page" id={'settings-panel-'+settingsCategory} role="tabpanel" aria-labelledby={'settings-tab-'+settingsCategory} tabindex="0">
          {#if settingsCategory==='engine'}
            <EnginePanel {engine} {busy} {stage} desktop={api.desktop} disabled={busy||engineAction||!!pendingRefinement} {clueEnabled} oncluechange={changeClue} ondownload={downloadComponents} onsetup={profile=>downloadComponents(undefined,profile)} onimport={importComponent} onverify={()=>manageEngine('verify')} onpause={pauseSetup}/>
            <TextSettings settings={status?.settings??{}} {engine} runtime={textRuntime} busy={busy||engineAction} {stage} onsave={saveSettings} ondownload={downloadTextComponent} onsetup={async()=>{await downloadComponents();if(error)throw Error(error);}} onimport={importComponent} onrefresh={()=>textWorkspace.refresh()} onkimodo={operation=>textWorkspace.manageKimodo(operation)}/>
          {:else if settingsCategory==='appearance'}
          <section class="settings-section appearance-settings"><h3>Your workspace, your style</h3>
            <fieldset class="theme-choices"><legend>Theme</legend>
              {#each ['dark', 'neon', 'light'] as option}
                <label class="theme-choice" class:chosen={theme === option} use:tooltip={option === 'dark' ? 'Charcoal surfaces with violet accents.' : option === 'neon' ? 'Electric yellow and magenta with subtle animated glow.' : 'Bright surfaces with violet accents.'}>
                  <input type="radio" name="theme" value={option} checked={theme === option} onchange={() => changeTheme(option as Theme)}/>
                  {#if option === 'dark'}<Moon size={19}/>{:else if option === 'neon'}<Zap size={19}/>{:else}<Sun size={19}/>{/if}
                  <span>{option === 'dark' ? 'Dark' : option === 'neon' ? 'Neon' : 'Light'}</span>
                </label>
              {/each}
            </fieldset>
            <p class="setting-note">Changes apply immediately and are saved locally.</p>
            <label for="motion">Motion preference</label><select id="motion" value={motion} onchange={(event) => { motion = event.currentTarget.value as 'auto'|'reduced'; void saveSettings().catch(e => error = String(e)); }} use:tooltip={"Windows reduced-motion settings always take precedence."}><option value="auto">Follow Windows preference</option><option value="reduced">Reduced motion</option></select><p>Neon ambience pauses while hidden. Reduced motion removes decorative movement and the curtain’s scale animation.</p>
          </section>
          {:else if settingsCategory==='studio'}
          <section class="settings-section"><h3>Choose how you pose</h3><fieldset class="selector-choices"><legend>Choose a body part</legend>{#each [{id:'buttons',title:'Joint buttons',description:'The familiar grouped joint list.'},{id:'map',title:'Body map',description:'Pick joints on a visual body and hand map.'}] as item}<label class:chosen={jointSelector===item.id} use:tooltip={item.description+' Both styles keep the same joints and precision controls.'}><input type="radio" name="joint-selector" value={item.id} checked={jointSelector===item.id} onchange={()=>{jointSelector=item.id as typeof jointSelector;void saveSettings().catch(e=>error=String(e));}}/><span><strong>{item.title}</strong><small>{item.description}</small></span></label>{/each}</fieldset><p>Switch styles anytime. Your selection, mannequin and pose stay intact.</p></section>
          {:else if settingsCategory==='extractions'}
          <section class="settings-section"><h3>How your next pose is extracted</h3><p>Choose the approach you prefer. Extraction stays local and includes SAM hand refinement.</p>
            <fieldset class="selector-choices"><legend>Extraction method</legend>
              {#each [{id:'auto',title:'Auto · Recommended',description:'Pure for one selected person. Genesis Smart Fit when building an interaction.'},{id:'pure',title:'Pure · Best for one person',description:'SAM’s body and hands, directly retargeted. Keeps the original pose estimate without extra landmark fitting.'},{id:'smart',title:'Genesis Smart Fit · Best for interactions',description:'Adds independent hand and foot measurements, then fits the pose and partner contacts to Genesis proportions.'}] as item}
                <label class:chosen={extractionMethod===item.id} use:tooltip={item.description+' Applies to your next extraction; existing poses stay intact.'}><input type="radio" name="extraction-method" value={item.id} checked={extractionMethod===item.id} disabled={busy||engineAction||engine?.active||!!interactionBuild||!!pendingRefinement} onchange={()=>changeExtraction(item.id as typeof extractionMethod)}/><span><strong>{item.title}</strong><small>{item.description}</small></span></label>
              {/each}
            </fieldset><p>Pure preserves the SAM-only method. Smart Fit can improve image agreement, but a single photograph leaves depth uncertain. Compare Reference and Side views before exporting.</p><p>Your current pose and saved studio edits are kept. Use Extract again or rebuild an interaction to use the new choice.</p>
            <ImageGuidanceControl value={imageGuidance} disabled={busy||engineAction||!!engine?.active||!!pendingRefinement} advanced onchange={changeGuidance} onsetup={()=>openSettings('engine')}/>
            <label for="depth-input-type">Depth input type</label><select id="depth-input-type" disabled={busy||engineAction} value={depthInputType} use:tooltip={'Applies to future Depth imports. Existing references keep their recorded encoding. This does not convert ShadeNet output into metric measurements.'} onchange={async event=>{const previous=depthInputType;depthInputType=event.currentTarget.value as typeof depthInputType;try{await saveSettings();}catch(e){depthInputType=previous;error=String(e);}}}><option value="relative">Relative</option><option value="metric">Metric</option></select><p>Relative describes nearer and farther. Metric requires known distance units and camera calibration. Existing references stay unchanged.</p>
            <CroppedJointsSettings enabled={zeroCroppedJoints} disabled={busy||engineAction||!!engine?.active||!!pendingRefinement||!!interactionBuild} active={extractionMethod!=='pure'} onchange={changeCroppedJoints}/>
          </section>
          <section class="settings-section"><h3>Body uncertainty · CLUE</h3><ClueSettings enabled={clueEnabled} disabled={busy||engineAction||!!engine?.active||!!pendingRefinement} installed={engine?engine.components.find(c=>c.id==='clue-body')?.state==='installed':null} onchange={changeClue}/></section>
        {:else if settingsCategory==='daz'}
          <section class="settings-section"><h3>Body rigs</h3><p>Built-in Genesis rigs work without a connection. Optionally read your selected figure’s rig. Scale and morphs stay untouched.</p><label for="daz-path">DAZ Studio 6 application</label><div class="path-field"><input id="daz-path" readonly value={dazExecutable || 'No application selected'} use:tooltip={dazExecutable || 'Choose DAZStudio.exe to connect and apply poses.'}/><button class="secondary" use:tooltip={"Choose your existing DAZStudio.exe. Nothing is installed."} onclick={chooseDaz} aria-disabled={busy || !api.desktop}>Choose</button></div><label for="connect-generation">Optional connection</label><select id="connect-generation" value={connectionRig??rig} disabled={busy} onchange={e=>connectionRig=e.currentTarget.value as RigId} use:tooltip={'Choose the matching generation of your selected figure in DAZ. This does not change your current pose.'}>{#each Object.entries(rigLabels) as [id,label]}<option value={id}>{label}</option>{/each}</select><div class="rig-connection-list">{#each Object.entries(rigLabels) as [id, label]}<span><span>{label}</span><b use:tooltip={bodyConnections.includes(id as RigId)?'Your optional rig connection is cached inside PoseSnap.':'Built-in rig ready. Extraction, posing and DUF export do not require a connection.'}>{bodyConnections.includes(id as RigId)?'Connected':'Default rig'}</b></span>{/each}</div><button class="secondary wide" use:tooltip={'Read or refresh the selected '+rigLabels[connectionRig??rig]+' rig in DAZ.'} onclick={connectFigure} aria-disabled={busy || !api.desktop}><Link2 size={15}/>{bodyConnections.includes(connectionRig??rig)?'Refresh selected figure':'Connect selected figure (optional)'}</button><p class="setting-note">Current export target: {rigLabels[rig]}</p></section><section class="settings-section"><h3>Facial connections</h3><p>Expression studio uses separate facial metadata. Connect each generation once; reading the selected face preserves the scene. Body connections are unchanged.</p><div class="rig-connection-list">{#each Object.entries(rigLabels) as [id,label]}<span><span>{label}</span><b use:tooltip={faceProfiles[id as RigId]?'Facial driver metadata is cached inside PoseSnap.':'Select a matching figure in DAZ, then connect its face.'}>{faceProfiles[id as RigId]?'Connected':'Not connected'}</b></span>{/each}</div><button class="secondary wide" disabled={busy||!api.desktop} use:tooltip={'Read or refresh facial controls for '+rigLabels[connectionRig??rig]+'. Select its matching figure in DAZ first.'} onclick={()=>expressionWorkspace.connect(connectionRig??rig)}><Smile size={15}/>{faceProfiles[connectionRig??rig]?'Refresh selected face':'Connect selected face'}</button><p>Missing or unsupported facial movements are listed in Expression studio → Expression notes. Custom facial shapes stay intact.</p></section>
          {:else}
          <AboutCreator/>
          <section class="settings-section asset-credits"><h3>Artist credits</h3><p><strong>Body mannequin</strong><br/><a href="https://sketchfab.com/3d-models/rigged-character-6ead91e980434073bfb15799d3e674bb" target="_blank" rel="noreferrer">Rigged Character</a> by <a href="https://sketchfab.com/BLENDERJO" target="_blank" rel="noreferrer">BLENDERJO</a> · <a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noreferrer">CC BY 4.0</a></p><p><strong>Expression face</strong><br/><a href="https://sketchfab.com/3d-models/face-sculpting-108th-female-b6638e38d0b24ec7be39b578df25727b" target="_blank" rel="noreferrer">Face Sculpting 108th (female)</a> by <a href="https://sketchfab.com/ComputerCats" target="_blank" rel="noreferrer">ComputerCat</a> · <a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noreferrer">CC BY 4.0</a></p><p class="asset-adaptation"><small>Adapted and rigged for PoseSnap’s preview. Genesis shapes may differ.</small></p></section>
          <div class="fit-guide"><strong>Local by design</strong><p>Photos, inference, settings and history stay inside your portable PoseSnap folder. Downloads fetch components; your photos are never uploaded.</p><p class="settings-credit">Made by Aitha and AI💕.</p></div>
          {/if}
          </div>
        {/if}
      </Drawer>
    {/if}
  </div>
  {#if curtain}<Curtain progress={startup.progress} label={startup.label} ready={startup.complete} workspaceReady={startup.workspaceReady} engineLabel={startup.engineLabel} checksLabel={startup.checksLabel} attention={startup.attention} reduced={motion === 'reduced'} onclose={dismissStartup}/>{/if}
  <SupportSystem ready={!curtain} blocked={busy||engineAction||!!engine?.active||!!drawer||!!error||!!pendingRefinement||!!interactionBuild||!!dragStart||dragOver||qualityOpen||notesOpen||firstHint||expressionPending||textPending} bind:open={supportOpen}/>
</div>



