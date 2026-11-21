<script lang="ts">
  import { onMount } from 'svelte';
  import * as THREE from 'three';
  import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
  import { RotateCcw, LoaderCircle, AlertCircle } from 'lucide-svelte';
  import { tooltip } from '../tooltip';
  import { ExpressionFaceModel, loadFacePreview } from './previewAsset';
  import type { Theme } from '../types';
  let {actions,referenceMatrix=[],theme='dark',active=true}:{actions:Record<string,number>;referenceMatrix?:number[];theme?:Theme;active?:boolean}=$props();
  let host:HTMLDivElement,profile=$state<string|null>('front');
  let loading=$state(true),ready=$state(false),error=$state(''),canRetry=$state(true);
  let update:()=>void=()=>{},redraw:()=>void=()=>{},setView:(value:string)=>void=()=>{};
  let retry=$state<()=>void>(()=>{});
  $effect(()=>{actions;active;update();});
  $effect(()=>{theme;active;redraw();});
  onMount(()=>{
    let renderer:THREE.WebGLRenderer;
    try{renderer=new THREE.WebGLRenderer({antialias:true,alpha:true,powerPreference:'low-power'});}
    catch{loading=false;canRetry=false;error='The 3D face preview needs WebGL. Restart PoseSnap or check your graphics driver. Expression extraction and export remain available.';return;}
    renderer.setPixelRatio(Math.min(devicePixelRatio,1.5));renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.setClearColor(0,0);host.appendChild(renderer.domElement);
    const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(32,1,.001,30),target=new THREE.Vector3();
    const orbit=new OrbitControls(camera,renderer.domElement);orbit.enablePan=false;orbit.enableDamping=false;
    scene.add(new THREE.HemisphereLight(0xf2efff,0x777286,1.8));
    const key=new THREE.DirectionalLight(0xfff9f3,2.5);key.position.set(-3,4,5);scene.add(key);
    const rim=new THREE.DirectionalLight(0xc3b5fa,1.2);rim.position.set(3,1,-3);scene.add(rim);
    let disposed=false,choosing=false,distance=1,model:ExpressionFaceModel|null=null;
    const framing=new THREE.Vector3();
    redraw=()=>{if(!disposed&&active&&host.clientWidth&&host.clientHeight)renderer.render(scene,camera);};
    update=()=>{if(disposed||!active||!model)return;model.update(actions);redraw();};
    orbit.addEventListener('change',()=>{if(!choosing)profile=null;redraw();});
    setView=(view)=>{
      if(!model||disposed)return;
      choosing=true;
      const offset=view==='side'?new THREE.Vector3(distance,0,0):view==='three-quarter'?new THREE.Vector3(distance*.65,0,distance*.76):new THREE.Vector3(0,0,distance);
      if(view==='reference'&&referenceMatrix.length===16&&referenceMatrix.every(Number.isFinite)){
        const rotation=new THREE.Matrix4().extractRotation(new THREE.Matrix4().fromArray(referenceMatrix));
        offset.applyQuaternion(new THREE.Quaternion().setFromRotationMatrix(rotation).invert());
      }
      camera.position.copy(offset.add(target));orbit.target.copy(target);orbit.update();profile=view;choosing=false;redraw();
    };
    const resize=()=>{
      const width=host.clientWidth,height=host.clientHeight;if(!width||!height)return;
      renderer.setSize(width,height);camera.aspect=width/height;
      if(model){
        const nextDistance=Math.max(framing.y,framing.x/camera.aspect)/(2*Math.tan(THREE.MathUtils.degToRad(camera.fov/2)))*1.25+framing.z/2;
        // Scale the current offset, keeping its direction and the user's relative zoom.
        camera.position.sub(orbit.target).multiplyScalar(nextDistance/distance).add(orbit.target);
        distance=nextDistance;camera.near=Math.max(.001,distance/100);camera.far=distance*15;
        orbit.minDistance=distance*.45;orbit.maxDistance=distance*2.6;
        choosing=true;orbit.update();choosing=false;
      }
      camera.updateProjectionMatrix();redraw();
    };
    const observer=new ResizeObserver(resize);observer.observe(host);
    async function load(){
      loading=true;error='';
      try{
        const asset=await loadFacePreview();if(disposed)return;
        const next=new ExpressionFaceModel(asset);
        if(model){scene.remove(model.group);model.dispose();}
        model=next;scene.add(model.group);
        model.bounds.getSize(framing);model.bounds.getCenter(target);
        if(asset.manifest.framing){target.fromArray(asset.manifest.framing.center);framing.y=asset.manifest.framing.height;framing.x=asset.manifest.framing.width;}
        // Expression updates never reset the camera. Resizing only adapts its framing.
        ready=true;loading=false;model.update(actions);resize();setView('front');
      }catch(e){if(!disposed){loading=false;ready=false;error=e instanceof Error?e.message:String(e);}}
    }
    retry=()=>void load();void load();resize();
    return()=>{disposed=true;observer.disconnect();orbit.dispose();model?.dispose();renderer.dispose();renderer.domElement.remove();};
  });
</script>
<div class="face-view" bind:this={host} role="region" aria-label="Interactive expression face adapted from ComputerCat’s model. Drag to orbit and scroll to zoom.">
  {#if loading}<div class="face-asset-status" role="status"><LoaderCircle size={20} class="spinner"/><strong>Preparing expression face</strong><span>Loading the local preview rig.</span></div>
  {:else if error}<div class="face-asset-status error" role="alert"><AlertCircle size={20}/><strong>Face preview needs attention</strong><span>{error}</span>{#if canRetry}<button class="secondary" onclick={retry} use:tooltip={'Retry loading the local expression face asset. Your expression stays intact.'}>Retry preview</button>{/if}</div>{/if}
</div>
<div class="face-camera" aria-label="Face preview cameras">
  {#each [{id:'reference',label:'Reference'},{id:'front',label:'Front'},{id:'three-quarter',label:'¾ view'},{id:'side',label:'Side'}] as camera}
    <button disabled={!ready||camera.id==='reference'&&referenceMatrix.length!==16} class:active={ready&&profile===camera.id} aria-pressed={ready&&profile===camera.id} use:tooltip={camera.id==='reference'?'Inspect the estimated photograph head angle. This changes the preview camera, never the DAZ head orientation.':'Inspect the face from '+camera.label+'. Drag to orbit freely.'} onclick={()=>setView(camera.id)}>{camera.label}</button>
  {/each}
  <button disabled={!ready} aria-label="Reset facial preview camera" use:tooltip={'Return to the front view. Expression stays intact.'} onclick={()=>setView('front')}><RotateCcw size={14}/></button>
</div>
