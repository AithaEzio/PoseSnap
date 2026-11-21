/** Format monotonic elapsed time without rounding 59.95 seconds to “60 seconds”. */
export function formatElapsed(milliseconds:number):string {
  if(!Number.isFinite(milliseconds)||milliseconds<0)throw new RangeError('Elapsed time must be finite and nonnegative.');
  const seconds=Math.round(milliseconds/100)/10;
  if(seconds<60)return seconds.toFixed(1)+(seconds===1?' second':' seconds');
  const total=Math.round(seconds),minutes=Math.floor(total/60),remainder=total%60;
  return minutes+(minutes===1?' minute':' minutes')+(remainder?' '+remainder+(remainder===1?' second':' seconds'):'');
}
