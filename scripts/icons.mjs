import sharp from 'sharp';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
await mkdir('src-tauri/icons', {recursive:true});
const svg=await readFile('public/logo.svg');
const sizes=[16,32,48,64,128,256]; const pngs=[];
for(const size of sizes){const png=await sharp(svg).resize(size).png().toBuffer(); pngs.push(png);await writeFile(`src-tauri/icons/${size}.png`,png);}
const header=Buffer.alloc(6+sizes.length*16);header.writeUInt16LE(1,2);header.writeUInt16LE(sizes.length,4);let offset=header.length;
sizes.forEach((size,i)=>{const n=6+i*16;header[n]=header[n+1]=size===256?0:size;header.writeUInt16LE(1,n+4);header.writeUInt16LE(32,n+6);header.writeUInt32LE(pngs[i].length,n+8);header.writeUInt32LE(offset,n+12);offset+=pngs[i].length;});
await writeFile('src-tauri/icons/icon.ico',Buffer.concat([header,...pngs]));
