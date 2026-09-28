<script>
  let { lines = 3, h = 'h-16' } = $props();
</script>
<div class="space-y-3">
  {#each Array(lines) as _}<div class="skeleton {h}"></div>{/each}
</div>
