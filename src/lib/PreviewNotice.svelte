<script lang="ts">
  import { Info } from 'lucide-svelte';
  let {kind}:{kind:'pose'|'expression'}=$props();
</script>

<div class="preview-notice" role="note" aria-label="Preview limitations">
  <Info size={15} aria-hidden="true"/>
  <p><strong>Quick preview · limited detail</strong> Use this simplified {kind} preview to judge the movement. Your DAZ figure brings its full mesh and morphs; review the final look in DAZ Studio.</p>
</div>

<style>
  .preview-notice{display:flex;align-items:flex-start;gap:8px;flex:none;padding:9px 13px;border-top:1px solid var(--line);background:var(--surface);color:var(--muted)}
  .preview-notice :global(svg){flex:none;color:var(--accent);margin-top:1px}
  p{margin:0;font-size:10px;line-height:1.6}
  strong{color:var(--text);font-weight:550;margin-right:7px}
</style>
