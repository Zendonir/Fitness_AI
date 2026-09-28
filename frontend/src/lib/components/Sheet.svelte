<script>
  import Icon from './Icon.svelte';
  let { open = $bindable(false), title = '', children, footer, full = false, onclose = null } = $props();
  function close() { open = false; onclose?.(); }
  $effect(() => {
    if (open) document.body.style.overflow = 'hidden';
    return () => (document.body.style.overflow = '');
  });
</script>

{#if open}
  <div class="fixed inset-0 z-50 flex items-end justify-center sm:items-center" role="dialog" aria-modal="true">
    <button class="absolute inset-0 bg-black/50" onclick={close} aria-label="Schließen"></button>
    <div class="slideup relative flex w-full max-w-lg flex-col rounded-t-3xl bg-surface shadow-2xl sm:rounded-3xl
      {full ? 'h-[92dvh]' : 'max-h-[88dvh]'}" style="padding-bottom: env(safe-area-inset-bottom)">
      <div class="mx-auto mt-2 h-1.5 w-10 rounded-full bg-line sm:hidden"></div>
      <div class="flex items-center gap-2 px-4 pt-3 pb-2">
        <h2 class="flex-1 text-lg font-bold">{title}</h2>
        <button class="rounded-full bg-surface-2 p-1.5" onclick={close} aria-label="Schließen"><Icon name="x" size={18} /></button>
      </div>
      <div class="flex-1 overflow-y-auto px-4 pb-4">{@render children?.()}</div>
      {#if footer}<div class="border-t border-line p-4">{@render footer()}</div>{/if}
    </div>
  </div>
{/if}
