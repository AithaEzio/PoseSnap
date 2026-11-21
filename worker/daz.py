"""DUF pose serialization and acknowledged, undoable DAZ handoff."""
import json, math, subprocess, time, uuid
from pathlib import Path
from storage import atomic_json
from rigs import evaluated_channels, pose_channels, RIG_LABELS

def connection_script(rig_id, ack_path, job_id, cancel_path):
    from rigs import RIG_LABELS, FACIAL_PARTS
    if rig_id not in RIG_LABELS:raise ValueError('Unsupported Genesis generation')
    config=dict(rigId=rig_id,label=RIG_LABELS[rig_id],excludedParts=list(FACIAL_PARTS),ack=str(ack_path).replace('\\','/'),jobId=job_id,cancel=str(cancel_path).replace('\\','/'))
    source=Path(__file__).with_name('connect_figure.dsa').read_text(encoding='utf-8')
    return source.replace('__POSESNAP_CONFIG__',json.dumps(config,ensure_ascii=True,allow_nan=False))

def connect_figure(root,payload,progress):
    from rigs import cache_profile, RIG_LABELS
    rig_id=payload['rigId']
    if rig_id not in RIG_LABELS:raise ValueError('Unsupported Genesis generation')
    executable=Path(payload['executable'])
    if not executable.is_file() or executable.name.lower()!='dazstudio.exe':raise ValueError('Choose DAZ Studio 6’s DAZStudio.exe in Settings')
    job_id=uuid.uuid4().hex;folder=root/'temp/daz'/job_id;folder.mkdir(parents=True)
    active_job=payload.get('_jobId',job_id)
    if not isinstance(active_job,str) or not active_job.replace('-','').isalnum() or len(active_job)>79:raise ValueError('Invalid connection job')
    cancel=root/'temp/jobs'/(active_job+'.cancel');cancel.parent.mkdir(parents=True,exist_ok=True)
    ack=folder/'ack.json';script=folder/'connect.dsa'
    script.write_text(connection_script(rig_id,ack,job_id,cancel),encoding='utf-8')
    progress('Reading selected figure metadata in DAZ Studio',25)
    subprocess.Popen([str(executable),str(script)],cwd=executable.parent)
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        if cancel.exists():raise ValueError('Rig connection cancelled')
        if ack.is_file():
            try:result=json.loads(ack.read_text(encoding='utf-8-sig'))
            except (OSError,ValueError):time.sleep(.1);continue
            if result.get('version')!=1 or result.get('jobId')!=job_id:raise ValueError('DAZ acknowledgment does not match this connection')
            if not result.get('success'):raise ValueError(result.get('message','Could not read the selected figure'))
            progress('Validating and caching local rig metadata',80)
            cache_profile(root,result['profile'],rig_id)
            progress('Figure connected',100)
            return dict(rigId=rig_id,figure=result['figure'])
        time.sleep(.25)
    cancel.write_text('expired',encoding='ascii')
    raise ValueError('DAZ did not acknowledge the connection. Close blocking dialogs, select '+RIG_LABELS[rig_id]+' and retry.')

def validate_pose(pose):
    if pose.get('version')!=1 or pose.get('rigId') not in ('g8f','g8m','g9'):
        raise ValueError('Invalid target pose')
    allowed={n['id'] for n in pose['rig']['nodes'] if n['type']=='bone'}
    if not pose['rotations'] or any(bone not in allowed for bone in pose['rotations']):raise ValueError('Pose contains an unsupported bone')
    for values in list(pose['rotations'].values())+[pose['translation'],pose.get('rootRotation',[0,0,0])]:
        if len(values)!=3 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in values):raise ValueError('Pose contains invalid channel values')
    pins=pose.get('pins',{})
    if not isinstance(pins,dict) or any(bone not in allowed for bone in pins):raise ValueError('Pose contains an unsupported joint pin')
    for pin in pins.values():
        if not isinstance(pin,dict) or not pin or set(pin)-{'position','rotation'}:raise ValueError('Invalid joint pin')
        for component,values in pin.items():
            if not isinstance(values,list) or len(values)!=(3 if component=='position' else 4) or not all(type(v) in (int,float) and math.isfinite(v) for v in values):raise ValueError('Invalid joint pin target')
            if component=='rotation' and abs(sum(v*v for v in values)-1)>1e-5:raise ValueError('Joint pin orientation must be normalized')

def validate_placement(pose,placement):
    if placement not in ('keep','floor','origin','reference'):raise ValueError('Unknown placement policy')
    if placement=='reference':
        layout=pose.get('layout',{})
        if layout.get('version') not in (1,2,3) or not layout.get('reference') or not layout.get('id') or pose.get('personId') not in layout.get('personIds',[]):
            raise ValueError('Build an interaction before exporting a reference layout.')
    if placement=='origin' and pose.get('footSupport') and all(s['state']=='air' for s in pose['footSupport']):
        raise ValueError('Reset to origin would remove this airborne placement. Choose Match preview floor or Reference layout to retain its height.')

def duf(pose,placement):
    validate_pose(pose)
    validate_placement(pose,placement)
    animations=[]
    nodes={n['id']:n for n in pose['rig']['nodes']}
    for bone,values in pose_channels(pose['rig'],pose['rotations']).items():
        for axis,value in zip('xyz',values):
            if nodes[bone].get('limits',{}).get(axis,{}).get('locked') or axis in nodes[bone].get('driven',[]):continue
            animations.append(dict(url=f'name://@selection/{bone}:?rotation/{axis}/value',keys=[[0,value]]))
    for axis,value in zip('xyz',pose.get('rootRotation',[0,0,0])):
        animations.append(dict(url=f'name://@selection:?rotation/{axis}/value',keys=[[0,value]]))
    # Keep position omits root translation; loading a pose cannot move the figure accidentally.
    if placement!='keep':
        values=pose['translation'] if placement in ('floor','reference') else [0.,0.,0.]
        for axis,value in zip('xyz',values):
            animations.append(dict(url=f'name://@selection:?translation/{axis}/value',keys=[[0,value]]))
    return dict(file_version='0.6.0.0',asset_info=dict(id='/PoseSnap/Pose.duf',type='preset_pose',contributor=dict(author='PoseSnap',website=''),revision='1.0'),
        scene=dict(animations=animations))

def export(root,payload):
    destination=Path(payload['path'])
    if destination.suffix.lower()!='.duf':destination=destination.with_suffix('.duf')
    atomic_json(destination,duf(payload['pose'],payload.get('placement','keep')))
    return dict(path=str(destination))

def application_script(pose,placement,ack_path,job_id,cancel_path=None):
    validate_pose(pose)
    validate_placement(pose,placement)
    pose=dict(pose,rotations=pose_channels(pose['rig'],pose['rotations']))
    config=dict(pose=pose,rigLabel=RIG_LABELS[pose['rigId']],placement=placement,ack=str(ack_path).replace('\\','/'),jobId=job_id,evaluated=evaluated_channels(pose['rig'],pose['rotations']),cancel=str(cancel_path).replace('\\','/') if cancel_path else '')
    return '''// PoseSnap: local handoff, validated before modification, one undo operation.
(function () {
  var job = CONFIG;
  function acknowledge(value) {
    value.jobId = job.jobId;
    var file = new DzFile(job.ack);
    if (!file.open(DzFile.WriteOnly)) { throw new Error("Could not write PoseSnap acknowledgment"); }
    file.write(JSON.stringify(value)); file.close();
  }
  var undoStarted = false;
  function checkCancelled(){if(job.cancel && new DzFileInfo(job.cancel).exists()){throw new Error("PoseSnap application cancelled");}}
  function snapshotScale(figure) {
    var saved=[],nodes=[figure].concat(figure.getNodeChildren(true)),nonDefault=false;
    var getters=["getScaleControl","getXScaleControl","getYScaleControl","getZScaleControl"];
    for(var n=0;n<nodes.length;n++){
      for(var g=0;g<getters.length;g++){
        var property=nodes[n][getters[g]]();if(!property)continue;
        var raw=Number(property.getRawValue()),value=Number(property.getValue());
        if(!isFinite(raw)||!isFinite(value))throw new Error("A scale control is invalid; PoseSnap has not changed the figure.");
        saved.push({property:property,raw:raw,root:n===0,value:value});
        if(Math.abs(value-property.getDefaultValue())>.00001)nonDefault=true;
      }
    }
    return {controls:saved,nonDefault:nonDefault};
  }
  function verifyScale(saved) {
    // Read-only protection. Bone ERC outputs may follow posing naturally;
    // their raw scale dials and the figure's effective scale stay untouched.
    for(var i=0;i<saved.controls.length;i++){
      var item=saved.controls[i],raw=Number(item.property.getRawValue());
      var value=item.root?Number(item.property.getValue()):item.value;
      if(!isFinite(raw)||!isFinite(value)||Math.abs(raw-item.raw)>.000001||item.root&&Math.abs(value-item.value)>.000001){
        throw new Error("DAZ changed a scale control during posing. The pose was rolled back.");
      }
    }
  }
  try {
    checkCancelled();
    var figure = Scene.getPrimarySelection();
    if (!figure) { throw new Error("Select a Genesis figure in DAZ Studio first"); }
    if (figure.inherits("DzBone")) { figure = figure.getSkeleton(); }
    if (!figure || !figure.inherits("DzSkeleton")) { throw new Error("The selection is not a supported figure"); }
    if (job.placement === "reference") {
      if (figure.getNodeParent()) { throw new Error("Reference layout needs an unparented figure so every participant shares the same scene frame. Unparent it while keeping its transforms, then retry."); }
    }
    var g9 = figure.findNodeChild("l_thigh", true);
    var g8 = figure.findNodeChild("lThighBend", true);
    if ((job.pose.rigId === "g9" && !g9) || (job.pose.rigId !== "g9" && !g8)) {
      throw new Error("Select " + job.rigLabel + " in DAZ Studio to apply this pose.");
    }
    if(job.pose.rigId !== "g9"){
      var uri=(String(figure.assetUri)+" "+String(figure.assetSource)).toLowerCase();
      var female=uri.indexOf("genesis8female")>=0 || uri.indexOf("/female/")>=0;
      var male=uri.indexOf("genesis8male")>=0 || uri.indexOf("/male/")>=0;
      if((job.pose.rigId === "g8f" && !female) || (job.pose.rigId === "g8m" && !male)){throw new Error("Select "+job.rigLabel+" in DAZ Studio to apply this pose.");}
    }
    var axes = ["X","Y","Z"], pending = [], verification = [], metadata = {};
    for(var n=0;n<job.pose.rig.nodes.length;n++){metadata[job.pose.rig.nodes[n].id]=job.pose.rig.nodes[n];}
    for (var boneName in job.pose.rotations) {
      if (!job.pose.rotations.hasOwnProperty(boneName)) { continue; }
      var bone = figure.findNodeChild(boneName, true);
      if (!bone) { throw new Error("Missing target bone: " + boneName); }
      for (var i=0;i<3;i++) {
        var property = bone["get"+axes[i]+"RotControl"]();
        if (!property) { throw new Error("Missing rotation: " + boneName); }
        verification.push([property,job.evaluated[boneName][i],boneName,axes[i]]);
        if ((metadata[boneName].driven || []).indexOf(axes[i].toLowerCase())>=0) { continue; }
        if (property.isLocked()) {
          if (Math.abs(property.getValue()-job.pose.rotations[boneName][i])>0.1) { throw new Error("A required rotation is locked: " + boneName); }
          continue;
        }
        pending.push([property,job.pose.rotations[boneName][i],boneName,axes[i]]);
      }
    }
    for (var i=0;i<3;i++) {
      var rootRot=figure["get"+axes[i]+"RotControl"]();
      if (rootRot.isLocked()) {if(Math.abs(rootRot.getValue()-(job.pose.rootRotation || [0,0,0])[i])>0.1){throw new Error("The figure orientation is locked");}continue;}
      pending.push([rootRot,(job.pose.rootRotation || [0,0,0])[i],"@selection",axes[i]]);
      verification.push(pending[pending.length-1]);
    }
    if (job.placement !== "keep") {
      var translation=(job.placement === "floor" || job.placement === "reference") ? job.pose.translation : [0,0,0];
      for (var i=0;i<3;i++) {
        var rootPos=figure["get"+axes[i]+"PosControl"]();
        if (rootPos.isLocked()) {if(Math.abs(rootPos.getValue()-translation[i])>0.1){throw new Error("The figure position is locked");}continue;}
        pending.push([rootPos,translation[i],"@translation",axes[i]]);
        verification.push(pending[pending.length-1]);
      }
    }
    var scale=snapshotScale(figure);
    checkCancelled();beginUndo(); undoStarted=true;
    for (var i=0;i<pending.length;i++) { pending[i][0].setValue(pending[i][1]); }
    var actual = {}, maximumError=0, worstChannel="";
    for (var i=0;i<verification.length;i++) {
      var channelError=Math.abs(verification[i][0].getValue()-verification[i][1]);
      if(channelError>maximumError){maximumError=channelError;worstChannel=verification[i][2]+"/"+verification[i][3]+" (requested "+verification[i][1]+", actual "+verification[i][0].getValue()+")";}
      actual[verification[i][2]+"/"+verification[i][3]]=verification[i][0].getValue();
    }
    if (maximumError>0.1) { throw new Error("DAZ adjusted "+worstChannel+". The pose was rolled back."); }
    verifyScale(scale);
    checkCancelled();acceptUndo("PoseSnap pose"); undoStarted=false;
    var warnings=job.placement==="reference"&&scale.nonDefault?["Scale preserved. Different character proportions can shift contacts; adjust positions if needed."]:[];
    acknowledge({success:true,figure:figure.getLabel(),maximumError:maximumError,channels:actual,scalePreserved:true,warnings:warnings});
  } catch(error) {
    if (undoStarted) { cancelUndo(); }
    acknowledge({success:false,message:String(error)});
  }
}());
'''.replace('CONFIG',json.dumps(config,ensure_ascii=True,allow_nan=False))

def apply(root,payload,progress):
    executable=Path(payload['executable'])
    if not executable.is_file() or executable.name.lower()!='dazstudio.exe':raise ValueError('Choose DAZ Studio 6\'s DAZStudio.exe in Settings')
    job_id=uuid.uuid4().hex
    folder=root/'temp/daz'/job_id;folder.mkdir(parents=True)
    cancel_job=payload.get('_jobId',job_id)
    if not isinstance(cancel_job,str) or not cancel_job.replace('-','').isalnum() or len(cancel_job)>79:raise ValueError('Invalid application job')
    cancel=root/'temp/jobs'/(cancel_job+'.cancel');cancel.parent.mkdir(parents=True,exist_ok=True)
    ack=folder/'ack.json';script=folder/'apply.dsa'
    script.write_text(application_script(payload['pose'],payload.get('placement','keep'),ack,job_id,cancel),encoding='utf-8')
    progress('Waiting for DAZ Studio to apply the pose',25)
    subprocess.Popen([str(executable),str(script)],cwd=executable.parent)
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        if ack.is_file():
            try:result=json.loads(ack.read_text(encoding='utf-8-sig'))
            except (OSError,ValueError):time.sleep(.1);continue
            if result.get('jobId')!=job_id:raise ValueError('DAZ acknowledgment does not match this job')
            if not result.get('success'):raise ValueError(result.get('message','DAZ could not apply the pose'))
            progress('Pose applied in DAZ Studio',100)
            return result
        time.sleep(.25)
    cancel.write_text('expired',encoding='ascii')
    raise ValueError('DAZ did not acknowledge the pose within 60 seconds. The pending application was cancelled. Close any DAZ dialogs and retry, or save DUF.')
