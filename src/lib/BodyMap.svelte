<script lang="ts">
  import { quickJoints, jointLabel, type JointGroup } from './editor';
  import { tooltip } from './tooltip';
  import type { Pose, RigNode } from './types';
  let {pose,selected,group,side='l',busy=false,onSelect}:{pose:Pose;selected:string;group:JointGroup;side?:string;busy?:boolean;onSelect:(id:string)=>void}=$props();
  const nodes=$derived(group==='hands'?quickJoints(pose,'hands').filter(n=>n.id[0]===side):group==='body'?[...quickJoints(pose,'body'),...quickJoints(pose,'arms'),...quickJoints(pose,'legs')]:quickJoints(pose,group));
  function point(n:RigNode):number[]{
    const id=n.id.toLowerCase().replaceAll('_',''),left=id[0]==='l',sign=left?1:-1;
    if(group==='hands'){
      if(id.endsWith('hand'))return [53,84];
      const match=id.match(/(thumb|index|mid|middle|ring|pinky)([123])$/);
      if(!match)return [50,50];
      const segment=Number(match[2]);
      if(match[1]==='thumb')return [[23,61],[16,51],[10,41]][segment-1];
      return [{index:37,mid:54,middle:54,ring:71,pinky:88}[match[1] as 'index'],[43,29,15][segment-1]];
    }
    const torso:Record<string,number[]>={head:[50,8],necklower:[64,18],neckupper:[50,18],neck1:[64,18],neck2:[50,18],chestupper:[50,26],spine4:[50,26],chestlower:[50,34],spine3:[50,34],abdomenupper:[50,42],spine2:[50,42],abdomenlower:[50,50],spine1:[50,50],hip:[50,58],pelvis:[50,66]};
    if(torso[id])return torso[id];
    if(/collar|shoulder/.test(id))return [50+sign*12,24];
    if(/shldr|upperarm/.test(id))return [50+sign*24,29];
    if(/forearm/.test(id))return [50+sign*32,43];
    if(/hand/.test(id))return [50+sign*42,57];
    if(/thigh/.test(id))return [50+sign*12,65];
    if(/shin/.test(id))return [50+sign*14,79];
    if(/foot/.test(id))return [50+sign*16,91];
    return [50+sign*23,97];
  }
</script>
<div class="body-map" class:hand-map={group==='hands'} class:right-hand={group==='hands'&&side==='r'} aria-label={group==='hands'?(side==='l'?'Left':'Right')+' hand joint map':'Body joint map'}>
  <svg viewBox="0 0 200 320" aria-hidden="true">
    {#if group==='hands'}
      <path class="map-shape" d="M75 268 L67 237 Q40 215 24 163 L18 133 Q18 121 27 121 Q37 121 43 140 L55 163 L61 141 L61 53 Q61 40 73 40 Q85 40 85 53 L85 124 L95 124 L95 25 Q95 12 108 12 Q121 12 121 25 L121 126 L130 126 L130 43 Q130 30 143 30 Q156 30 156 43 L156 143 L163 143 L163 73 Q163 62 177 62 Q189 62 189 73 L189 176 Q187 215 155 241 L143 268 Z"/>
      <path class="map-line" d="M73 137 L108 143 L143 151 L177 164 M63 203 Q108 181 153 207"/>
    {:else}
      <path class="map-shape" d="M88 60 Q79 44 79 28 Q79 6 100 6 Q121 6 121 28 Q121 44 112 60 L125 70 Q146 69 154 91 L174 134 L195 179 L181 186 L155 149 L136 113 L126 157 L127 193 L139 216 L146 291 L153 310 L132 314 L120 296 L110 230 L100 211 L90 230 L80 296 L68 314 L47 310 L54 291 L61 216 L73 193 L74 157 L64 113 L45 149 L19 186 L5 179 L26 134 L46 91 Q54 69 75 70 Z"/>
      <path class="map-line" d="M74 157 Q100 170 126 157 M73 193 Q100 177 127 193 M46 91 L64 113 M136 113 L154 91 M61 249 L85 249 M115 249 L139 249"/>
    {/if}
  </svg>
  {#each nodes as n}
    {@const p=point(n)}
    <button class="map-joint" class:active={selected===n.id} style={`left:${group==='hands'&&side==='r'?100-p[0]:p[0]}%;top:${p[1]}%`} aria-label={'Select '+jointLabel(n)} aria-pressed={selected===n.id} disabled={busy} use:tooltip={jointLabel(n)+' · Select this joint to move or rotate its pose.'} onclick={()=>onSelect(n.id)}><span></span></button>
  {/each}
  <span class="map-side">{group==='hands'?(side==='l'?'Left hand':'Right hand'):'Front · your left is figure right'}</span>
</div>
<p class="map-selection" aria-live="polite">{pose.rig.nodes.find(n=>n.id===selected)?jointLabel(pose.rig.nodes.find(n=>n.id===selected)!):'Whole figure'}</p>
