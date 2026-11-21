/** Optional staged normal-only repair for the inherited 40-way tongue pole.
 * Apply after computeVertexNormals, only while the coupled tongue is extended.
 * Positions, topology, expression values and the posterior pole are untouched.
 */
export function smoothExtendedTongueTip(normals,positions,amount){
  if(amount<=0)return false;
  if(normals.length!==1320*3||positions.length!==normals.length)throw Error('Tongue pole topology mismatch.');
  const start=32*40*3;let x=0,y=0,z=0;
  for(let at=start;at<normals.length;at+=3){
    if(Math.abs(positions[at]-positions[start])>1e-7||Math.abs(positions[at+1]-positions[start+1])>1e-7||Math.abs(positions[at+2]-positions[start+2])>1e-7)throw Error('Tongue tip is not a coincident pole.');
    x+=normals[at];y+=normals[at+1];z+=normals[at+2];
  }
  const length=Math.hypot(x,y,z);if(length<1e-8)return false;
  for(let at=start;at<normals.length;at+=3){normals[at]=x/length;normals[at+1]=y/length;normals[at+2]=z/length;}
  return true;
}
