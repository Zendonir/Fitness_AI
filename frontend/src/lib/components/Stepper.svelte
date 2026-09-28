<script>
  import { tap } from '$lib/haptics.js';
  let { value = $bindable(0), step = 1, min = 0, max = 99999, label = '', unit = '', decimals = 1 } = $props();
  function change(d) {
    tap();
    const v = Math.round(((Number(value) || 0) + d) * 1000) / 1000;
    value = Math.min(max, Math.max(min, v));
  }
</script>
<div class="flex flex-col items-center">
  {#if label}<span class="mb-1 text-xs text-muted">{label}</span>{/if}
  <div class="flex items-center gap-1">
    <button class="h-12 w-12 rounded-2xl bg-surface-2 text-2xl font-bold active:scale-95" onclick={() => change(-step)} aria-label="weniger">−</button>
    <input class="w-20 rounded-xl bg-transparent text-center text-2xl font-bold tabular-nums outline-none" inputmode="decimal"
      value={value === null || value === undefined ? '' : Number(Number(value).toFixed(decimals))}
      onchange={(e) => (value = Number(String(e.currentTarget.value).replace(',', '.')) || 0)} />
    <button class="h-12 w-12 rounded-2xl bg-surface-2 text-2xl font-bold active:scale-95" onclick={() => change(step)} aria-label="mehr">+</button>
  </div>
  {#if unit}<span class="mt-0.5 text-xs text-muted">{unit}</span>{/if}
</div>
