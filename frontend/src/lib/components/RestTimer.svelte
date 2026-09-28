<script>
  import { api } from '$lib/api.js';
  import { alarm, tap } from '$lib/haptics.js';
  import { session } from '$lib/session.svelte.js';
  import { fmtDuration } from '$lib/units.js';
  import Icon from './Icon.svelte';
  let { seconds = 120, exercise = '', running = $bindable(false), onfinish = () => {} } = $props();
  let endAt = $state(0);
  let left = $state(0);
  let iv;

  export function start(sec = seconds) {
    endAt = Date.now() + sec * 1000;
    left = sec;
    running = true;
    clearInterval(iv);
    iv = setInterval(tick, 250);
    if (session.settings?.rest_timer_push !== false) api.post('/api/push/timer', { seconds: sec, exercise }).catch(() => {});
  }
  function tick() {
    left = Math.max(0, Math.round((endAt - Date.now()) / 1000));
    if (left <= 0) finish();
  }
  function finish() {
    clearInterval(iv);
    running = false;
    if (session.settings?.rest_timer_vibrate !== false) alarm();
    try { new Audio('data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=').play(); } catch {}
    onfinish();
  }
  export function stop() {
    clearInterval(iv);
    running = false;
    api.del('/api/push/timer').catch(() => {});
  }
  function add(s) { tap(); endAt += s * 1000; tick(); }
  // Timer läuft auch weiter, wenn die App kurz im Hintergrund war
  $effect(() => {
    const onVis = () => running && tick();
    document.addEventListener('visibilitychange', onVis);
    return () => { document.removeEventListener('visibilitychange', onVis); clearInterval(iv); };
  });
</script>

{#if running}
  <div class="pop fixed inset-x-3 z-40 flex items-center gap-3 rounded-2xl bg-fg px-4 py-3 text-bg shadow-2xl"
    style="bottom: calc(env(safe-area-inset-bottom) + var(--tabbar-h) + 12px)">
    <Icon name="timer" />
    <div class="flex-1">
      <div class="text-xs opacity-70">Pause{exercise ? ` · ${exercise}` : ''}</div>
      <div class="text-2xl font-bold tabular-nums">{fmtDuration(left)}</div>
    </div>
    <button class="rounded-xl bg-bg/15 px-3 py-2 text-sm font-semibold" onclick={() => add(-15)}>−15</button>
    <button class="rounded-xl bg-bg/15 px-3 py-2 text-sm font-semibold" onclick={() => add(30)}>+30</button>
    <button class="rounded-xl bg-bg/15 p-2" onclick={stop} aria-label="Timer stoppen"><Icon name="x" /></button>
  </div>
{/if}
