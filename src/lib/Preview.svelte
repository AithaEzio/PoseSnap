<script lang="ts">
  import { onMount, untrack } from 'svelte';
  import * as THREE from 'three';
  import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
  import { cameraTransform,referenceFrame,referenceProjection } from './referenceCamera';
  import { PreviewCameraCommands } from './previewCamera';
  import {PreviewFrames} from './previewFrames';
  import { TransformControls } from 'three/addons/controls/TransformControls.js';
  import { neutralRig, forwardKinematics, previewRotations } from './pose';
  import { Mannequin, loadMannequin } from './mannequin';
  import { editable, figureKey, gizmoFrame, boundedGizmoRotation, handleJoints, jointLabel, isReachJoint, type EditTool, type JointGroup, type EditAxis } from './editor';
  import { preservePins } from './pinning';
  import { Pin } from 'lucide-svelte';
  import { moveLimb } from './ik';
  import { tooltip } from './tooltip';
  import { separateHandles, handleGlyph, type HandlePoint } from './handles';
  import type { Pose, Theme } from './types';
  let {active=true,overlay=false,pose=null,companions=[],originalPoses=[],theme='dark',view='front',showGrid=true,reset=0,focus=0,editing=false,selectedBone=figureKey,tool='select',space='local',snap=false,axis='all',handles=true,ghostPartners=true,jointGroup='body',onSelect=()=>{},onEdit=()=>{},onDrag=()=>{},onReady=()=>{},onCameraProfile=()=>{}}: {active?:boolean;overlay?:boolean;pose?:Pose|null;companions?:Pose[];originalPoses?:Pose[];theme?:Theme;view?:string;showGrid?:boolean;reset?:number;focus?:number;editing?:boolean;selectedBone?:string;tool?:EditTool;space?:'local'|'world';snap?:boolean;axis?:EditAxis;handles?:boolean;ghostPartners?:boolean;jointGroup?:JointGroup;onSelect?:(person:number,bone:string)=>void;onEdit?:(pose:Pose)=>void;onDrag?:(active:boolean)=>void;onReady?:(problem?:string)=>void;onCameraProfile?:(profile:string|null)=>void}=$props();
  const referenceCamera=$derived(pose?.referenceCamera);
  let host:HTMLDivElement;let error=$state('');
  let renderer:THREE.WebGLRenderer,scene:THREE.Scene,camera:THREE.PerspectiveCamera,controls:OrbitControls,grid:THREE.GridHelper,floor:THREE.Mesh,gizmo:TransformControls,proxy:THREE.Object3D,marker:THREE.Mesh;
  let initialized=$state(false),dirty=true;
  let frames:PreviewFrames|undefined;
  function invalidate(){dirty=true;frames?.invalidate();}
  function activity(){frames?.setActive(active&&document.visibilityState==='visible'&&host.clientWidth>0&&host.clientHeight>0);}
  const cameraCommands=new PreviewCameraCommands();
  const neutral=neutralRig();let figures:Mannequin[]=[];let originals:Mannequin[]=[];
  let pins=$state<HandlePoint[]>([]),reachDistance=$state<number|null>(null),limitActive=$state(false);
  let pinWorld:{id:string;label:string;position:THREE.Vector3}[]=[];let lastFocus=0;
  function updatePins(){
    if(!editing||!handles||!pose){if(pins.length)pins=[];return;}
    const {width,height}=host.getBoundingClientRect();camera.updateMatrixWorld();
    const frame=view==='reference'&&referenceCamera?referenceFrame(referenceCamera,width,height):{x:0,y:0,width,height};
    pins=separateHandles(pinWorld.flatMap(pin=>{const point=pin.position.clone().project(camera);const x=frame.x+(point.x+1)*frame.width/2,y=frame.y+(1-point.y)*frame.height/2;return point.z<1&&point.z>-1&&Math.abs(point.x)<.96&&Math.abs(point.y)<.94?[{id:pin.id,label:pin.label,x,y,anchorX:x,anchorY:y}]:[];}),width,height);
  }
  function disposeFigures(){for(const f of [...figures,...originals]){scene.remove(f.group);f.dispose();}figures=[];originals=[];}
  function syncGizmo(){
    if(!initialized)return;
    if(!editing||!pose||tool==='select'||view==='reference'){gizmo.detach();marker.visible=false;return;}
    const node=pose.rig.nodes.find(n=>selectedBone===figureKey?!n.parent:n.id===selectedBone);
    if(!node||tool==='translate'&&pose.pins?.[selectedBone]?.position||tool==='rotate'&&pose.pins?.[selectedBone]?.rotation){gizmo.detach();marker.visible=false;return;}
    const frame=gizmoFrame(pose,selectedBone);
    marker.visible=selectedBone!==figureKey;marker.position.copy(frame.position);
    if(gizmo.dragging)return;
    proxy.position.copy(frame.position);proxy.quaternion.copy(frame.rotation);
    const moving=tool==='translate'&&(selectedBone===figureKey||isReachJoint(selectedBone));
    gizmo.setMode(moving?'translate':'rotate');gizmo.setSpace(moving?'world':space);gizmo.setTranslationSnap(snap?.01:null);gizmo.setRotationSnap(snap?THREE.MathUtils.degToRad(5):null);
    gizmo.showX=(axis==='all'||axis==='x')&&(moving||editable(node,0));gizmo.showY=(axis==='all'||axis==='y')&&(moving||editable(node,1));gizmo.showZ=(axis==='all'||axis==='z')&&(moving||editable(node,2));
    gizmo.attach(proxy);invalidate();
  }
  function refresh(){
    if(!initialized)return;const started=performance.now();const members=pose?[pose,...companions]:[null];
    // Selection reorders the members. Reuse their existing meshes/skeletons;
    // adding, removing or converting one mannequin only replaces that member.
    const previous=figures;figures=members.map(p=>previous.find(f=>f.rig===(p?.rig??neutral)&&f.personId===(p?.personId??0))??new Mannequin(p?.rig??neutral,p?.personId??0));
    for(const f of previous)if(!figures.includes(f)){scene.remove(f.group);f.dispose();}
    for(const f of figures)if(f.group.parent!==scene)scene.add(f.group);
    figures.forEach((f,i)=>f.update(members[i],theme,i===0,editing?selectedBone:'',editing&&ghostPartners&&i>0));
    const oldGhosts=originals;originals=originalPoses.map(p=>oldGhosts.find(f=>f.rig===p.rig&&f.personId===p.personId)??new Mannequin(p.rig,p.personId));
    for(const f of oldGhosts)if(!originals.includes(f)){scene.remove(f.group);f.dispose();}
    originals.forEach((f,i)=>{if(f.group.parent!==scene)scene.add(f.group);f.update(originalPoses[i],theme,false,'',true);});
    if(pose&&editing){const world=forwardKinematics(pose.rig,previewRotations(pose),pose.translation);const shown=handleJoints(pose,jointGroup,selectedBone);for(const id of Object.keys(pose.pins??{})){const node=pose.rig.nodes.find(n=>n.id===id);if(node&&!shown.some(n=>n.id===id))shown.push(node);}pinWorld=shown.map(n=>({id:n.id,label:jointLabel(n),position:world.get(n.id)!.position.clone().multiplyScalar(.01)}));}else pinWorld=[];
    scene.background=new THREE.Color(theme==='light'?0xedf0f7:theme==='neon'?0x100d1d:0x111623);
    (grid.material as THREE.Material).opacity=theme==='light'?.32:.22;grid.visible=showGrid;
    (floor.material as THREE.MeshStandardMaterial).color.set(theme==='light'?0xe0e3ee:theme==='neon'?0x1a132b:0x1b2031);
    syncGizmo();invalidate();if(import.meta.env.DEV)host.dataset.updateMs=(performance.now()-started).toFixed(2);
  }
  function cameraView(){
    if(!initialized||!cameraCommands.accept({view,reset,scene:pose?.imageId??'',reference:referenceCamera}))return;
    // Flush orbit inertia before an explicit camera command.
    const damping=controls.enableDamping;controls.enableDamping=false;controls.update();controls.enableDamping=damping;
    camera.aspect=host.clientWidth/Math.max(1,host.clientHeight);camera.updateProjectionMatrix();controls.enabled=!(view==='reference'&&referenceCamera);
    if(view==='reference'&&referenceCamera){const ref=referenceCamera;if(ref.version===1){camera.position.fromArray(ref.originCm).multiplyScalar(-.01);camera.quaternion.identity();controls.target.copy(camera.position).add(new THREE.Vector3(0,0,-Math.max(1,Math.abs(ref.originCm[2])*.01)));}else{const transform=cameraTransform(ref);camera.position.copy(transform.position);camera.quaternion.copy(transform.quaternion);controls.target.copy(camera.position).add(new THREE.Vector3(0,0,-1).applyQuaternion(camera.quaternion));}camera.projectionMatrix.copy(referenceProjection(ref));camera.projectionMatrixInverse.copy(camera.projectionMatrix).invert();camera.updateMatrixWorld();onCameraProfile('reference');invalidate();return;}
    const bounds=new THREE.Box3();for(const f of figures)bounds.expandByObject(f.group);const sphere=bounds.getBoundingSphere(new THREE.Sphere()),target=sphere.center;
    const vertical=THREE.MathUtils.degToRad(camera.fov),horizontal=2*Math.atan(Math.tan(vertical/2)*camera.aspect),distance=Math.max(1.8,sphere.radius/Math.sin(Math.min(vertical,horizontal)/2)*1.13);
    controls.target.copy(target);camera.position.copy(target).add(new THREE.Vector3(...(view==='side'?[1,.08,0]:view==='back'?[0,.08,-1]:[0,.08,1]) as [number,number,number]).normalize().multiplyScalar(distance));controls.update();onCameraProfile(view);invalidate();
  }
  $effect(()=>{active;if(initialized)untrack(activity);});
  $effect(()=>{pose;companions;originalPoses;theme;showGrid;editing;selectedBone;tool;space;snap;axis;handles;ghostPartners;jointGroup;view;if(initialized)refresh();});
  $effect(()=>{view;reset;pose?.imageId;referenceCamera;if(initialized)untrack(cameraView);});
  $effect(()=>{focus;if(initialized&&focus!==lastFocus&&pose&&view!=='reference'){lastFocus=focus;onCameraProfile(null);const direction=camera.position.clone().sub(controls.target).normalize();
    if(selectedBone===figureKey){const member=figures.find(f=>f.personId===pose!.personId);if(member){const sphere=new THREE.Box3().setFromObject(member.group).getBoundingSphere(new THREE.Sphere());const angle=Math.min(THREE.MathUtils.degToRad(camera.fov),2*Math.atan(Math.tan(THREE.MathUtils.degToRad(camera.fov)/2)*camera.aspect));controls.target.copy(sphere.center);camera.position.copy(sphere.center).addScaledVector(direction,Math.max(1.8,sphere.radius/Math.sin(angle/2)*1.13));}}
    else{const frame=gizmoFrame(pose,selectedBone);if(tool==='rotate'&&axis!=='all'){direction.set(axis==='x'?1:0,axis==='y'?1:0,axis==='z'?1:0);if(space==='local')direction.applyQuaternion(frame.rotation);if(direction.dot(camera.position.clone().sub(controls.target))<0)direction.negate();}controls.target.copy(frame.position);camera.position.copy(frame.position).addScaledVector(direction,.7);}controls.update();invalidate();}});
  onMount(()=>{
    let observer:ResizeObserver,disposed=false;const pointer=new THREE.Vector2(),ray=new THREE.Raycaster();let down=[0,0],transformed=false;
    const pointerDown=(e:PointerEvent)=>{down=[e.clientX,e.clientY];transformed=false;};
    const pointerUp=(e:PointerEvent)=>{if(!editing||!pose||transformed||gizmo.axis||Math.hypot(e.clientX-down[0],e.clientY-down[1])>4)return;const r=host.getBoundingClientRect();const frame=view==='reference'&&referenceCamera?referenceFrame(referenceCamera,r.width,r.height):{x:0,y:0,width:r.width,height:r.height};pointer.set((e.clientX-r.left-frame.x)/frame.width*2-1,-(e.clientY-r.top-frame.y)/frame.height*2+1);ray.setFromCamera(pointer,camera);const hit=ray.intersectObjects(figures.map(f=>f.group),true)[0];if(hit){const figure=figures.find(f=>f.personId===hit.object.userData.personId),bone=figure?.pickBone(hit);if(bone)onSelect(figure!.personId,bone);}};
    try{
      renderer=new THREE.WebGLRenderer({antialias:true,alpha:false,powerPreference:'low-power'});renderer.setPixelRatio(Math.min(devicePixelRatio,1.5));renderer.outputColorSpace=THREE.SRGBColorSpace;host.appendChild(renderer.domElement);
      scene=new THREE.Scene();camera=new THREE.PerspectiveCamera(35,1,.01,50);scene.add(new THREE.HemisphereLight(0xe4e7ff,0x302a45,2.3));const light=new THREE.DirectionalLight(0xffffff,2.7);light.position.set(3,5,4);scene.add(light);
      grid=new THREE.GridHelper(10,50,0x848099,0x625b7a);(grid.material as THREE.Material).transparent=true;scene.add(grid);
      floor=new THREE.Mesh(new THREE.CircleGeometry(1.35,80),new THREE.MeshStandardMaterial({roughness:1,metalness:.1}));floor.rotation.x=-Math.PI/2;floor.position.y=-.035;scene.add(floor);
      controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true;controls.dampingFactor=.12;controls.minDistance=.25;controls.maxDistance=9;controls.maxPolarAngle=Math.PI*.94;let navigating=false;controls.addEventListener('start',()=>navigating=true);controls.addEventListener('end',()=>navigating=false);controls.addEventListener('change',()=>{invalidate();if(navigating)onCameraProfile(null);});
      proxy=new THREE.Object3D();scene.add(proxy);gizmo=new TransformControls(camera,renderer.domElement);gizmo.setSize(1.15);gizmo.setColors(0xff668a,0xa78bfa,0x6174ff,0xfcee09);scene.add(gizmo.getHelper());
      marker=new THREE.Mesh(new THREE.SphereGeometry(.014,12,8),new THREE.MeshBasicMaterial({color:0xa78bfa,depthTest:false}));marker.renderOrder=5;scene.add(marker);marker.visible=false;
      gizmo.addEventListener('mouseDown',()=>{transformed=true;reachDistance=null;limitActive=false;controls.enabled=false;onDrag(true);});
      gizmo.addEventListener('mouseUp',()=>{controls.enabled=view!=='reference';onDrag(false);syncGizmo();invalidate();});
      gizmo.addEventListener('change',()=>invalidate());
      gizmo.addEventListener('objectChange',()=>{
        if(!pose)return;
        let next:Pose;
        if(gizmo.mode==='translate'){
          if(selectedBone===figureKey){const root=pose.rig.nodes.find(n=>!n.parent)!;next={...pose,translation:proxy.position.clone().multiplyScalar(100).sub(new THREE.Vector3().fromArray(root.center)).toArray(),edited:true};}
          else {const started=performance.now(),result=moveLimb(pose,selectedBone,proxy.position.clone().multiplyScalar(100).toArray());reachDistance=result.distanceCm;next=result.pose;if(import.meta.env.DEV)host.dataset.ikMs=(performance.now()-started).toFixed(2);}
        }else {const result=boundedGizmoRotation(pose,selectedBone,proxy.quaternion);next=result.pose;limitActive=result.limited;}
        next=preservePins(next,selectedBone,8);
        // TransformControls follows the cursor even beyond a constrained pose.
        // Return its visible proxy to the achieved FK on every drag event.
        const achieved=gizmoFrame(next,selectedBone);proxy.position.copy(achieved.position);proxy.quaternion.copy(achieved.rotation);proxy.updateMatrixWorld(true);marker.position.copy(achieved.position);
        onEdit(next);invalidate();
      });
      renderer.domElement.addEventListener('pointerdown',pointerDown);renderer.domElement.addEventListener('pointerup',pointerUp);
      observer=new ResizeObserver(()=>{const {width,height}=host.getBoundingClientRect();activity();if(width<=0||height<=0)return;renderer.setSize(width,height,false);camera.aspect=width/height;camera.updateProjectionMatrix();if(view==='reference'&&referenceCamera){camera.projectionMatrix.copy(referenceProjection(referenceCamera));camera.projectionMatrixInverse.copy(camera.projectionMatrix).invert();}invalidate();});observer.observe(host);
      loadMannequin().then(()=>{if(disposed)return;initialized=true;refresh();cameraView();onReady();}).catch(e=>{if(disposed)return;error='The mannequin preview could not load. Verify or reinstall this PoseSnap copy, then reopen it.';console.error(e);onReady(error);});
      let benchmark=import.meta.env.DEV&&new URLSearchParams(location.search).has('benchmark'),benchmarkFrames=0,started=0;
      const profiling=import.meta.env.DEV&&new URLSearchParams(location.search).has('profile');let callbacks=0;
      const render=()=>{if(profiling){host.dataset.previewCallbacks=String(++callbacks);host.dataset.previewResources=JSON.stringify({...renderer.info.memory,programs:renderer.info.programs?.length,frames:renderer.info.render.frame});}if(!active||document.visibilityState!=='visible'||!host.clientWidth||!host.clientHeight)return false;const moving=view!=='reference'&&controls.update();if(benchmark&&initialized){invalidate();if(!started)started=performance.now();benchmarkFrames++;if(performance.now()-started>=5000){host.dataset.benchmarkFps=(benchmarkFrames*1000/(performance.now()-started)).toFixed(1);benchmark=false;}}if(dirty){updatePins();if(view==='reference'&&referenceCamera){const frame=referenceFrame(referenceCamera,host.clientWidth,host.clientHeight);renderer.setScissorTest(false);renderer.setViewport(0,0,host.clientWidth,host.clientHeight);renderer.clear();renderer.setViewport(frame.x,frame.y,frame.width,frame.height);renderer.setScissor(frame.x,frame.y,frame.width,frame.height);renderer.setScissorTest(true);}else{renderer.setScissorTest(false);renderer.setViewport(0,0,host.clientWidth,host.clientHeight);}renderer.render(scene,camera);dirty=false;}return !!moving||benchmark;};frames=new PreviewFrames(render);document.addEventListener('visibilitychange',activity);activity();
    }catch(e){error='3D preview could not start. Check graphics drivers and WebGL support.';console.error(e);onReady(error);}
    return()=>{disposed=true;frames?.dispose();document.removeEventListener('visibilitychange',activity);observer?.disconnect();disposeFigures();grid?.geometry.dispose();(grid?.material as THREE.Material)?.dispose();floor?.geometry.dispose();(floor?.material as THREE.Material)?.dispose();marker?.geometry.dispose();(marker?.material as THREE.Material)?.dispose();gizmo?.dispose();controls?.dispose();renderer?.domElement.removeEventListener('pointerdown',pointerDown);renderer?.domElement.removeEventListener('pointerup',pointerUp);renderer?.dispose();};
  });
</script>
<div class="viewport" bind:this={host} aria-label="Interactive 3D pose preview">
  {#if overlay&&view==='reference'&&referenceCamera&&pose&&!pose.edited&&!pose.quality?.stale&&pose.quality?.markers?.length}<svg class="reference-landmarks" viewBox={'0 0 '+referenceCamera.imageSize.join(' ')} preserveAspectRatio="xMidYMid meet" aria-label="Measured image landmarks and projected target agreement"><g>{#each pose.quality.markers as point}{#if point.predicted}<line x1={point.xy[0]} y1={point.xy[1]} x2={point.predicted[0]} y2={point.predicted[1]}/><circle cx={point.xy[0]} cy={point.xy[1]} r="4"/><circle class="predicted" cx={point.predicted[0]} cy={point.predicted[1]} r="3"/>{/if}{/each}</g></svg>{/if}
  {#if error}<p class="webgl-error">{error}</p>{/if}
  {#if editing&&pose&&!error}
    <div class="joint-handles" aria-label="Mannequin joint handles"><svg class="handle-leaders" aria-hidden="true">{#each pins as pin}<line x1={pin.anchorX} y1={pin.anchorY} x2={pin.x} y2={pin.y}/><circle cx={pin.anchorX} cy={pin.anchorY} r="2"/>{/each}</svg>{#each pins as pin(pin.id)}<button class="joint-handle" class:selected={pin.id===selectedBone} class:pinned={!!pose?.pins?.[pin.id]} data-bone={pin.id} style:left={pin.x+'px'} style:top={pin.y+'px'} aria-label={'Select '+pin.label} aria-pressed={pin.id===selectedBone} use:tooltip={pin.label+(pose?.pins?.[pin.id]?' · Pinned. Select to inspect or unpin.':' · Click to select. Use E to rotate; hands and feet also support W to move.')} onclick={()=>onSelect(pose!.personId,pin.id)}>{#if pose?.pins?.[pin.id]}<Pin size={12}/>{:else}{handleGlyph(pin.label)}{/if}</button>{/each}</div>
    <div class="editor-view-hint">{view==='reference'?'Reference camera locked · Use Front or Side to drag joints':tool==='translate'&&pose.pins?.[selectedBone]?.position?'Position pinned · Unpin to move this joint':tool==='rotate'&&pose.pins?.[selectedBone]?.rotation?'Rotation pinned · Unpin to rotate this joint':tool==='select'?'Choose a joint handle · Drag empty space to orbit':tool==='translate'&&selectedBone!==figureKey?'Drag an arrow to move this limb · Bone lengths stay fixed':tool==='translate'?'Drag an arrow to position the figure':'Drag a coloured ring to rotate · Choose one axis for precision'}{#if limitActive&&tool==='rotate'}<span role="status">Joint limit reached · drag back to continue</span>{:else if reachDistance!==null&&reachDistance>.5}<span role="status">Reach limited · {reachDistance.toFixed(1)} cm from target</span>{/if}</div>
  {/if}
</div>

<style>.reference-landmarks{position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:2}.reference-landmarks line{stroke:#ff3fa4;stroke-width:1.5;opacity:.7}.reference-landmarks circle{fill:none;stroke:#a78bfa;stroke-width:2}.reference-landmarks .predicted{fill:#fcee09;stroke:#111623;stroke-width:1}

  .joint-handle.pinned{border:2px solid var(--accent);background:var(--deep);color:var(--accent);box-shadow:0 0 0 3px var(--tint)}
  .joint-handle.pinned.selected{background:var(--accent);color:var(--on-accent)}
</style>
