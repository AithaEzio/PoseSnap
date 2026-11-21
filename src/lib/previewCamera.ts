import type { ReferenceCamera } from './types';

interface CameraCommand { view:string; reset:number; scene:string; reference?:ReferenceCamera }

/** Pose edits and panel resizes redraw the scene, but never issue a camera command. */
export class PreviewCameraCommands {
  private previous='';
  accept(command:CameraCommand){
    const key=JSON.stringify([command.view,command.reset,command.scene,command.view==='reference'?command.reference:null]);
    if(key===this.previous)return false;
    this.previous=key;
    return true;
  }
}
