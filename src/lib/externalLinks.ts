/** Keep HTTPS links out of the desktop's private application WebView. */
export async function handleExternalLink(event:MouseEvent,desktop:boolean,open:(url:string)=>Promise<unknown>,onerror:(error:unknown)=>void){
  if(!desktop||event.defaultPrevented||event.button>1)return;
  const target=event.target as Element|null;
  const anchor=target?.closest?.('a[href]') as HTMLAnchorElement|null;
  if(!anchor||anchor.hasAttribute('download'))return;
  let url:URL;
  try{url=new URL(anchor.href);}catch{return;}
  if(url.protocol!=='https:')return;
  event.preventDefault();
  try{await open(url.href);}catch(error){onerror(error);}
}
