/** Staged preview-only tongue clearance; consumes already coupled actions.
 * Float32 position arrays are compatible with Three.BufferAttribute. This
 * module has no Three/Blender dependency and never changes expression values.
 * Call after all surface morphs, before normals/bounds are recomputed.
 */
export const ORAL_CLEARANCE_ASSET = '0f423ec4f1de19e529aa469c31aa0a00f0527cf882a2c7e264ad48df29a2a2f6';
const smooth=(a,b,v)=>{const t=Math.max(0,Math.min(1,(v-a)/(b-a)));return t*t*(3-2*t);};
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));

/** An exact vertical ray against projected triangles, indexed into a bounded
 * 32x32 grid. It has fixed spatial storage and no persistent posed buffers.
 */
function verticalEnvelope(surfaces, selectors, points) {
  const size=32,cellCount=size*size,cells=Array.from({length:cellCount},()=>[]),faces=[];
  let minX=Infinity,maxX=-Infinity,minZ=Infinity,maxZ=-Infinity;
  for(let i=0;i<points.length;i+=3){minX=Math.min(minX,points[i]);maxX=Math.max(maxX,points[i]);minZ=Math.min(minZ,points[i+2]);maxZ=Math.max(maxZ,points[i+2]);}
  minX-=.00001;maxX+=.00001;minZ-=.00301;maxZ+=.00301;
  const sx=size/(maxX-minX),sz=size/(maxZ-minZ),cellX=v=>clamp(Math.floor((v-minX)*sx),0,size-1),cellZ=v=>clamp(Math.floor((v-minZ)*sz),0,size-1);
  for(const [name,triangles] of selectors){
    const p=surfaces.get(name);
    for(let i=0;i<triangles.length;i+=3){
      const a=triangles[i]*3,b=triangles[i+1]*3,c=triangles[i+2]*3;
      const ax=p[a],az=p[a+2],ux=p[b]-ax,uz=p[b+2]-az,vx=p[c]-ax,vz=p[c+2]-az;
      const det=ux*vz-uz*vx;if(Math.abs(det)<1e-16)continue;
      const bx=Math.min(ax,p[b],p[c]),ex=Math.max(ax,p[b],p[c]),bz=Math.min(az,p[b+2],p[c+2]),ez=Math.max(az,p[b+2],p[c+2]);
      if(ex<minX||bx>maxX||ez<minZ||bz>maxZ)continue;
      const at=faces.length;faces.push([ax,az,ux,uz,vx,vz,1/det,p[a+1],p[b+1]-p[a+1],p[c+1]-p[a+1]]);
      for(let z=cellZ(bz);z<=cellZ(ez);z++)for(let x=cellX(bx);x<=cellX(ex);x++)cells[z*size+x].push(at);
    }
  }
  return (x,z,up)=>{
    let nearest=up?.1:-.2,found=false;
    if(x<minX||x>maxX||z<minZ||z>maxZ)return null;
    for(const at of cells[cellZ(z)*size+cellX(x)]){
      const [ax,az,ux,uz,vx,vz,inv,ay,uy,vy]=faces[at],dx=x-ax,dz=z-az;
      const u=(dx*vz-dz*vx)*inv,v=(ux*dz-uz*dx)*inv;
      if(u< -1e-8||v< -1e-8||u+v>1+1e-8)continue;
      const y=ay+u*uy+v*vy;
      if(up?(y>=-.2&&y<=.1&&(!found||y<nearest)):(y<=.05&&y>=-.25&&(!found||y>nearest))){nearest=y;found=true;}
    }
    return found?nearest:null;
  };
}

/** Mesh inputs: {name, positions: Float32Array, index: Uint16/32Array}.
 * Attachment uses the existing manifest oralAttachments[0] arrays. The asset
 * signature/topology guard deliberately rejects a different derived face.
 */
export function createOralClearance(meshes,attachment,assetSha256){
  if(assetSha256!==ORAL_CLEARANCE_ASSET)throw Error('Oral clearance needs its reviewed face asset.');
  const rest=new Map(meshes.map(m=>[m.name,m.positions])),indices=new Map(meshes.map(m=>[m.name,m.index]));
  const lining=rest.get('InnerLips'),skin=rest.get('Skin'),tongue=rest.get('Tongue');
  if(!lining||lining.length!==582*3||!skin||!tongue||tongue.length!==33*40*3||attachment?.mesh!=='InnerLips'||attachment.surface!=='Skin'||attachment.vertices?.length!==194||attachment.indices?.length!==194)throw Error('Oral clearance topology mismatch.');
  const upper=new Uint8Array(582),depth=new Uint8Array(582),upperDeep=[];
  for(let i=0;i<582;i++){
    let chosen=-1,best=Infinity;
    for(let j=0;j<194;j++){
      const rim=attachment.vertices[j],dx=Math.abs(lining[rim*3]-lining[i*3]),dz=lining[rim*3+2]-lining[i*3+2],step=Math.round(dz/.00336);
      if(dx>=1e-7||step<0||step>2)continue;
      const score=dx*100+Math.abs(Math.abs(dz)/.00336-Math.round(Math.abs(dz)/.00336))*.01;
      if(score<best){chosen=j;best=score;}
    }
    if(chosen<0)throw Error('Oral clearance lining rows are invalid.');
    const rim=attachment.vertices[chosen];depth[i]=Math.round((lining[rim*3+2]-lining[i*3+2])/.00336);
    upper[i]=+(lining[rim*3+1]>skin[attachment.indices[chosen]*3+1]);
    if(upper[i]&&depth[i]>0)upperDeep.push(i);
  }
  if(upperDeep.length!==196||attachment.vertices.some(i=>depth[i]!==0))throw Error('Oral clearance anchors are invalid.');
  const selectors=[[],[]];
  for(const name of ['Skin','InnerLips','UpperTeeth','LowerTeeth']){
    const p=rest.get(name),tri=indices.get(name);if(!p||!tri)throw Error('Oral clearance surface is missing.');
    const groups=[[],[]];
    for(let i=0;i<tri.length;i+=3){
      const a=tri[i],b=tri[i+1],c=tri[i+2];let isUpper;
      if(name==='Skin'){
        const x=(p[a*3]+p[b*3]+p[c*3])/3,y=(p[a*3+1]+p[b*3+1]+p[c*3+1])/3,z=(p[a*3+2]+p[b*3+2]+p[c*3+2])/3;
        if(Math.abs(x)>=.046||y<=-.11||y>=-.037||z<=.06)continue;
        const u=clamp(x/.105,-.282,.282),crease=(-1.09+.024*Math.sin(Math.PI*u/.30)**2-.020*(u/.282)**4+.45)*.105;
        isUpper=y>=crease;
      }else isUpper=name==='InnerLips'?upper[a]+upper[b]+upper[c]>=2:name==='UpperTeeth';
      groups[isUpper?0:1].push(a,b,c);
    }
    groups.forEach((triangles,i)=>{if(triangles.length)selectors[i].push([name,triangles]);});
  }
  const ringZ=Array.from({length:33},(_,row)=>{let z=0;for(let i=0;i<40;i++)z+=tongue[(row*40+i)*3+2];return z/40;});
  return {
    upperDeepVertices:upperDeep.length,outerAnchorCount:194,
    correct(surfaces,actions){
      if(!Object.values(actions).some(v=>v>0))return {lining:false,tongue:false};
      // Check every required buffer before touching a buffer. Posed arrays are
      // owned by the caller; no frame is retained by this adapter.
      for(const [name,p] of rest){const q=surfaces.get(name);if(!q||q.length!==p.length)throw Error('Oral clearance posed topology mismatch.');}
      const amount=actions.tongueOut??0;if(amount<=0)return {lining:false,tongue:false};
      const output=surfaces.get('Tongue'),initial=Float64Array.from(output),jaw=actions.jawOpen??0;
      for(let row=3;row<33;row++){
        const width=1-(1-jaw)*.55*smooth(3/32,.42,row/32)*smooth(0,.2,amount);
        for(let i=0;i<40;i++)initial[(row*40+i)*3]*=width;
      }
      const centers=new Float64Array(33),heights=new Float64Array(33),normalized=new Float64Array(1320);
      for(let row=0;row<33;row++){
        for(let i=0;i<40;i++)centers[row]+=initial[(row*40+i)*3+1]/40;
        for(let i=0;i<40;i++)heights[row]=Math.max(heights[row],Math.abs(initial[(row*40+i)*3+1]-centers[row]));
        for(let i=0;i<40;i++)normalized[row*40+i]=(initial[(row*40+i)*3+1]-centers[row])/Math.max(heights[row],1e-8);
      }
      const upperRay=verticalEnvelope(surfaces,selectors[0],initial),lowerRay=verticalEnvelope(surfaces,selectors[1],initial),constraints=[];
      let targetCenters=centers.slice();const targetHeights=heights.slice();
      for(let row=3;row<33;row++){
        const lower=new Float64Array(40),higher=new Float64Array(40);
        for(let i=0;i<40;i++){
          const at=(row*40+i)*3,x=initial[at],z=initial[at+2];let top=Infinity,bottom=-Infinity;
          for(const dz of [-.003,-.0015,0,.0015,.003]){const u=upperRay(x,z+dz,true),l=lowerRay(x,z+dz,false);if(u!==null)top=Math.min(top,u-.0006);if(l!==null)bottom=Math.max(bottom,l+.0006);}
          lower[i]=bottom===-Infinity?-.2:bottom;higher[i]=top===Infinity?.1:top;
        }
        const feasible=height=>{let lo=-Infinity,hi=Infinity;for(let i=0;i<40;i++){const s=normalized[row*40+i]*height;lo=Math.max(lo,lower[i]-s);hi=Math.min(hi,higher[i]-s);}return [lo,hi];};
        const zero=feasible(0);if(zero[0]>zero[1])continue;
        let l=0,h=heights[row];for(let j=0;j<22;j++){const mid=(l+h)/2,[lo,hi]=feasible(mid);if(lo<=hi)l=mid;else h=mid;}
        const height=l*.97,[lo,hi]=feasible(height);targetCenters[row]=clamp(centers[row],lo,hi);targetHeights[row]=height;
        constraints.push({row,lower,higher,feasible});
      }
      for(let pass=0;pass<24;pass++){
        const next=targetCenters.slice();for(const {row,feasible} of constraints){if(row>=32)continue;const [lo,hi]=feasible(targetHeights[row]),wanted=.65*targetCenters[row]+.35*(targetCenters[row-1]+targetCenters[row+1])/2;next[row]=clamp(wanted,lo,hi);}targetCenters=next;
      }
      // The first 120 posterior vertices remain exactly inherited, including
      // their jaw motion. Width/path correction does not shorten the Z path.
      output.set(initial);
      for(const {row} of constraints){
        const weight=smooth(.03675,.052,ringZ[row])*smooth(0,.2,amount);
        for(let i=0;i<40;i++){const at=(row*40+i)*3,next=targetCenters[row]+normalized[row*40+i]*targetHeights[row];output[at+1]=initial[at+1]*(1-weight)+next*weight;}
      }
      return {lining:false,tongue:true};
    }
  };
}
