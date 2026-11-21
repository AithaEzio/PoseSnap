import {beforeEach,afterEach,describe,it,expect,vi} from 'vitest';
const native=vi.hoisted(()=>({desktop:true,invoke:vi.fn()}));
vi.mock('./api',()=>({get desktop(){return native.desktop;}}));
vi.mock('@tauri-apps/api/core',()=>({invoke:native.invoke}));
import {closingSeconds,idleForReminder,creatorLinks,recordCreation,supportEvent} from './support';
import {handleExternalLink} from './externalLinks';

describe('optional local support reminders',()=>{
  beforeEach(()=>{native.desktop=true;native.invoke.mockReset();native.invoke.mockResolvedValue({disabled:false,pending:null,waitMs:0,claim:null});vi.useFakeTimers();});
  afterEach(()=>vi.useRealTimers());
  it('does not extend a five-second deadline when the tab was backgrounded',()=>{
    expect(closingSeconds(5000,0)).toBe(5);expect(closingSeconds(5000,1)).toBe(5);
    expect(closingSeconds(5000,4999)).toBe(1);expect(closingSeconds(5000,5000)).toBe(0);expect(closingSeconds(5000,60000)).toBe(0);
  });
  it('waits for five seconds of visible, safe idle time',()=>{
    expect(idleForReminder(1000,5999,false,true)).toBe(false);
    expect(idleForReminder(1000,6000,false,true)).toBe(true);
    expect(idleForReminder(1000,9000,true,true)).toBe(false);
    expect(idleForReminder(1000,9000,false,false)).toBe(false);
  });
  it('deduplicates retryable completions using the same operation identity',async()=>{
    native.invoke.mockRejectedValueOnce(Error('File sharing lock')).mockResolvedValue({});
    recordCreation('operation-1234',2);await vi.runAllTimersAsync();
    expect(native.invoke).toHaveBeenCalledTimes(2);
    for(const call of native.invoke.mock.calls)expect(call).toEqual(['support_event',{event:{kind:'creation',operationId:'operation-1234',actors:2}}]);
  });
  it('suppresses service failures after bounded retries without rejecting normal creation',async()=>{
    native.invoke.mockRejectedValue(Error('Unreadable storage'));
    expect(recordCreation('operation-1234')).toBeUndefined();await vi.runAllTimersAsync();expect(native.invoke).toHaveBeenCalledTimes(3);
  });
  it('browser validation never changes native counters',async()=>{
    native.desktop=false;recordCreation('operation-1234',4);await vi.runAllTimersAsync();
    await expect(supportEvent({kind:'workspace'})).rejects.toThrow('desktop-only');expect(native.invoke).not.toHaveBeenCalled();
  });
  it('routes both creator destinations through the existing external-browser bridge',async()=>{
    const open=vi.fn().mockResolvedValue(undefined);
    for(const href of Object.values(creatorLinks)){
      const preventDefault=vi.fn(),event={button:0,defaultPrevented:false,preventDefault,target:{closest:()=>({href,hasAttribute:()=>false})}} as unknown as MouseEvent;
      await handleExternalLink(event,true,open,vi.fn());expect(preventDefault).toHaveBeenCalledOnce();expect(open).toHaveBeenLastCalledWith(href);
    }
    expect(creatorLinks.kofi).toBe('https://ko-fi.com/aithaezio');expect(creatorLinks.github).toBe('https://github.com/AithaEzio?tab=repositories');
  });
});
