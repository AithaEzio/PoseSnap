<script lang="ts">
  let { state, label }: {state:string;label:string}=$props();
</script>
<span class="engine-indicator" data-state={state}>
  <span class="engine-light" aria-hidden="true"></span><span class="engine-label">{label}</span>
</span>
