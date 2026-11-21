import { describe,it,expect } from 'vitest';
import { PreviewCameraCommands } from './previewCamera';
import type { ReferenceCamera } from './types';

const reference:ReferenceCamera={version:1,imageSize:[1200,800],originCm:[0,0,300],intrinsics:[[900,0,600],[0,900,400],[0,0,1]]};
describe('preview camera commands',()=>{
  it('retains an orbited view across pose clones, selection, rig conversion and panel redraws',()=>{
    const commands=new PreviewCameraCommands(),command={view:'side',reset:1,scene:'photo',reference};
    expect(commands.accept(command)).toBe(true);
    for(let i=0;i<5;i++)expect(commands.accept({...command,reference:structuredClone(reference)})).toBe(false);
    expect(commands.accept({...command,reference:{...reference,originCm:[2,3,300]}})).toBe(false);
  });
  it('allows returning to the same preset explicitly and framing a new scene',()=>{
    const commands=new PreviewCameraCommands(),command={view:'front',reset:0,scene:'photo'};
    expect(commands.accept(command)).toBe(true);
    expect(commands.accept({...command,reset:1})).toBe(true);
    expect(commands.accept({...command,reset:1,view:'back'})).toBe(true);
    expect(commands.accept({...command,reset:1,view:'back',scene:'new-photo'})).toBe(true);
  });
  it('updates a calibrated reference projection only when its values change',()=>{
    const commands=new PreviewCameraCommands(),command={view:'reference',reset:0,scene:'photo',reference};
    expect(commands.accept(command)).toBe(true);
    expect(commands.accept({...command,reference:structuredClone(reference)})).toBe(false);
    expect(commands.accept({...command,reference:{...reference,originCm:[0,0,350]}})).toBe(true);
  });
});
