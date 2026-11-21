/* Crop/flip checks diagnose inconsistent evidence; they never average away asymmetry. */
globalThis.FaceEvidence={
  windows(width,height){
    const windows=[{x:0,y:0,width,height,full:true}];
    if(Math.max(width,height)<=900)return windows;
    const side=Math.max(640,Math.ceil(Math.max(width,height)/3.25)),tileWidth=Math.min(width,side),tileHeight=Math.min(height,side);
    const positions=(extent,size)=>{const count=Math.max(1,Math.min(4,Math.ceil((extent-size)/(size*.65))+1));return Array.from({length:count},(_,i)=>count===1?0:i*(extent-size)/(count-1));};
    for(const y of positions(height,tileHeight))for(const x of positions(width,tileWidth))windows.push({x,y,width:tileWidth,height:tileHeight,full:false});
    return windows;
  },
  roll(face){const a=face.landmarks[33],b=face.landmarks[263];return a&&b?Math.atan2(b[1]-a[1],b[0]-a[0]):0;},
  merge(faces){
    const accepted=[];
    const area=f=>(f.box[2]-f.box[0])*(f.box[3]-f.box[1]);
    for(const face of [...faces].sort((a,b)=>(b.resolution??0)-(a.resolution??0)||area(b)-area(a))){
      const b=face.box,cx=(b[0]+b[2])/2,cy=(b[1]+b[3])/2;
      if(accepted.some(a=>{const c=a.box,nose=face.landmarks[1],otherNose=a.landmarks[1],eyes=face.landmarks[33],otherEye=face.landmarks[263];if(nose&&otherNose&&eyes&&otherEye&&Math.hypot(nose[0]-otherNose[0],nose[1]-otherNose[1])<.35*Math.hypot(eyes[0]-otherEye[0],eyes[1]-otherEye[1]))return true;const overlap=Math.max(0,Math.min(b[2],c[2])-Math.max(b[0],c[0]))*Math.max(0,Math.min(b[3],c[3])-Math.max(b[1],c[1]));return overlap/Math.min(area(face),area(a))>.55&&Math.hypot(cx-(c[0]+c[2])/2,cy-(c[1]+c[3])/2)<.3*Math.min(b[3]-b[1],c[3]-c[1]);}))continue;
      accepted.push(face);
    }
    // Reading order, grouping rows by face height; x-sort alone scrambles collages.
    const rows=[];
    for(const face of accepted.sort((a,b)=>(a.box[1]+a.box[3])-(b.box[1]+b.box[3]))){const cy=(face.box[1]+face.box[3])/2,h=face.box[3]-face.box[1];let row=rows.find(r=>Math.abs(r.y-cy)<Math.min(r.height,h)*.45);if(!row){row={y:cy,height:h,faces:[]};rows.push(row);}row.faces.push(face);}
    return rows.flatMap(row=>row.faces.sort((a,b)=>a.box[0]-b.box[0])).slice(0,32).map((face,i)=>({...face,id:i+1,roll:this.roll(face)}));
  },
  restore(face,window,size,angle=0){
    const c=Math.cos(angle),s=Math.sin(angle),cx=window.x+window.width/2,cy=window.y+window.height/2,scale=window.width/size;
    const restore=p=>{const x=(p[0]-size/2)*scale,y=(p[1]-size/2)*scale;return [cx+c*x-s*y,cy+s*x+c*y,p[2]*scale];};
    const points=face.landmarks.map(restore),corners=[[face.box[0],face.box[1],0],[face.box[2],face.box[1],0],[face.box[0],face.box[3],0],[face.box[2],face.box[3],0]].map(restore);
    const matrix=[...face.matrix];
    // Undo the image-plane rotation on the orientation, in Y-up coordinates.
    for(let col=0;col<4;col++){const x=matrix[col*4],y=matrix[col*4+1];matrix[col*4]=c*x+s*y;matrix[col*4+1]=-s*x+c*y;}
    return {...face,landmarks:points,matrix,box:[Math.min(...corners.map(p=>p[0])),Math.min(...corners.map(p=>p[1])),Math.max(...corners.map(p=>p[0])),Math.max(...corners.map(p=>p[1]))]};
  },
  details(face,pixels){
    const smooth=(a,b,v)=>{const t=Math.max(0,Math.min(1,(v-a)/(b-a)));return t*t*(3-2*t);};
    const r=face.matrix,q=face.landmarks.map(p=>[0,1,2].map(i=>r[i*4]*p[0]-r[i*4+1]*p[1]-r[i*4+2]*p[2]));
    const distance=(a,b)=>Math.hypot(...q[a].map((v,i)=>v-q[b][i])),eye=distance(33,263),lip=distance(78,308),gap=distance(13,14)/Math.max(lip,1);
    const yaw=Math.abs(Math.atan2(r[8],r[10])),pitch=Math.abs(Math.atan2(-r[9],r[10]));
    const frontal=1-smooth(.5,1.05,yaw),sealed=1-smooth(.04,.12,gap),notSmile=1-smooth(.25,.6,Math.max(face.actions.mouthSmileLeft??0,face.actions.mouthSmileRight??0));
    // A conservative geometry estimate fills a model output that is effectively
    // absent in this task. Identity and occlusion remain ambiguity; retain raw
    // coefficients and label the measurement, never call it model confidence.
    const fullness=distance(172,397)/Math.max(distance(234,454),1),lower=distance(1,152)/Math.max(eye,1);
    const compressedLips=1-smooth(.56,.61,distance(61,291)/Math.max(eye,1));
    const puff=sealed*notSmile*frontal*(1-smooth(.3,.65,pitch))*Math.sqrt(smooth(.79,.812,fullness)*compressedLips*(1-smooth(.80,.85,lower)));
    const brow=side=>{const inner=side==='Left'?336:107,corner=side==='Left'?362:133;const height=(q[inner][1]-q[corner][1])/Math.max(eye,1);return frontal*smooth(.245,.18,height)*.75;};
    let tongue=0,coverage=0;
    if(pixels&&gap>.35&&frontal>.35){
      const p=face.landmarks,left=p[78],right=p[308],top=p[13],bottom=p[14],width=Math.abs(right[0]-left[0]),height=Math.abs(bottom[1]-top[1]);
      const x0=Math.max(0,Math.floor(Math.min(left[0],right[0])+width*.18)),x1=Math.min(pixels.width,Math.ceil(Math.max(left[0],right[0])-width*.18));
      const y0=Math.max(0,Math.floor(top[1]+height*.4)),y1=Math.min(pixels.height,Math.ceil(bottom[1]+height*.15));let pink=0,total=0;
      for(let y=y0;y<y1;y+=2)for(let x=x0;x<x1;x+=2){const i=(y*pixels.width+x)*4,[red,green,blue]=pixels.data.slice(i,i+3);total++;if(red>65&&red>green*1.12&&blue>green*.86&&red>blue*1.02&&red-green>12)pink++;}
      coverage=total?pink/total:0;tongue=smooth(.16,.5,coverage)*smooth(.35,.65,gap)*frontal;
    }
    return {cheekPuff:puff,browDownLeft:Math.max(face.actions.browDownLeft??0,brow('Left')),browDownRight:Math.max(face.actions.browDownRight??0,brow('Right')),jawOpen:Math.max(face.actions.jawOpen??0,smooth(.06,.75,gap)*.9),tongueOut:tongue,features:{mouthGap:gap,cheekFullness:fullness,lowerFaceRatio:lower,tongueCoverage:coverage}};
  },
  region(action){return action.startsWith('brow')?'brows':action.startsWith('eyeLook')?'gaze':action.startsWith('eye')?'eyes':/^(cheek|nose)/.test(action)?'cheeks':'mouth';},
  pairedDetail(name,original,mirrored){
    const value=Math.min(original,mirrored),agreement=1-Math.abs(original-mirrored);
    // Puff geometry saturates differently after mirroring. Strong evidence in
    // BOTH views still supports the weaker amount; a single strong view cannot.
    const accepted=name==='cheekPuff'?value>.35||value>.2&&agreement>.65:name==='tongueOut'?value>.3&&agreement>.7:agreement>.7;
    return {value,agreement,accepted};
  },
  unflip(actions){return Object.fromEntries(Object.entries(actions).map(([name,value])=>[name.endsWith('Left')?name.slice(0,-4)+'Right':name.endsWith('Right')?name.slice(0,-5)+'Left':name==='jawLeft'?'jawRight':name==='jawRight'?'jawLeft':name==='mouthLeft'?'mouthRight':name==='mouthRight'?'mouthLeft':name,value]));},
  disagreement(original,flipped){const groups={};for(const [action,value] of Object.entries(original)){const region=this.region(action);(groups[region]??=[]).push(Math.abs(value-(flipped[action]??value)));}return Object.fromEntries(Object.entries(groups).map(([name,values])=>[name,values.reduce((a,b)=>a+b,0)/values.length]));},
  selected(faces,size){const sorted=faces.map(face=>({face,distance:Math.hypot((face.box[0]+face.box[2])/2-size/2,(face.box[1]+face.box[3])/2-size/2)/size})).sort((a,b)=>a.distance-b.distance);if(!sorted.length||sorted[0].distance>.25||sorted.length>1&&sorted[1].distance-sorted[0].distance<.035)throw Error('The selected face overlaps another face ambiguously. Use a closer reference that separates them.');return sorted[0].face;}
};
