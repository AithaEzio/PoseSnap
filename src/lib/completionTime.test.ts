import {describe,it,expect} from 'vitest';
import {formatElapsed} from './completionTime';
describe('extraction completion time',()=>{
  it('shows sub-second and ordinary extraction times to a tenth of a second',()=>{
    expect(formatElapsed(0)).toBe('0.0 seconds');expect(formatElapsed(346)).toBe('0.3 seconds');
    expect(formatElapsed(1000)).toBe('1.0 second');expect(formatElapsed(12456)).toBe('12.5 seconds');
  });
  it('uses readable minutes for long operations and handles the rollover',()=>{
    expect(formatElapsed(59940)).toBe('59.9 seconds');expect(formatElapsed(59999)).toBe('1 minute');
    expect(formatElapsed(61000)).toBe('1 minute 1 second');expect(formatElapsed(125000)).toBe('2 minutes 5 seconds');
  });
  it('rejects invalid clock readings instead of displaying a fabricated time',()=>{
    for(const value of [-1,NaN,Infinity])expect(()=>formatElapsed(value)).toThrow(RangeError);
  });
});
