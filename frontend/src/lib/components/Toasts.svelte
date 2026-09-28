<script>
  import { toasts } from '$lib/toast.svelte.js';
</script>
<div class="pointer-events-none fixed inset-x-0 z-[60] flex flex-col items-center gap-2 px-4" style="top: calc(env(safe-area-inset-top) + 8px)">
  {#each toasts.list as t (t.id)}
    <div class="pop pointer-events-auto max-w-md rounded-2xl px-4 py-3 text-sm font-medium shadow-lg
      {t.type === 'error' ? 'bg-danger text-white' : t.type === 'success' ? 'bg-accent text-white' : 'bg-fg text-bg'}">{t.message}</div>
  {/each}
</div>
