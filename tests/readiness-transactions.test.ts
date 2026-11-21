import {describe,it,expect,vi} from 'vitest';
import {componentHandler} from './component-handlers';
const text='src/lib/text/TextWorkspace.svelte',app='src/App.svelte';
function deferred<T>(){let resolve!:(v:T)=>void;const promise=new Promise<T>(r=>resolve=r);return {promise,resolve};}
describe('missing private runtime recovery',()=>{
  it('directs New pose and mannequin creation to engine setup before metadata is known',async()=>{
    for(const status of [null,{rigs:[],python:'Not installed',ready:false}])for(const name of ['newPose','addMannequin']){
      const ctx={mode:'editor',busy:false,pendingRefinement:null,finalPose:{},displayPoses:[],photo:null,api:{desktop:true},connected:false,status,engine:{runtimeReady:false},error:'',job:vi.fn()};
      await componentHandler(app,name,ctx)();
      expect(ctx.error).toBe('Set up the local engine in Settings to start posing.');expect(ctx.job).not.toHaveBeenCalled();
    }
  });
  it('retains genuine missing-rig recovery after the runtime is available',async()=>{
    const ctx={mode:'editor',busy:false,pendingRefinement:null,api:{desktop:true},connected:false,status:{rigs:[],python:'private/python.exe'},engine:{runtimeReady:true},error:'',job:vi.fn()};
    await componentHandler(app,'newPose',ctx)();expect(ctx.error).toContain('Re-extract');expect(ctx.job).not.toHaveBeenCalled();
  });
  it('preserves existing scenes when native fallback blocks conversion or interaction',async()=>{
    const base={api:{desktop:true},status:{rigs:[],python:'Not installed'},engine:{runtimeReady:false},error:'',job:vi.fn(),busy:false,photo:{id:'kept'},chosenMembers:[{id:1,rigId:'g8f'},{id:2,rigId:'g9'}],extractionFor:()=> 'smart',extractionMethod:'auto',rigLabels:{},generationLocked:false,mode:'editor',finalPose:{rigId:'g8f'},editPoses:[{id:'kept'}]};
    for(const name of ['changeRig','buildInteraction']){const ctx={...base};await componentHandler(app,name,ctx)('g9');expect(ctx.error).toContain('Set up the local engine');expect(ctx.editPoses).toEqual([{id:'kept'}]);expect(ctx.job).not.toHaveBeenCalled();}
  });
});
describe('Text cancellation transactions',()=>{
  function context(){const ctx:any={busy:true,currentJob:'old',revision:1,error:'',notice:'',stage:'Generating',accepted:{id:'kept'},prompt:'A person dances',ontask:vi.fn(),refresh:vi.fn(),api:{desktop:true,cancel:vi.fn().mockRejectedValue(Error('IPC disconnected')),request:vi.fn()},progress:vi.fn()};return ctx;}
  it('unlocks after a rejected cancel without claiming confirmed shutdown',async()=>{const ctx=context();await componentHandler(text,'cancel',ctx)();expect(ctx.busy).toBe(false);expect(ctx.currentJob).toBe('');expect(ctx.ontask).toHaveBeenLastCalledWith(false,'');expect(ctx.error).toContain('could not be confirmed');expect(ctx.notice).not.toContain('unloaded');expect(ctx.accepted.id).toBe('kept');expect(ctx.prompt).toBe('A person dances');});
  it('rejects a late reply before it can feed the next generation stage',async()=>{const ctx=context(),reply=deferred<unknown>();ctx.api.request.mockReturnValue(reply.promise);const pending=componentHandler(text,'request',ctx)('text_plan',{});const rejection=expect(pending).rejects.toThrow('Cancelled result ignored');await componentHandler(text,'cancel',ctx)();reply.resolve({intent:{status:'plan'}});await rejection;expect(ctx.accepted.id).toBe('kept');});
  it('permits a later successful task after cancellation fails',async()=>{const ctx=context();await componentHandler(text,'cancel',ctx)();const result=await componentHandler(text,'work',ctx)('Next preview',async()=>42);expect(result).toBe(42);expect(ctx.busy).toBe(false);expect(ctx.error).toBe('');});
});
describe('Escape dismisses the visible overlay before work',()=>{
  function context(){return {supportOpen:false,curtain:false,historyRemoval:null,drawer:'help',busy:true,mode:'text',qualityOpen:false,notesOpen:false,closeDrawer:vi.fn(),stop:vi.fn(),expressionWorkspace:{closeNotes:vi.fn(()=>false)},textWorkspace:{closeNotes:vi.fn(()=>false)}};}
  const event=()=>({key:'Escape',defaultPrevented:false,preventDefault:vi.fn()});
  it('closes Help while preserving the running job',()=>{const ctx=context();componentHandler(app,'keyboard',ctx)(event());expect(ctx.closeDrawer).toHaveBeenCalledOnce();expect(ctx.stop).not.toHaveBeenCalled();});
  it('dismisses Text notes and only cancels when there is no overlay',()=>{const ctx:any=context();ctx.drawer=null;ctx.textWorkspace.closeNotes.mockReturnValue(true);componentHandler(app,'keyboard',ctx)(event());expect(ctx.stop).not.toHaveBeenCalled();ctx.textWorkspace.closeNotes.mockReturnValue(false);componentHandler(app,'keyboard',ctx)(event());expect(ctx.stop).toHaveBeenCalledOnce();});
  it('leaves the support countdown responsible for Escape',()=>{const ctx=context();ctx.supportOpen=true;componentHandler(app,'keyboard',ctx)(event());expect(ctx.closeDrawer).not.toHaveBeenCalled();expect(ctx.stop).not.toHaveBeenCalled();});
});
describe('New pose and history workspace',()=>{
  it('builds a neutral pose without changing the current mode or panel layout',()=>{
    for(const mode of ['extract','editor']){
      const neutral={personId:1,rigId:'g9'};
      const ctx={mode,referenceCollapsed:false,previewCollapsed:true,actionsCollapsed:true,clearPose:vi.fn(),selected:null,
        editPoses:[],editBaseline:[],copyPoses:(v:unknown)=>v,syncEdits:vi.fn(),selectedBone:'hip',figureKey:'figure',
        editTool:'rotate',jointGroup:'head',drawer:null,historyTab:'extractions',reset:0,view:'side',photo:null};
      componentHandler(app,'adoptScene',ctx)([neutral],true);
      expect(ctx).toMatchObject({mode,referenceCollapsed:false,previewCollapsed:true,actionsCollapsed:true,view:'side',
        selected:1,editPoses:[neutral],reset:1});
    }
  });
  it('selects every saved interaction member without rebinding detached detections',async()=>{
    const first={personId:1,rigId:'g8f'}, second={personId:2,rigId:'g9'};
    const group={poses:[first,second]};
    const ctx={mode:'extract',busy:false,pendingRefinement:null,rig:'g8f',clearPose:vi.fn(),overlay:true,
      job:vi.fn().mockResolvedValue({id:'saved',people:[{id:1},{id:2}],historyResult:{poses:group.poses,result:group,detached:true}}),
      photo:null,people:[],interactionChoices:{},selected:null,referenceCollapsed:false,previewCollapsed:false,
      drawer:'history',reset:0,pose:null,sourceAvailable:false,interaction:null,lastRefinement:null,
      placement:'keep',view:'front',notice:'',editPoses:[],figureKey:'figure',selectedBone:'figure',editTool:'select',error:'',notesOpen:false};
    await componentHandler(app,'openHistory',ctx)({id:'saved',solved:true});
    await componentHandler(app,'selectPerson',ctx)(2);
    expect(ctx).toMatchObject({photo:{detachedPose:true},people:[],pose:second,selected:2,sourceAvailable:false,placement:'reference'});
    expect(ctx.notice).toContain('Recheck people');
    expect(ctx.job).toHaveBeenCalledOnce();
  });
  it('restores an extraction and the saved figure immediately and uses no detector or solve',async()=>{
    const saved={personId:2,rigId:'g8m',rotations:{head:[12,0,0]}};
    const job=vi.fn().mockResolvedValue({id:'saved',people:[{id:1},{id:2}],historyResult:{poses:[saved]}});
    const ctx={mode:'extract',busy:false,pendingRefinement:null,rig:'g9',clearPose:vi.fn(),job,
      photo:null,people:[],interactionChoices:{},selected:null,referenceCollapsed:true,previewCollapsed:true,
      drawer:'history',reset:0,pose:null,sourceAvailable:false,interaction:null,placement:'floor',view:'side',notice:''};
    await componentHandler(app,'openHistory',ctx)({id:'saved',solved:true});
    expect(job).toHaveBeenCalledExactlyOnceWith('read_image',{imageId:'saved',restorePose:true,rigId:'g9'});
    expect(ctx).toMatchObject({pose:saved,selected:2,rig:'g8m',previewCollapsed:false,drawer:null,reset:1});
    expect(ctx.photo).not.toHaveProperty('historyResult');
  });
});
describe('replacement failures preserve the accepted Studio scene',()=>{
  function context(){return {mode:'editor',busy:false,pendingRefinement:null,photo:{id:'kept'},pose:{edited:true,pins:{hand:{position:true}}},selected:1,people:[{id:1}],clearPose:vi.fn(),clearEdits:vi.fn(),findPeople:vi.fn(),job:vi.fn().mockResolvedValue(null),api:{request:vi.fn()},extractDisabled:false,groupActive:true,rig:'g8f',refinement:'body',extractionMethod:'auto',zeroCroppedJoints:true,imageGuidance:'auto',inputCategory:'photo',depthImportKind:'relative-depth',extractionFor:vi.fn(()=> 'pure')};}
  it('keeps scene and selection when import or history read fails',async()=>{for(const name of ['loadPath','openHistory']){const ctx=context();await componentHandler(app,name,ctx)(name==='loadPath'?'missing.png':{id:'missing',kind:'image'});expect(ctx.clearPose).not.toHaveBeenCalled();expect(ctx.photo.id).toBe('kept');expect(ctx.selected).toBe(1);expect(ctx.pose.edited).toBe(true);}});
  it('keeps edits when detection or re-extraction fails',async()=>{const ctx=context();await componentHandler(app,'findPeople',ctx)({id:'new'},false,true);await componentHandler(app,'extract',ctx)();expect(ctx.clearPose).not.toHaveBeenCalled();expect(ctx.clearEdits).not.toHaveBeenCalled();expect(ctx.pose.pins.hand.position).toBe(true);});
});
describe('History removal failure feedback',()=>{
  it('reports failed deletion without mutating history or clearing the scene',async()=>{const ctx={busy:false,error:'',api:{request:vi.fn().mockRejectedValue(Error('Disk unavailable'))},refreshHistory:vi.fn(),history:[{id:'kept'}],clearPose:vi.fn()};expect(await componentHandler(app,'removeHistory',ctx)({id:'kept',kind:'text'})).toBe(false);expect(ctx.busy).toBe(false);expect(ctx.history).toEqual([{id:'kept'}]);expect(ctx.error).toContain('Disk unavailable');expect(ctx.clearPose).not.toHaveBeenCalled();});
  it('keeps inline feedback when deletion fails and prevents duplicate requests',async()=>{const reply=deferred<boolean>(),ctx={busy:false,pending:false,failure:'',onconfirm:vi.fn(()=>reply.promise)};const confirm=componentHandler('src/lib/HistoryRemoval.svelte','confirm',ctx),first=confirm();await confirm();expect(ctx.onconfirm).toHaveBeenCalledOnce();reply.resolve(false);await first;expect(ctx.pending).toBe(false);expect(ctx.failure).toContain('could not be confirmed');});
});

describe('prospective image guidance',()=>{
  it('keeps accepted poses and restores preferences when saving fails',async()=>{
    const accepted={id:'accepted',rotations:{hand:[21,0,0]}};
    const ctx={busy:false,engineAction:false,pendingRefinement:null,interactionBuild:'',imageGuidance:'auto',pose:accepted,saveSettings:vi.fn().mockRejectedValue(Error('Read-only settings')),notice:'',error:''};
    await componentHandler(app,'changeGuidance',ctx)('off');
    expect(ctx.imageGuidance).toBe('auto');expect(ctx.pose).toBe(accepted);expect(ctx.error).toContain('Read-only');
  });
  it('ignores map replies for a replaced reference',async()=>{
    const reply=deferred<unknown>();
    const ctx={busy:false,imageId:'first',kind:'photo',provider:'image',mapQuality:'detailed',job:vi.fn(()=>reply.promise),inspection:null,selected:'original',
      get context(){return [this.imageId,this.kind,this.provider,this.mapQuality].join('/');}};
    const work=componentHandler('src/lib/ReferenceMaps.svelte','inspect',ctx)('normals');ctx.imageId='replacement';reply.resolve({url:'old',available:['normals']});await work;
    expect(ctx.inspection).toBeNull();expect(ctx.selected).toBe('original');
  });
});
