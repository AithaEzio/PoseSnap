import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {parse} from 'svelte/compiler';
import {describe,it,expect,vi} from 'vitest';
import {componentHandler} from './component-handlers';

const source=readFileSync('worker/connect_figure.dsa','utf8');
const parts=readFileSync('worker/rigs.py','utf8').match(/^FACIAL_PARTS = \((.+)\)$/m)![1];
const excludedParts=JSON.parse('['+parts.replaceAll("'",'"')+']');
function fixture(rigId:'g8f'|'g8m'|'g9'){
  const state={ack:null as any,writes:0,controllerReads:[] as string[],cancelled:false};
  const keyed={type:6,active:true,addend:0,scalar:1,inherits:(t:string)=>t==='DzERCLink',
    getProperty:()=>({getName:()=> 'JB2_Animation',getDefaultValue:()=>0}),getKeyOpValue:()=>5};
  const figureName={g8f:'Genesis8Female',g8m:'Genesis8Male',g9:'Genesis9'}[rigId];
  const names=rigId==='g9'?['hip','l_hand','r_hand','l_upperarm','r_upperarm','l_thigh','l_pectoral','l_eye','tongue01']:['hip','lHand','rHand','lShldrBend','rShldrBend','lThighBend','lPectoral','lEye','tongue01'];
  const properties=new Map<string,any>(),nodes:any[]=[];
  function node(id:string,isFigure=false){
    const n:any={getName:()=>id,getNodeParent:()=>isFigure?null:figure,getSkeleton:()=>figure,
      inherits:(t:string)=>t===(isFigure?'DzSkeleton':'DzBone'),
      getOrigin:()=>({x:0,y:100,z:0}),getEndPoint:()=>({x:0,y:110,z:0}),
      getRotationOrder:()=>({firstAxis:0,secondAxis:1,thirdAxis:2})};
    for(const axis of ['X','Y','Z']){
      const key=id+'/'+axis,p={value:0,controllers:[] as any[],getMin:()=>-180,getMax:()=>180,isClamped:()=>true,isLocked:()=>false,
        getDefaultValue:()=>0,getControllerList(){state.controllerReads.push(key);return this.controllers;},setValue(){state.writes++;}};
      properties.set(key,p);n['get'+axis+'RotControl']=()=>p;n['getOrient'+axis+'Control']=()=>p;
    }
    return n;
  }
  const figure=node(figureName,true);nodes.push(...names.map(n=>node(n)));
  Object.assign(figure,{assetUri:'/'+figureName+'/',assetSource:'',getLabel:()=> 'Custom morphed character',
    getNodeChildren:()=>nodes,findNodeChild:(id:string)=>nodes.find(n=>n.getName()===id)});
  for(const name of names.filter(n=>/pectoral|eye|tongue/i.test(n)))properties.get(name+'/X').controllers=[keyed];
  const context={Scene:{getPrimarySelection:()=>figure},DzERCLink:{ERCDeltaAdd:0,ERCDivideInto:1,ERCDivideBy:2,ERCMultiply:3,ERCSubtract:4,ERCAdd:5,ERCKeyed:6},
    DzFileInfo:class{exists(){return state.cancelled;}},DzFile:class{static WriteOnly=1;open(){return true;}write(s:string){state.ack=JSON.parse(s);}close(){}}};
  return {state,properties,keyed,run(){vm.runInNewContext(source.replace('__POSESNAP_CONFIG__',JSON.stringify({rigId,label:rigId,excludedParts,jobId:'body-connect',ack:'ack',cancel:'cancel'})),context);return state.ack;}};
}

describe('optional body rig connection on customized Genesis figures',()=>{
  for(const rig of ['g8f','g8m','g9'] as const){
    it(`reads ${rig} without inspecting JB2_Animation pectoral or facial controllers`,()=>{
      const f=fixture(rig),ack=f.run();expect(ack.success).toBe(true);expect(f.state.writes).toBe(0);
      expect(f.state.controllerReads.some(n=>/pectoral|eye|tongue/i.test(n))).toBe(false);
      expect(ack.profile.nodes.some((n:any)=>/pectoral/i.test(n.id))).toBe(true);
    });
    it(`still reads required ${rig} bone relationships`,()=>{
      const f=fixture(rig),hand=rig==='g9'?'l_hand':'lHand';
      f.properties.get(hand+'/X').controllers=[{...f.keyed,type:0,scalar:.5,addend:0,getProperty:()=>f.properties.get('hip/X')}];
      const ack=f.run();expect(ack.success).toBe(true);expect(ack.profile.formulas).toHaveLength(1);
      expect(ack.profile.nodes.find((n:any)=>n.id===hand).driven).toEqual(['x']);expect(f.state.writes).toBe(0);
    });
  }
  it('rejects an unsupported controller on an actual body channel without modifying the figure',()=>{
    const f=fixture('g8f');f.properties.get('hip/X').controllers=[f.keyed];
    expect(f.run()).toMatchObject({success:false});expect(f.state.ack.message).toContain('optional rig connection was not changed');
    expect(f.state.ack.message).not.toContain('standard Genesis base figure');expect(f.state.writes).toBe(0);
  });
  it('cancellation performs no controller traversal or scene writes',()=>{
    const f=fixture('g9');f.state.cancelled=true;expect(f.run().success).toBe(false);
    expect(f.state.controllerReads).toHaveLength(0);expect(f.state.writes).toBe(0);
  });
});

const app=readFileSync('src/App.svelte','utf8'),ast=parse(app) as any;
function derived(name:string,ctx:Record<string,unknown>){
  const decl=ast.instance.content.body.flatMap((n:any)=>n.declarations??[]).find((d:any)=>d.id.name===name);
  const value=decl.init.arguments[0];return new Function('ctx',`with(ctx){return (${app.slice(value.start,value.end)});}`)(ctx);
}
describe('body workflows without a selected DAZ connection',()=>{
  for(const rig of ['g8f','g8m','g9'])it(`allows ${rig} extraction and a neutral studio pose using its built-in rig`,async()=>{
    const ctx:any={api:{desktop:true,request:vi.fn().mockResolvedValue([])},status:{rigs:['g8f','g8m','g9'],connectedRigs:[],ready:true},rig,
      mode:'editor',busy:false,pendingRefinement:null,people:[],interactionChoices:{},photo:{id:'reference'},selected:1,engine:{ready:true},editPoses:[],finalPose:null,
      job:vi.fn().mockResolvedValue({rigId:rig}),adoptScene:vi.fn(),rigLabels:{g8f:'Genesis 8 Female',g8m:'Genesis 8 Male',g9:'Genesis 9'},notice:'',error:'',history:[]};
    ctx.connected=derived('connected',ctx);expect(ctx.connected).toBe(true);
    expect(derived('extractDisabled',ctx)).toBe(false);expect(derived('bodyConnections',ctx)).toEqual([]);
    await componentHandler('src/App.svelte','newPose',ctx)();
    expect(ctx.job).toHaveBeenCalledExactlyOnceWith('retarget',{editorOperation:'new_pose',rigId:rig});
    expect(ctx.adoptScene).toHaveBeenCalledWith([{rigId:rig}],true);expect(ctx.error).toBe('');
  });
});
