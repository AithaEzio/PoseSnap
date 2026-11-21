<script lang="ts">
  let {enabled=false,disabled=false,compact=false,onchange}:{enabled?:boolean;disabled?:boolean;compact?:boolean;onchange:(enabled:boolean)=>void}=$props();
  const descriptionId=$props.id();
  function change(event:Event){
    const input=event.currentTarget as HTMLInputElement,next=input.checked;
    // Keep the saved value visible until the parent confirms the preference.
    input.checked=enabled;
    onchange(next);
  }
</script>
<div class="hand-shape-setting" class:compact>
  <label class="hand-shape-toggle">
    <span><strong>Approximate hand shapes</strong><small>{enabled?'On · Rule-based estimates':'Off · Relaxed fingers'}</small></span>
    <input type="checkbox" role="switch" aria-label="Approximate hand shapes" aria-describedby={descriptionId} checked={enabled} {disabled} onchange={change}/>
  </label>
  <p id={descriptionId}>{enabled?'PoseSnap estimates supported hand shapes from your words. These estimates can be inaccurate; inspect the fingers.':'Generated bodies use relaxed fingers. Refine them in Pose Studio.'}</p>
</div>
<style>
  .hand-shape-setting{display:grid;gap:8px;margin:12px 0}.hand-shape-setting.compact{margin:0}
  .hand-shape-toggle{display:flex;align-items:center;justify-content:space-between;gap:16px;cursor:pointer}.hand-shape-toggle:has(input:disabled){cursor:default}
  .hand-shape-toggle span{display:grid;gap:4px;min-width:0}.hand-shape-toggle strong{font-size:12px;font-weight:600;line-height:1.5}.hand-shape-toggle small,p{font-size:10px;line-height:1.6;color:var(--muted);margin:0}
  .hand-shape-toggle input{appearance:none;flex-shrink:0;width:36px;height:20px;border:1px solid var(--line);border-radius:12px;background:var(--field,var(--panel));position:relative;cursor:pointer;margin:0}
  .hand-shape-toggle input::before{content:'';position:absolute;width:12px;height:12px;left:3px;top:3px;border-radius:50%;background:var(--muted)}
  .hand-shape-toggle input:checked{background:var(--accent);border-color:var(--accent)}.hand-shape-toggle input:checked::before{left:19px;background:var(--panel)}
  .hand-shape-toggle input:focus-visible{outline:2px solid var(--accent);outline-offset:3px}.hand-shape-toggle input:disabled{opacity:.45;cursor:default}
</style>
