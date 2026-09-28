<script>
  import { onMount } from 'svelte';
  import Icon from './Icon.svelte';
  let { option, height = 260, name = 'diagramm', csv = null, toolbar = true, onclick = null } = $props();
  let el = $state();
  let chart;
  let echarts;

  function themed(opt) {
    const dark = document.documentElement.classList.contains('dark');
    const text = dark ? '#8b98a8' : '#64748b';
    const line = dark ? '#243040' : '#e3e6ea';
    const axis = (a) => (a ? [].concat(a).map((x) => ({
      axisLine: { lineStyle: { color: line } }, axisLabel: { color: text }, splitLine: { lineStyle: { color: line } }, ...x
    })) : a);
    return {
      backgroundColor: 'transparent',
      textStyle: { color: text, fontFamily: '-apple-system, BlinkMacSystemFont, Inter, sans-serif' },
      grid: { left: 8, right: 12, top: 28, bottom: 8, containLabel: true },
      tooltip: { trigger: 'axis', confine: true, backgroundColor: dark ? '#1b2430' : '#fff', borderColor: line,
        textStyle: { color: dark ? '#e6edf3' : '#0f172a' }, ...(opt.tooltip || {}) },
      ...opt,
      xAxis: axis(opt.xAxis),
      yAxis: axis(opt.yAxis),
      legend: opt.legend ? { textStyle: { color: text }, top: 0, type: 'scroll', ...opt.legend } : undefined
    };
  }

  onMount(() => {
    let ro;
    (async () => {
      echarts = await import('echarts');
      chart = echarts.init(el, null, { renderer: 'canvas' });
      if (option) chart.setOption(themed(option), true);
      if (onclick) chart.on('click', onclick);
      ro = new ResizeObserver(() => chart?.resize());
      ro.observe(el);
    })();
    return () => { ro?.disconnect(); chart?.dispose(); };
  });

  $effect(() => {
    const o = option;
    if (chart && o) chart.setOption(themed(o), true);
  });

  function download(href, filename) {
    const a = document.createElement('a');
    a.href = href;
    a.download = filename;
    a.click();
  }
  function exportPng() {
    const dark = document.documentElement.classList.contains('dark');
    download(chart.getDataURL({ pixelRatio: 2, backgroundColor: dark ? '#131a22' : '#ffffff' }), `${name}.png`);
  }
  function exportCsv() {
    let rows = csv;
    if (!rows) {
      const x = [].concat(option.xAxis || [])[0]?.data || [];
      rows = x.map((label, i) => {
        const r = { x: label };
        for (const s of option.series || []) r[s.name || 'wert'] = Array.isArray(s.data?.[i]) ? s.data[i][1] : s.data?.[i]?.value ?? s.data?.[i];
        return r;
      });
    }
    if (!rows?.length) return;
    const cols = Object.keys(rows[0]);
    const body = [cols.join(';'), ...rows.map((r) => cols.map((c) => String(r[c] ?? '').replace(';', ',')).join(';'))].join('\n');
    download(URL.createObjectURL(new Blob(['﻿' + body], { type: 'text/csv' })), `${name}.csv`);
  }
</script>

<div class="relative">
  {#if toolbar}
    <div class="absolute right-0 -top-1 z-10 flex gap-1">
      <button class="rounded-lg p-1.5 text-muted hover:bg-surface-2" onclick={exportPng} title="Als PNG exportieren"><Icon name="image" size={16} /></button>
      <button class="rounded-lg p-1.5 text-muted hover:bg-surface-2" onclick={exportCsv} title="Als CSV exportieren"><Icon name="download" size={16} /></button>
    </div>
  {/if}
  <div bind:this={el} style="height:{height}px;width:100%"></div>
</div>
