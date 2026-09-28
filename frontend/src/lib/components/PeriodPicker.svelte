<script>
  import { addDays, today } from '$lib/units.js';
  // value: { start, end, compare: bool, cstart, cend }
  let { value = $bindable() } = $props();
  const presets = [[7, '7 T'], [14, '14 T'], [30, '30 T'], [90, '3 M'], [180, '6 M'], [365, '1 J']];
  let custom = $state(false);
  function setDays(n) {
    const end = today();
    const start = addDays(end, -(n - 1));
    value = { ...value, start, end, days: n, ...(value.compare ? prev(start, end) : {}) };
    custom = false;
  }
  function prev(start, end) {
    const len = (new Date(end) - new Date(start)) / 86400000 + 1;
    return { cstart: addDays(start, -len), cend: addDays(start, -1) };
  }
  function toggleCompare() {
    value = { ...value, compare: !value.compare, ...prev(value.start, value.end) };
  }
</script>

<div class="space-y-2">
  <div class="no-scrollbar flex gap-1.5 overflow-x-auto">
    {#each presets as [n, l]}
      <button class={value.days === n && !custom ? 'chip-active' : 'chip'} onclick={() => setDays(n)}>{l}</button>
    {/each}
    <button class={custom ? 'chip-active' : 'chip'} onclick={() => (custom = !custom)}>Eigener</button>
    <button class={value.compare ? 'chip-active' : 'chip'} onclick={toggleCompare}>Vergleich</button>
  </div>
  {#if custom}
    <div class="grid grid-cols-2 gap-2">
      <input type="date" class="input" bind:value={value.start} onchange={() => (value = { ...value, days: null, ...prev(value.start, value.end) })} />
      <input type="date" class="input" bind:value={value.end} onchange={() => (value = { ...value, days: null, ...prev(value.start, value.end) })} />
    </div>
  {/if}
  {#if value.compare}
    <div class="grid grid-cols-2 gap-2 text-sm">
      <label><span class="label">Vergleich von</span><input type="date" class="input" bind:value={value.cstart} /></label>
      <label><span class="label">bis</span><input type="date" class="input" bind:value={value.cend} /></label>
    </div>
  {/if}
</div>
