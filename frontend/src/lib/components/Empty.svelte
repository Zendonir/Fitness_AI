<script>
  import Icon from './Icon.svelte';
  let { icon = 'info', title = '', text = '', children } = $props();
</script>
<div class="flex flex-col items-center px-6 py-10 text-center">
  <div class="mb-3 rounded-full bg-surface-2 p-4 text-muted"><Icon name={icon} size={30} /></div>
  <p class="font-semibold">{title}</p>
  {#if text}<p class="mt-1 text-sm text-muted">{text}</p>{/if}
  {#if children}<div class="mt-4">{@render children()}</div>{/if}
</div>
