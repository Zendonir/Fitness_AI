<script>
  // Browser für die GIF-Bibliothek: Animation auswählen oder Übung übernehmen
  import { LIB_MUSCLES, libraryMuscle, thumbUrl, gifUrl } from '$lib/media.js';
  import Sheet from './Sheet.svelte';
  let { open = $bindable(false), title = 'Übungsbibliothek (Animationen)', onpick } = $props();
  let muscle = $state('pectorals');
  let items = $state([]);
  let q = $state('');
  let error = $state('');
  let loading = $state(false);
  $effect(() => {
    if (!open) return;
    const m = muscle;
    loading = true; error = '';
    libraryMuscle(m).then((r) => (items = r)).catch((e) => (error = e.message)).finally(() => (loading = false));
  });
  const filtered = $derived(items.filter((e) => !q || e.name.toLowerCase().includes(q.toLowerCase()) || e.equipment?.includes(q.toLowerCase())));
</script>

<Sheet bind:open {title} full>
  <div class="no-scrollbar -mx-4 mb-2 flex gap-1.5 overflow-x-auto px-4">
    {#each Object.entries(LIB_MUSCLES) as [k, l]}<button class={muscle === k ? 'chip-active' : 'chip'} onclick={() => (muscle = k)}>{l}</button>{/each}
  </div>
  <input class="input mb-3" placeholder="Suchen (englisch, z. B. curl, press, cable) …" bind:value={q} />
  {#if error}<p class="rounded-xl bg-danger/10 p-3 text-sm text-danger">{error}</p>{/if}
  {#if loading}<div class="grid grid-cols-3 gap-2">{#each Array(9) as _}<div class="skeleton aspect-square"></div>{/each}</div>{/if}
  <div class="grid grid-cols-3 gap-2">
    {#each filtered.slice(0, 120) as e (e.id)}
      <button class="overflow-hidden rounded-2xl border border-line bg-surface text-left active:scale-95" onclick={() => { onpick?.(e); open = false; }}>
        <img src={thumbUrl(e.id)} alt="" loading="lazy" class="aspect-square w-full bg-white object-contain"
          onerror={(ev) => { const i = ev.currentTarget; if (!i.dataset.fb) { i.dataset.fb = "1"; i.src = gifUrl(e.id); } else i.style.visibility = "hidden"; }} />
        <div class="line-clamp-2 p-1.5 text-[11px] leading-tight">{e.name}</div>
      </button>
    {/each}
  </div>
  {#if !loading && !error && !filtered.length}<p class="text-sm text-muted">Keine Treffer</p>{/if}
  <p class="mt-4 text-center text-[10px] text-muted">Quelle: ExerciseGymGifsDB (github.com/JahelCuadrado/ExerciseGymGifsDB) · Rechte an den Animationen bei den jeweiligen Urhebern</p>
</Sheet>
