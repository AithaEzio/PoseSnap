import {describe,it,expect,vi} from 'vitest';
import {handleExternalLink} from './externalLinks';
function click(url:string,extra:Record<string,unknown>={}){
  return {button:0,defaultPrevented:false,preventDefault:vi.fn(),target:{closest:()=>({href:url,hasAttribute:()=>false})},...extra} as unknown as MouseEvent;
}
describe('external pages in the private WebView',()=>{
  it('opens nested source/credit links using the native default-browser bridge, including middle clicks',async()=>{
    for(const button of [0,1]){
      const event=click('https://huggingface.co/meghshukla/clue',{button}),open=vi.fn().mockResolvedValue(undefined);
      await handleExternalLink(event,true,open,vi.fn());
      expect(event.preventDefault).toHaveBeenCalledOnce();expect(open).toHaveBeenCalledWith('https://huggingface.co/meghshukla/clue');
    }
  });
  it('retains normal browser navigation and ignores unrelated, cancelled and local links',async()=>{
    for(const [event,desktop] of [[click('https://github.com'),false],[click('https://github.com',{defaultPrevented:true}),true],[click('https://github.com',{button:2}),true],[click('file:///C:/test.exe'),true],[click('https://github.com',{target:null}),true]] as const){
      const open=vi.fn();await handleExternalLink(event,desktop,open,vi.fn());
      expect(open).not.toHaveBeenCalled();expect(event.preventDefault).not.toHaveBeenCalled();
    }
  });
  it('reports launch errors without navigating away from the application',async()=>{
    const event=click('https://github.com/facebookresearch/sam-3d-body'),failure=new Error('No browser configured'),onerror=vi.fn();
    await handleExternalLink(event,true,vi.fn().mockRejectedValue(failure),onerror);
    expect(event.preventDefault).toHaveBeenCalledOnce();expect(onerror).toHaveBeenCalledWith(failure);
  });
});
