import { describe,it,expect } from 'vitest';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
const template=readFileSync('worker/expression_figure.dsa','utf8');
function fixture(){
  const state={accepted:0,cancelled:0,writes:0,cancelRequested:false,ack:null as any,selection:null as any};
  const props:any[]=[];
  function prop(id:string,value=0,extra:any={}){
    const p={id,value,default:0,min:0,max:1,locked:false,controllers:[] as any[],path:'Pose Controls/Head/Expressions',
      getName(){return this.id;},getLabel(){return this.id;},getPath(){return this.path;},getMin(){return this.min;},getMax(){return this.max;},getDefaultValue(){return this.default;},getRawValue(){return this.value;},getValue(){return this.value;},isLocked(){return this.locked;},getControllerList(){return this.controllers;},getSlaveControllerList(){return props.flatMap(output=>output.controllers.filter((link:any)=>link.getProperty()===this).map((link:any)=>({active:link.active,getOwner:()=>output})));},inherits(){return false;},getOwner(){return {getName:()=>id,inherits:()=>false};},setValue(v:number){this.value=v;state.writes++;},...extra};props.push(p);return p;
  }
  const jaw=prop('facs_bs_JawOpen'),blink=prop('facs_bs_EyeBlinkLeft'),gaze=prop('facs_bs_EyeLookUpLeft',.3),body=prop('xRotate',.35,{path:'Transforms'});
  const head={getName:()=> 'head',getPropertyList:()=>[],getXRotControl:()=>body,getNodeParent:()=>null};
  const eyeRotation=prop('YRotate',.23,{path:'Transforms'}),eye={getName:()=> 'l_eye',inherits:(kind:string)=>kind==='DzNode',getPropertyList:()=>[eyeRotation],getNodeParent:()=>head,getYRotControl:()=>eyeRotation};eyeRotation.getOwner=()=>eye;
  const dataItems=new Map<string,any>();
  const figure={assetUri:'/Genesis9/Base/Genesis9.dsf',assetSource:'',inherits:(kind:string)=>kind==='DzSkeleton',getName:()=> 'Genesis9',getLabel:()=> 'Test Genesis 9',findNodeChild:(name:string)=>name==='head'?head:name==='l_eye'?eye:name==='l_thigh'?{}:null,getObject:()=>null,getPropertyList:()=>[jaw,blink,gaze],getNodeChildren:()=>[head,eye],findDataItem:(name:string)=>dataItems.get(name)??null,addDataItem(item:any){dataItems.set(item.name,item);return 0;},deleteDataItem(item:any){dataItems.delete(item.name);return 0;}};state.selection=figure;
  const drivers=[jaw,blink,gaze].map(p=>({id:p.id,owner:'figure',property:p.id,min:p.min,max:p.max,default:p.default,locked:false,dependencies:[]}));
  drivers.push({id:'l_eye.YRotate',owner:'node:l_eye',property:'YRotate',min:0,max:1,default:0,locked:false,dependencies:[]});
  const job:any={version:1,jobId:'test-face',ack:'ack',cancel:'cancel',rigId:'g9',label:'Genesis 9',connect:false,profile:{drivers,mappings:drivers.map(d=>({driver:d.id,region:d.id.includes('EyeLook')||d.id.includes('YRotate')?'gaze':d.id.includes('Blink')?'eyes':'mouth'}))},expression:{source:{unknown:[]},options:{regions:{brows:true,eyes:true,mouth:true,cheeks:true,gaze:false}},channels:{facs_bs_JawOpen:.6,facs_bs_EyeBlinkLeft:.9}}};
  let snapshot:number[]=[];
  class ElementData{values:Record<string,string>={};constructor(public name:string,public persistent:boolean){}getSettings(){return {getStringValue:(key:string,fallback:string)=>this.values[key]??fallback,setStringValue:(key:string,value:string)=>this.values[key]=value};}}
  const context={Scene:{getPrimarySelection:()=>state.selection},DzSimpleElementData:ElementData,DzFileInfo:class{exists(){return state.cancelRequested;}},DzFile:class{static WriteOnly=1;open(){return true;}write(s:string){state.ack=JSON.parse(s);}close(){}},beginUndo(){snapshot=props.map(p=>p.value);},acceptUndo(){state.accepted++;},cancelUndo(){state.cancelled++;props.forEach((p,i)=>p.value=snapshot[i]);},Error,Math,JSON};
  function record(ids:string[]){const item=new ElementData('PoseSnapExpressionControlsV1',true);item.values.record=JSON.stringify({version:1,rigId:job.rigId,drivers:ids.map(id=>{const d=drivers.find(d=>d.id===id)!;return {id,owner:d.owner,property:d.property,default:d.default,regions:job.profile.mappings.filter((m:any)=>m.driver===id).map((m:any)=>m.region)};})});dataItems.set(item.name,item);}
  return {state,job,figure,props,prop,jaw,blink,gaze,body,eyeRotation,record,dataItems,run(){vm.runInNewContext(template.replace('__POSESNAP_CONFIG__',JSON.stringify(job)),context);return state.ack;}};
}
describe('DAZ facial handoff behavior',()=>{
  it('preserves root and bone scales on expression apply and scoped zero',()=>{
    const f=fixture(),rootScale=f.prop('Scale',1,{path:'Transforms',getValue:()=>.915}),boneScale=f.prop('YScale',1.07,{path:'Transforms'});
    Object.assign(f.figure,{getScaleControl:()=>rootScale});
    const head=f.figure.findNodeChild('head');Object.assign(head!,{getYScaleControl:()=>boneScale});
    const originalProperties=f.figure.getPropertyList;f.figure.getPropertyList=()=>[...originalProperties(),rootScale,boneScale];
    expect(f.run().success).toBe(true);f.job.zero=true;expect(f.run().success).toBe(true);
    expect(rootScale.getRawValue()).toBe(1);expect(rootScale.getValue()).toBe(.915);expect(boneScale.getRawValue()).toBe(1.07);
    expect(f.state.writes).toBe(4);
  });
  it('connects without mutation or an undo entry',()=>{const f=fixture();f.job.connect=true;const ack=f.run();expect(ack.success).toBe(true);expect(ack.profile.drivers.length).toBe(4);expect(ack.profile.anatomy).toEqual({tongue:false,eyes:false});expect(f.state.writes).toBe(0);expect(f.state.accepted).toBe(0);});
  it('applies and acknowledges one undo step while preserving gaze/head',()=>{const f=fixture();const ack=f.run();expect(ack.success).toBe(true);expect(ack.maximumError).toBe(0);expect(f.state.accepted).toBe(1);expect(f.jaw.value).toBe(.6);expect(f.blink.value).toBe(.9);expect(f.gaze.value).toBe(.3);expect(f.body.value).toBe(.35);});
  it('rejects locked or changed metadata before any write',()=>{for(const change of [(f:ReturnType<typeof fixture>)=>f.jaw.locked=true,(f:ReturnType<typeof fixture>)=>f.jaw.max=.8]){const f=fixture();change(f);expect(f.run().success).toBe(false);expect(f.state.writes).toBe(0);}});
  it('allows a neutral combined controller but rejects an active one',()=>{for(const value of [0,.7]){const f=fixture();const input=f.prop('customCombined',value);f.jaw.controllers=[{active:true,getProperty:()=>input}];f.job.profile.drivers[0].dependencies=['customCombined'];expect(f.run().success).toBe(value===0);expect(f.state.writes).toBe(value===0?2:0);}});
  it('replaces a previous expression through a derived mapped input and verifies raw keys',()=>{const f=fixture();f.blink.value=.2;const derived=f.prop('eCTRLEyelidSquint',0,{getValue:()=>f.blink.value*.2});derived.controllers=[{active:true,getProperty:()=>f.blink}];f.jaw.controllers=[{active:true,getProperty:()=>derived}];f.jaw.getValue=()=>f.jaw.value+derived.getValue();f.job.profile.drivers[0].dependencies=['eCTRLEyelidSquint'];const ack=f.run();expect(ack.success).toBe(true);expect(ack.maximumError).toBe(0);expect(ack.channels.facs_bs_JawOpen.raw).toBe(.6);expect(ack.channels.facs_bs_JawOpen.value).toBeCloseTo(.78);});
  it('rejects an independently keyed or cyclic derived controller before mutation',()=>{for(const cycle of [false,true]){const f=fixture();const input=f.prop('customCombined',cycle?0:.2,{getValue:()=>cycle?.2:0});if(cycle)input.controllers=[{active:true,getProperty:()=>input}];f.jaw.controllers=[{active:true,getProperty:()=>input}];f.job.profile.drivers[0].dependencies=['customCombined'];expect(f.run().success).toBe(false);expect(f.state.writes).toBe(0);}});
  it('rolls back effective clamping and preserves the previous result',()=>{const f=fixture();f.jaw.getValue=()=>Math.min(.4,f.jaw.value);expect(f.run().success).toBe(false);expect(f.state.accepted).toBe(0);expect(f.state.cancelled).toBe(1);expect(f.jaw.value).toBe(0);expect(f.blink.value).toBe(0);});
  it('rolls back unintended head movement',()=>{const f=fixture();f.jaw.setValue=(value:number)=>{f.jaw.value=value;f.body.value=1;};expect(f.run().success).toBe(false);expect(f.body.value).toBe(.35);expect(f.jaw.value).toBe(0);expect(f.state.cancelled).toBe(1);});
  it('protects existing eyeball direction unless gaze was explicitly enabled',()=>{for(const enabled of [false,true]){const f=fixture();f.job.expression.options.regions.gaze=enabled;if(enabled)f.job.expression.channels['l_eye.YRotate']=.8;f.jaw.setValue=(value:number)=>{f.jaw.value=value;f.eyeRotation.value=.8;};expect(f.run().success).toBe(enabled);expect(f.eyeRotation.value).toBe(enabled?.8:.23);}});
  it('rejects a different generation and Genesis 8.1',()=>{const f=fixture();f.job.rigId='g8f';expect(f.run().success).toBe(false);const g=fixture();g.figure.assetUri='/Genesis8_1/Female';expect(g.run().success).toBe(false);expect(g.state.writes).toBe(0);});
  it('preserves an unknown active expression without clearing it',()=>{const f=fixture();const unknown=f.prop('eCTRLUnknownSmile',.8);f.figure.getPropertyList=()=>[f.jaw,f.blink,f.gaze,unknown];expect(f.run().success).toBe(true);expect(unknown.value).toBe(.8);expect(f.state.writes).toBe(2);});
  it('zeros only successfully applied dials, preserving unrelated gaze and identity',()=>{
    const f=fixture(),identity=f.prop('FBMIdentity',.7,{path:'Actor/Shape'});f.figure.getPropertyList=()=>[f.jaw,f.blink,f.gaze,identity];
    expect(f.run().success).toBe(true);f.job.zero=true;delete f.job.profile;delete f.job.expression;
    expect(f.run()).toMatchObject({success:true,zeroed:2});expect(f.jaw.value).toBe(0);expect(f.blink.value).toBe(0);
    expect(f.gaze.value).toBe(.3);expect(f.eyeRotation.value).toBe(.23);expect(identity.value).toBe(.7);expect(f.body.value).toBe(.35);
  });
  it('makes no writes and no undo entry when no ownership record exists',()=>{
    const f=fixture();f.jaw.value=.8;f.job.zero=true;
    expect(f.run()).toMatchObject({success:true,zeroed:0,tracked:0});expect(f.jaw.value).toBe(.8);expect(f.gaze.value).toBe(.3);expect(f.state.writes).toBe(0);expect(f.state.accepted).toBe(0);
  });
  it('does not create another undo step when recorded controls are already neutral',()=>{
    const f=fixture();expect(f.run().success).toBe(true);f.job.zero=true;expect(f.run().zeroed).toBe(2);const undo=f.state.accepted,writes=f.state.writes;
    expect(f.run()).toMatchObject({success:true,zeroed:0,tracked:2});expect(f.state.accepted).toBe(undo);expect(f.state.writes).toBe(writes);
  });
  it('clears previously applied optional tongue detail when replacing an observed mouth',()=>{
    const f=fixture(),tongue=f.prop('facs_bs_TongueOut');f.figure.getPropertyList=()=>[f.jaw,f.blink,f.gaze,tongue];
    f.job.profile.drivers.push({id:tongue.id,owner:'figure',property:tongue.id,min:0,max:1,default:0,dependencies:[]});f.job.profile.mappings.push({driver:tongue.id,region:'mouth'});
    f.job.expression.channels[tongue.id]=1;expect(f.run().success).toBe(true);expect(tongue.value).toBe(1);
    delete f.job.expression.channels[tongue.id];f.job.expression.channels.facs_bs_JawOpen=.2;
    expect(f.run()).toMatchObject({success:true,reset:[tongue.id]});expect(tongue.value).toBe(0);expect(f.jaw.value).toBe(.2);
  });
  it('preserves an untracked legacy tongue dial and explains how to establish ownership',()=>{
    const f=fixture(),tongue=f.prop('facs_bs_TongueOut',1);f.figure.getPropertyList=()=>[f.jaw,f.blink,f.gaze,tongue];
    const ack=f.run();expect(ack.success).toBe(true);expect(tongue.value).toBe(1);expect(ack.warnings.join(' ')).toContain('Reapply the earlier tongue expression once');
    f.job.zero=true;expect(f.run().success).toBe(true);expect(tongue.value).toBe(1);
  });
  it('preserves optional tongue values when the mouth region is disabled or uncertain',()=>{
    for(const unknown of [false,true]){const f=fixture();expect(f.run().success).toBe(true);delete f.job.expression.channels.facs_bs_JawOpen;
      if(unknown)f.job.expression.source.unknown=['mouth'];else f.job.expression.options.regions.mouth=false;
      expect(f.run().success).toBe(true);expect(f.jaw.value).toBe(.6);
    }
  });
  it('keeps unowned active expression dials unchanged during apply and reset',()=>{
    const f=fixture(),combined=f.prop('VendorSmile',.7),powerPose=f.prop('powerpose_ctrl_LipsClose',.2,{path:'Hidden/PowerPose'});
    f.figure.getPropertyList=()=>[f.jaw,f.blink,f.gaze,combined,powerPose];expect(f.run().success).toBe(true);f.job.zero=true;
    expect(f.run().success).toBe(true);expect(combined.value).toBe(.7);expect(powerPose.value).toBe(.2);
  });
  it('zeros its raw dial even if an unowned external controller remains active',()=>{
    const f=fixture(),external=f.prop('UnknownExternal',.7,{path:'Actor/Shape'});expect(f.run().success).toBe(true);
    f.jaw.controllers=[{active:true,getProperty:()=>external}];f.jaw.getValue=()=>f.jaw.value+external.value;f.job.zero=true;
    expect(f.run().success).toBe(true);expect(f.jaw.value).toBe(0);expect(f.jaw.getValue()).toBe(.7);expect(external.value).toBe(.7);
  });
  it('does not evaluate external ERC outputs merely to zero its stored dial',()=>{
    const f=fixture();expect(f.run().success).toBe(true);f.job.zero=true;
    f.jaw.getValue=()=>{throw Error('Native controller evaluation must not run during scoped zero');};
    expect(f.run()).toMatchObject({success:true,zeroed:2});expect(f.jaw.value).toBe(0);
  });
  it('allows native expression outputs to follow while preserving morph raw values',()=>{
    const f=fixture(),shape=f.prop('FBMIdentity',.7,{path:'Actor/Shape',getValue:()=>shape.value+f.jaw.value*.5});shape.controllers=[{active:true,getProperty:()=>f.jaw}];
    f.figure.getPropertyList=()=>[f.jaw,f.blink,f.gaze,shape];expect(f.run().success).toBe(true);f.job.zero=true;
    expect(f.run().success).toBe(true);expect(shape.value).toBe(.7);expect(shape.getValue()).toBe(.7);
  });
  it('resolves a recorded head-panel alias without claiming a separate shape control',()=>{
    const f=fixture(),modifier={getName:()=> 'facs_bs_JawOpen',inherits:(kind:string)=>kind==='DzModifier'},underlying=f.prop('Value',0,{path:'Hidden',getOwner:()=>modifier});
    f.jaw.getAliasTarget=()=>underlying;f.jaw.setValue=(v:number)=>{f.jaw.value=v;underlying.value=v;f.state.writes++;};expect(f.run().success).toBe(true);f.job.zero=true;
    expect(f.run().success).toBe(true);expect(underlying.value).toBe(0);
  });
  it('rolls back changed body or unowned raw identity dials',()=>{
    for(const identityCase of [false,true]){const f=fixture(),identity=f.prop('FBMIdentity',.7,{path:'Actor/Shape'});f.figure.getPropertyList=()=>[f.jaw,f.blink,f.gaze,identity];expect(f.run().success).toBe(true);
      f.job.zero=true;f.jaw.setValue=(v:number)=>{f.jaw.value=v;(identityCase?identity:f.body).value=.1;};const undo=f.state.accepted;
      expect(f.run().success).toBe(false);expect(f.state.accepted).toBe(undo);expect(f.state.cancelled).toBe(1);expect(f.jaw.value).toBe(.6);expect(f.body.value).toBe(.35);expect(identity.value).toBe(.7);
    }
  });
  it('rejects a changed or locked recorded property before writing',()=>{
    for(const locked of [false,true]){const f=fixture();expect(f.run().success).toBe(true);f.job.zero=true;const writes=f.state.writes;
      if(locked)f.jaw.locked=true;else f.jaw.default=.1;
      expect(f.run().success).toBe(false);expect(f.state.writes).toBe(writes);expect(f.jaw.value).toBe(.6);
    }
  });
  it('does not record a failed or cancelled apply',()=>{
    for(const cancelled of [false,true]){const f=fixture();f.jaw.setValue=(v:number)=>{f.jaw.value=v;if(cancelled)f.state.cancelRequested=true;else f.body.value=1;};
      expect(f.run().success).toBe(false);expect(f.dataItems.size).toBe(0);expect(f.jaw.value).toBe(0);expect(f.state.accepted).toBe(0);
    }
  });
  it('cancels a reset after writing and retains ownership of the restored expression',()=>{
    const f=fixture();expect(f.run().success).toBe(true);f.job.zero=true;f.blink.setValue=(v:number)=>{f.blink.value=v;f.state.cancelRequested=true;};const record=f.dataItems.get('PoseSnapExpressionControlsV1').values.record;
    expect(f.run().success).toBe(false);expect(f.jaw.value).toBe(.6);expect(f.blink.value).toBe(.9);expect(f.dataItems.get('PoseSnapExpressionControlsV1').values.record).toBe(record);
  });
  it('does not evaluate or traverse thousands of unrelated morphs during reset',()=>{
    const f=fixture();expect(f.run().success).toBe(true);const unused=Array.from({length:3000},(_,i)=>f.prop('FBMUnused'+i,0,{path:'Actor/Shape',getValue:()=>{throw Error('Unrelated morph evaluation');},getControllerList:()=>{throw Error('Unrelated controller traversal');}}));
    f.figure.getObject=()=>({getNumModifiers:()=>unused.length,getModifier:(i:number)=>({getName:()=>unused[i].id,getPropertyList:()=>[unused[i]]})}) as any;f.job.zero=true;
    expect(f.run()).toMatchObject({success:true,zeroed:2});expect(f.body.value).toBe(.35);
  });
  it('does not use another figure’s ownership record',()=>{
    const first=fixture(),second=fixture();expect(first.run().success).toBe(true);second.jaw.value=.8;second.job.zero=true;
    expect(second.run()).toMatchObject({success:true,tracked:0,zeroed:0});expect(second.jaw.value).toBe(.8);
  });
  it('rejects corrupt tracking metadata before any mutation',()=>{
    const f=fixture();expect(f.run().success).toBe(true);f.dataItems.get('PoseSnapExpressionControlsV1').values.record='{"version":1,"rigId":"g8f","drivers":[]}';f.job.zero=true;const writes=f.state.writes;
    expect(f.run().success).toBe(false);expect(f.state.writes).toBe(writes);expect(f.jaw.value).toBe(.6);
  });
});
