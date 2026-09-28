<script>
  // Animierte Übungsdarstellung (ExerciseGymGifsDB). Tippen öffnet die große Ansicht.
  import { gifUrl, mediaEnabled, thumbUrl } from '$lib/media.js';
  import Icon from './Icon.svelte';
  let { id, name = '', size = 'thumb', class: cls = '', zoom = true } = $props();
  let failed = $state(false);
  let open = $state(false);
  $effect(() => { id; failed = false; });
  const src = $derived(size === 'thumb' ? thumbUrl(id) : gifUrl(id));
</script>

{#if id && mediaEnabled() && !failed}
  {#if zoom}
    <button type="button" class="block shrink-0 overflow-hidden bg-white {cls}" onclick={(e) => { e.preventDefault(); e.stopPropagation(); open = true; }} aria-label="Animation vergrößern">
      <img {src} alt={name} loading="lazy" decoding="async" class="h-full w-full object-contain" onerror={() => (failed = true)} />
    </button>
  {:else}
    <div class="shrink-0 overflow-hidden bg-white {cls}"><img {src} alt={name} loading="lazy" decoding="async" class="h-full w-full object-contain" onerror={() => (failed = true)} /></div>
  {/if}
{:else if size === 'thumb'}
  <div class="flex shrink-0 items-center justify-center bg-surface-2 text-muted {cls}"><Icon name="dumbbell" size={18} /></div>
{/if}

{#if open}
  <div class="fixed inset-0 z-[70] flex flex-col items-center justify-center bg-black/85 p-4" role="dialog" aria-modal="true">
    <button class="absolute inset-0" onclick={() => (open = false)} aria-label="Schließen"></button>
    <div class="pop relative w-full max-w-md overflow-hidden rounded-3xl bg-white">
      <img src={gifUrl(id)} alt={name} class="aspect-square w-full object-contain" />
    </div>
    <p class="relative mt-3 text-center font-semibold text-white">{name}</p>
    <p class="relative mt-1 text-center text-[10px] text-white/60">Animation: ExerciseGymGifsDB · Rechte bei den jeweiligen Urhebern</p>
    <button class="relative mt-4 rounded-full bg-white/15 px-5 py-2 text-white" onclick={() => (open = false)}>Schließen</button>
  </div>
{/if}
