import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { readFile, realpath } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { resolve } from 'node:path';
import { gunzipSync } from 'node:zlib';
import { fixtureDownloads } from './scripts/engine-fixture';
const expressionPreview={name:'local-expression-assets',configureServer(server:import('vite').ViteDevServer){server.middlewares.use('/__expression-assets',async(req,res)=>{
  const route=(req.url??'').split('?')[0].replace(/^\//,'');
  const wasm=/^wasm\/vision_wasm_(?:module_)?(?:nosimd_)?internal\.(js|wasm)$/.test(route);
  const image=/^image\/[a-f0-9]{24}$/.test(route);
  let path=route==='model'?'models/expression/face_landmarker.task':route==='vision_bundle.js'||wasm?'runtime/vision/'+route:image?'data/history/'+route.slice(6)+'/source.png':route==='test-portrait'?'temp/expression-validation/portrait.jpg':null;
  if(!path||!['GET','HEAD'].includes(req.method??'')){res.statusCode=404;res.end();return;}
  try{const root=await realpath('.'),file=await realpath(path);if(!file.startsWith(root+'\\')&&!file.startsWith(root+'/'))throw Error();const bytes=await readFile(file);if(bytes.length>160_000_000)throw Error();res.setHeader('Content-Type',route.endsWith('.wasm')?'application/wasm':route.endsWith('.js')?'text/javascript':image?'image/png':route==='test-portrait'?'image/jpeg':'application/octet-stream');res.setHeader('Cache-Control','no-store');res.end(req.method==='HEAD'?undefined:bytes);}catch{res.statusCode=404;res.end('Expression asset is missing.');}
});}};
const enginePreview={name:'engine-validation-preview',configureServer(server:import('vite').ViteDevServer){server.middlewares.use('/__engine-validation',async(req,res)=>{
  try{
    const catalogue=JSON.parse(gunzipSync(await readFile('src-tauri/engine-catalogue.json.gz')).toString());
    const missing=new URL(req.url??'','http://local').searchParams.has('missing');
    const components=catalogue.components.map((c:{id:string;label:string;version:string;required:boolean;roots:string[];files:{size:number}[];artifacts:{size:number;urls:string[];parts?:{urls:string[]}[]}[];source:string|null;note:string})=>({id:c.id,label:c.label,version:c.version,required:c.required,state:missing&&['python','hands','interaction-detector','clue-body'].includes(c.id)?'missing':'installed',locations:c.roots.map(p=>resolve(p)),relativeLocations:c.roots,installedBytes:c.files.reduce((s,f)=>s+f.size,0),downloadBytes:c.artifacts.length?c.artifacts.reduce((s,a)=>s+a.size,0):null,source:c.source,...fixtureDownloads(c.artifacts),message:c.note}));
    res.setHeader('Content-Type','application/json');res.end(JSON.stringify({version:1,root:resolve('.'),phase:missing?'attention':'ready',ready:!missing,runtimeReady:!missing,active:false,message:missing?'Development fixture: install or import missing components':'Development fixture: engine ready',components,transfers:[],gpu:missing?null:'Development fixture GPU'}));
  }catch{res.statusCode=404;res.end();}
});}};
const studioPreview={name:'read-only-studio-preview',configureServer(server:import('vite').ViteDevServer){server.middlewares.use('/__studio-convert',(req,res)=>{if(req.method!=='POST'){res.statusCode=405;res.end();return;}let body='';req.on('data',chunk=>{body+=chunk;if(body.length>2_000_000)req.destroy();});req.on('end',()=>{let payload;try{payload=JSON.parse(body);if(!['g8f','g8m','g9'].includes(payload.rigId)||!payload.pose||!payload.baseline)throw Error();}catch{res.statusCode=400;res.end();return;}const child=spawn(resolve('runtime/python/python.exe'),['-I',resolve('scripts/dev-studio.py')],{cwd:process.cwd(),windowsHide:true,env:{...process.env,TEMP:resolve('temp'),TMP:resolve('temp'),PYTHONNOUSERSITE:'1'}});let output='',errors='';const timeout=setTimeout(()=>child.kill(),30000);child.stdout.on('data',chunk=>output+=chunk);child.stderr.on('data',chunk=>errors+=chunk);child.on('error',()=>{clearTimeout(timeout);res.statusCode=503;res.end(JSON.stringify({error:'Private Python is unavailable.'}));});child.on('close',code=>{clearTimeout(timeout);if(res.writableEnded)return;res.setHeader('Content-Type','application/json');res.statusCode=code===0?200:422;res.end(code===0?output:JSON.stringify({error:errors.slice(-1500)||'Conversion did not finish.'}));});child.stdin.end(JSON.stringify(payload));});});}};
const textChoicesPreview={name:'read-only-text-choices',configureServer(server:import('vite').ViteDevServer){server.middlewares.use('/__text-choices',async(req,res)=>{
  if(!['GET','HEAD'].includes(req.method??'')){res.statusCode=405;res.end();return;}
  const params=new URL(req.url??'','http://local').searchParams;const output=params.get('output')??'pose';const kimodo=params.get('generator')==='kimodo';const sample=params.get('sample')??'dance-1';const validSample=/^(relaxed|confident|happy|dance|walking|jump)-[0-3]$/.test(sample);const file=kimodo&&output==='pose'?(sample==='kimodo-only'?'temp/text-choice-fixes-20261025/create.json':validSample?`.tools/kimodo/qualification/${sample}-pose-g8f-result.json`:undefined):undefined;
  if(kimodo&&output==='pose'&&/^complete-[a-z0-9_-]+$/.test(sample)){
    try{
      const id=sample.slice(9),contacts=['front_hug','side_hug','handhold','shoulder'].includes(id);
      const file=contacts?'contact-replay-final-v6.json':id.startsWith('lying-')?'results-lying-final-v7.json':id.startsWith('crawl-')?'results-crawl-cached-v6.json':id.startsWith('inverted-')?'results-inverted-cached-v6.json':'results-cached-v4.json';
      const report=JSON.parse(await readFile('.tools/kimodo/complete-integration/'+file,'utf8'));
      const row=report.cases.find((c:{id:string;success:boolean;result?:{output:string}})=>c.id===id&&c.success&&c.result?.output===output);
      if(!row)throw Error();const bytes=JSON.stringify(row.result);if(bytes.length>2_000_000)throw Error();res.setHeader('Content-Type','application/json');res.setHeader('Cache-Control','no-store');res.end(req.method==='HEAD'?undefined:bytes);
    }catch{res.statusCode=404;res.end('No checked complete-integration fixture matches this selection.');}return;
  }
  if(!file){res.statusCode=404;res.end();return;}
  try{const bytes=await readFile(file);if(bytes.length>2_000_000)throw Error('Fixture too large');res.setHeader('Content-Type','application/json');res.setHeader('Cache-Control','no-store');res.end(req.method==='HEAD'?undefined:bytes);}catch{res.statusCode=404;res.end('Generate the isolated text-choice fixture first.');}
});}};
export default defineConfig({plugins:[svelte(),expressionPreview,studioPreview,enginePreview,textChoicesPreview,{name:'local-validation-fixture',configureServer(server){server.middlewares.use('/__validation',async(req,res)=>{try{const fixture=JSON.parse(await readFile(new URL(req.url??'', 'http://local').searchParams.has('dancing')?'.tools/dancing-ui-fixture.json':'.tools/ui-fixture.json','utf8'));if(new URL(req.url??'', 'http://local').searchParams.get('refinement')==='1'){fixture.interaction=JSON.parse(await readFile('temp/refinement-smoke.json','utf8'));fixture.pose=fixture.interaction.poses[0];}if(new URL(req.url??'', 'http://local').searchParams.get('posture')==='1'){fixture.interaction=JSON.parse(await readFile('temp/automatic-refine-smoke.json','utf8'));fixture.pose=fixture.interaction.poses[0];fixture.preview=JSON.parse(await readFile('temp/posture-worker-smoke.json','utf8'));}const params=new URL(req.url??'', 'http://local').searchParams;
if(params.has('pure')){
  if(params.has('dancing')){fixture.pose=JSON.parse(await readFile('temp/pure-validation/dancing/person-1-g8f.json','utf8'));delete fixture.interaction;}
  else{fixture.interaction=JSON.parse(await readFile('temp/pure-validation/hug/interaction-pure.json','utf8'));fixture.pose=fixture.interaction.poses[0];}
}
if(params.has('targetFit')&&params.has('dancing')){fixture.pose=JSON.parse(await readFile('temp/target-fit-validation/dancing-g8f.json','utf8')).poses[0];delete fixture.interaction;}
const rigs=await Promise.all(['g8f','g8m','g9'].map(async id=>{try{return [id,JSON.parse(await readFile('data/rigs/'+id+'.json','utf8'))] as const;}catch{return null;}}));fixture.rigs=Object.fromEntries(rigs.filter(value=>value!==null));res.setHeader('Content-Type','application/json');res.end(JSON.stringify(fixture));}catch{res.statusCode=404;res.end();}});}}],clearScreen:false,server:{port:1420,strictPort:true,watch:{ignored:['**/backups/**','**/data/**','**/runtime/**','**/models/**','**/vendor/**','**/.tools/**','**/.downloads/**','**/release/**','**/temp/**','**/logs/**','**/src-tauri/target/**','**/*.blend','**/*.blend[0-9]','**/*.fbx','**/assets/mannequin/source/**']}},build:{target:'es2022'}});

