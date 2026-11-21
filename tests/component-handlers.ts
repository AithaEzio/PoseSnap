import {readFileSync} from 'node:fs';
import {parse} from 'svelte/compiler';
import {transpileModule,ScriptTarget} from 'typescript';

/** Exercise actual component transactions without an inference engine or a user scene. */
export function componentHandler(file:string,name:string,ctx:Record<string,unknown>){
  const source=readFileSync(file,'utf8'),ast=parse(source) as any;
  const node=ast.instance.content.body.map((n:any)=>n.type==='ExportNamedDeclaration'?n.declaration:n).find((n:any)=>n?.type==='FunctionDeclaration'&&n.id.name===name);
  if(!node)throw Error('Missing component handler '+name);
  // Match Vite's production constant when executing a handler outside an ESM module.
  const code=transpileModule(source.slice(node.start,node.end).replaceAll('import.meta.env.DEV','false'),{compilerOptions:{target:ScriptTarget.ES2022}}).outputText;
  return (...args:unknown[])=>new Function('ctx','args',`with(ctx){${code};return ${name}(...args);}`)(ctx,args);
}
