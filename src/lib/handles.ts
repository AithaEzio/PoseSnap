export interface HandlePoint {id:string;label:string;x:number;y:number;anchorX:number;anchorY:number}
export function handleGlyph(label:string){
  const name=label.replace(/^(Left|Right) /,''),finger=name.match(/^(Thumb|Index|Middle|Ring|Pinky) ([123])$/);
  if(finger)return finger[1][0]+finger[2];
  const side=label.startsWith('Left ')?'L':label.startsWith('Right ')?'R':'';
  return side+(name==='Hand'?'H':name==='Elbow'?'E':name==='Knee'?'K':name==='Foot'?'F':name.startsWith('Shoulder')?'S':name[0]);
}
/** Spread overlapping screen handles without changing the anatomical pivots. */
export function separateHandles(points:HandlePoint[],width:number,height:number){
  const result=points.map(p=>({...p}));
  for(let iteration=0;iteration<20;iteration++){
    let moved=false;
    for(let i=0;i<result.length;i++)for(let j=i+1;j<result.length;j++){
      const a=result[i],b=result[j];let dx=b.x-a.x,dy=b.y-a.y,distance=Math.hypot(dx,dy);
      if(distance>=32)continue;
      if(distance<.01){const angle=(i+j*.618)*2.399;dx=Math.cos(angle);dy=Math.sin(angle);distance=1;}
      const offset=(32-distance)/2+.05;a.x-=dx/distance*offset;a.y-=dy/distance*offset;b.x+=dx/distance*offset;b.y+=dy/distance*offset;moved=true;
    }
    for(const point of result){point.x=Math.max(17,Math.min(width-17,point.x));point.y=Math.max(17,Math.min(height-17,point.y));}
    if(!moved)break;
  }
  return result;
}
