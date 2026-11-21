import { afterEach,describe,expect,it,vi } from 'vitest';
import { waitForDaz } from './handoff';
afterEach(()=>vi.useRealTimers());
describe('DAZ task deadline',()=>{
  it('returns an acknowledgment without later cancelling another job',async()=>{
    vi.useFakeTimers();const cancel=vi.fn(async()=>{});
    await expect(waitForDaz(Promise.resolve({zeroed:3}),cancel)).resolves.toEqual({zeroed:3});
    await vi.advanceTimersByTimeAsync(80_000);expect(cancel).not.toHaveBeenCalled();
  });
  it('propagates errors and removes the watchdog',async()=>{
    vi.useFakeTimers();const cancel=vi.fn(async()=>{});
    await expect(waitForDaz(Promise.reject(Error('DAZ closed')),cancel)).rejects.toThrow('DAZ closed');
    await vi.advanceTimersByTimeAsync(80_000);expect(cancel).not.toHaveBeenCalled();
  });
  it('releases a stalled task even when cancellation also fails',async()=>{
    vi.useFakeTimers();const cancel=vi.fn(async()=>{throw Error('Bridge stopped');});
    const result=waitForDaz(new Promise(()=>{}),cancel);const failure=expect(result).rejects.toThrow('PoseSnap stopped waiting');
    await vi.advanceTimersByTimeAsync(70_000);await failure;expect(cancel).toHaveBeenCalledOnce();
  });
  it('ignores a late acknowledgment after the deadline',async()=>{
    vi.useFakeTimers();let finish!:(value:number)=>void;const cancel=vi.fn(async()=>{});
    const result=waitForDaz(new Promise<number>(resolve=>finish=resolve),cancel);const failure=expect(result).rejects.toThrow('DAZ did not finish');
    await vi.advanceTimersByTimeAsync(70_000);await failure;finish(2);await vi.runAllTimersAsync();expect(cancel).toHaveBeenCalledOnce();
  });
});
