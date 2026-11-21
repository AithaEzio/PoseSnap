import {describe,it,expect,vi} from 'vitest';
import {PreviewFrames} from './previewFrames';
function fixture(){let id=0;const queue=new Map<number,FrameRequestCallback>(),frame=vi.fn(()=>false),cancel=vi.fn((id:number)=>queue.delete(id));const scheduler=new PreviewFrames(frame,fn=>{queue.set(++id,fn);return id;},cancel);const run=()=>{const next=queue.entries().next().value!;queue.delete(next[0]);next[1](0);};return {scheduler,queue,frame,cancel,run};}
describe('warm preview scheduling',()=>{
  it('coalesces redraws and sleeps after a settled frame',()=>{const f=fixture();f.scheduler.setActive(true);f.scheduler.invalidate();f.scheduler.invalidate();expect(f.queue.size).toBe(1);f.run();expect(f.frame).toHaveBeenCalledTimes(1);expect(f.queue.size).toBe(0);f.scheduler.invalidate();expect(f.queue.size).toBe(1);});
  it('continues orbit damping until it settles',()=>{const f=fixture();f.frame.mockReturnValueOnce(true).mockReturnValueOnce(true).mockReturnValue(false);f.scheduler.setActive(true);f.run();f.run();f.run();expect(f.frame).toHaveBeenCalledTimes(3);expect(f.queue.size).toBe(0);});
  it('pauses hidden previews without losing redraws on return',()=>{const f=fixture();f.scheduler.setActive(true);f.scheduler.setActive(false);f.scheduler.invalidate();expect(f.queue.size).toBe(0);f.scheduler.setActive(true);f.run();expect(f.frame).toHaveBeenCalledTimes(1);});
  it('keeps invalidations made during a frame and ignores work after disposal',()=>{const f=fixture();f.frame.mockImplementationOnce(()=>{f.scheduler.invalidate();return false;});f.scheduler.setActive(true);f.run();expect(f.queue.size).toBe(1);f.scheduler.dispose();f.scheduler.setActive(true);f.scheduler.invalidate();expect(f.queue.size).toBe(0);});
});
