<script>
  import '../app.css';
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { dev } from '$app/environment';
  import TabBar from '$components/TabBar.svelte';
  import Toasts from '$components/Toasts.svelte';
  import { loadConfig, loadSession, session } from '$lib/session.svelte.js';
  import { syncQueue } from '$lib/api.js';
  import { net } from '$lib/net.svelte.js';
  import { toast } from '$lib/toast.svelte.js';
  import { queue } from '$lib/offline.js';

  let { children } = $props();
  const PUBLIC = ['/login', '/register', '/reset'];
  const isPublic = $derived(PUBLIC.some((p) => page.url.pathname.startsWith(p)));
  const hideTabs = $derived(isPublic || page.url.pathname.startsWith('/onboarding') || page.url.pathname.startsWith('/training/live'));

  onMount(async () => {
    try { await loadConfig(); } catch {}
    await loadSession();
    guard();
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/service-worker.js', { type: dev ? 'module' : 'classic' }).catch(() => {});
    }
    net.pending = await queue.count().catch(() => 0);
    const sync = async () => {
      net.online = navigator.onLine;
      const n = await syncQueue();
      if (n) toast(`${n} Offline-Eintrag/Einträge synchronisiert`, 'success');
    };
    window.addEventListener('online', sync);
    window.addEventListener('offline', () => (net.online = false));
    document.addEventListener('visibilitychange', () => document.visibilityState === 'visible' && sync());
    sync();
  });

  function guard() {
    const p = page.url.pathname;
    if (!session.user && !PUBLIC.some((x) => p.startsWith(x))) {
      goto('/login?next=' + encodeURIComponent(p + page.url.search), { replaceState: true });
    } else if (session.user && !session.user.onboarding_done && !p.startsWith('/onboarding') && !PUBLIC.some((x) => p.startsWith(x))) {
      goto('/onboarding', { replaceState: true });
    }
  }
  $effect(() => { page.url.pathname; if (session.loaded) guard(); });
</script>

<Toasts />
{#if !net.online || net.pending}
  <div class="fixed inset-x-0 top-0 z-[55] bg-warn px-3 text-center text-xs font-semibold text-black" style="padding-top: env(safe-area-inset-top)">
    {!net.online ? 'Offline' : ''}{net.pending ? ` · ${net.pending} Eintrag/Einträge warten auf Sync` : ''}
  </div>
{/if}

{#if session.loaded && (session.user || isPublic)}
  <main class="mx-auto max-w-2xl {hideTabs ? '' : 'safe-bottom'}">
    {@render children()}
  </main>
  {#if !hideTabs && session.user}<TabBar />{/if}
{:else}
  <div class="flex h-dvh items-center justify-center">
    <img src="/icons/icon.svg" alt="" class="h-16 w-16 animate-pulse rounded-2xl" />
  </div>
{/if}
