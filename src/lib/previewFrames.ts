/** Keep warm previews asleep until a redraw or unfinished orbit needs a frame. */
export class PreviewFrames {
  private pending=0;
  private active=false;
  private disposed=false;
  constructor(private frame:()=>boolean,private request:(callback:FrameRequestCallback)=>number=callback=>window.requestAnimationFrame(callback),private cancel:(id:number)=>void=id=>window.cancelAnimationFrame(id)){}
  invalidate(){
    if(this.disposed||!this.active||this.pending)return;
    this.pending=this.request(()=>{this.pending=0;if(this.frame())this.invalidate();});
  }
  setActive(active:boolean){
    this.active=active;
    if(!active){if(this.pending)this.cancel(this.pending);this.pending=0;}
    else this.invalidate();
  }
  dispose(){this.disposed=true;this.setActive(false);}
}
