<script>
  let { value = 0, max = 100, size = 88, stroke = 9, color = 'var(--accent)', label = '', sub = '', big = false } = $props();
  const r = $derived((size - stroke) / 2);
  const c = $derived(2 * Math.PI * r);
  const pct = $derived(max > 0 ? Math.min(value / max, 1.5) : 0);
  const over = $derived(max > 0 && value > max * 1.05);
  let shown = $state(0);
  $effect(() => { const t = setTimeout(() => (shown = Math.min(pct, 1)), 30); return () => clearTimeout(t); });
</script>

<div class="flex flex-col items-center gap-1">
  <div class="relative" style="width:{size}px;height:{size}px">
    <svg width={size} height={size} class="-rotate-90">
      <circle cx={size / 2} cy={size / 2} r={r} stroke="var(--surface-2)" stroke-width={stroke} fill="none" />
      <circle cx={size / 2} cy={size / 2} r={r} stroke={over ? 'var(--warn)' : color} stroke-width={stroke} fill="none"
        stroke-linecap="round" stroke-dasharray={c} stroke-dashoffset={c * (1 - shown)}
        style="transition: stroke-dashoffset .9s cubic-bezier(.2,.8,.2,1)" />
    </svg>
    <div class="absolute inset-0 flex flex-col items-center justify-center leading-tight">
      <span class="{big ? 'text-2xl' : 'text-base'} font-bold tabular-nums">{Math.round(value)}</span>
      {#if sub}<span class="text-[10px] text-muted">{sub}</span>{/if}
    </div>
  </div>
  {#if label}<span class="text-xs font-medium text-muted">{label}</span>{/if}
</div>
