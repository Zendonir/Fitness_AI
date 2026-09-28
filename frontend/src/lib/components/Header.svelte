<script>
  import Icon from './Icon.svelte';
  let { title = '', back = null, subtitle = '', actions } = $props();
  function goBack() {
    if (typeof back === 'string') location.href = back;
    else history.back();
  }
</script>

<header class="safe-top sticky top-0 z-30 bg-bg/85 backdrop-blur-xl px-4 pb-2">
  <div class="mx-auto flex max-w-2xl items-center gap-2 min-h-11">
    {#if back}
      <button class="-ml-2 p-2 text-accent" onclick={goBack} aria-label="Zurück"><Icon name="back" size={26} /></button>
    {/if}
    <div class="min-w-0 flex-1">
      <h1 class="truncate text-2xl font-bold tracking-tight">{title}</h1>
      {#if subtitle}<p class="truncate text-sm text-muted">{subtitle}</p>{/if}
    </div>
    {#if actions}<div class="flex items-center gap-1">{@render actions()}</div>{/if}
  </div>
</header>
