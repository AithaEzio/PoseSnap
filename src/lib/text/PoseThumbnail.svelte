<script lang="ts">
  import {forwardKinematics,previewRotations} from '../pose';
  import type {Pose} from '../types';
  let {poses}:{poses:Pose[]}=$props();
  const drawing=$derived.by(()=>{
    const lines:{a:number[];b:number[]}[]=[];
    for(const pose of poses){
      const world=forwardKinematics(pose.rig,previewRotations(pose),pose.translation);
      for(const node of pose.rig.nodes){
        if(!node.parent||!/hip|pelvis|abdomen|spine|chest|neck|head|collar|shldr|upperarm|forearm|hand$|thigh|shin|foot|toe/i.test(node.id))continue;
        const a=world.get(node.parent)?.position,b=world.get(node.id)?.position;
        if(a&&b)lines.push({a:[a.x+.2*a.z,a.y],b:[b.x+.2*b.z,b.y]});
      }
    }
    const points=lines.flatMap(l=>[l.a,l.b]);if(!points.length)return [];
    const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]);
    const xmin=Math.min(...xs),xmax=Math.max(...xs),ymin=Math.min(...ys),ymax=Math.max(...ys);
    const scale=Math.min(112/Math.max(1,xmax-xmin),80/Math.max(1,ymax-ymin));
    const project=(p:number[])=>[70+(p[0]-(xmin+xmax)/2)*scale,92-(p[1]-ymin)*scale];
    return lines.map(l=>({a:project(l.a),b:project(l.b)}));
  });
</script>

<svg viewBox="0 0 140 108" aria-hidden="true">
  <path d="M12 96H128" class="ground"/>
  {#each drawing as line}<line x1={line.a[0]} y1={line.a[1]} x2={line.b[0]} y2={line.b[1]}/>{/each}
</svg>

<style>
  svg{width:100%;height:78px;display:block;color:var(--text)}line{stroke:currentColor;stroke-width:3.5;stroke-linecap:round}.ground{stroke:var(--line);stroke-width:1}
</style>
