<script>
  import Icon from './Icon.svelte';
  import { addDays, relDay, today } from '$lib/units.js';
  let { value = $bindable(today()) } = $props();
</script>
<div class="flex items-center justify-between rounded-2xl bg-surface-2 p-1">
  <button class="rounded-xl p-2" onclick={() => (value = addDays(value, -1))} aria-label="Vorheriger Tag"><Icon name="back" /></button>
  <label class="relative flex-1 text-center font-semibold">
    {relDay(value)}
    <input type="date" class="absolute inset-0 opacity-0" bind:value />
  </label>
  <button class="rounded-xl p-2 disabled:opacity-30" disabled={value >= today()} onclick={() => (value = addDays(value, 1))} aria-label="Nächster Tag"><Icon name="right" /></button>
</div>
