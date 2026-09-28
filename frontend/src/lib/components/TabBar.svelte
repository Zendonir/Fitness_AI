<script>
  import { page } from '$app/state';
  import Icon from './Icon.svelte';
  import { tap } from '$lib/haptics.js';
  const tabs = [
    { href: '/', label: 'Heute', icon: 'home', match: (p) => p === '/' },
    { href: '/training', label: 'Training', icon: 'dumbbell', match: (p) => p.startsWith('/training') },
    { href: '/nutrition', label: 'Ernährung', icon: 'apple', match: (p) => p.startsWith('/nutrition') },
    { href: '/coach', label: 'Coach', icon: 'sparkles', match: (p) => p.startsWith('/coach') },
    { href: '/progress', label: 'Fortschritt', icon: 'chart', match: (p) => p.startsWith('/progress') }
  ];
</script>

<nav class="fixed bottom-0 inset-x-0 z-40 border-t border-line bg-surface/90 backdrop-blur-xl"
  style="padding-bottom: env(safe-area-inset-bottom)">
  <div class="mx-auto flex max-w-2xl" style="height: var(--tabbar-h)">
    {#each tabs as t}
      {@const active = t.match(page.url.pathname)}
      <a href={t.href} onclick={() => tap()} class="flex flex-1 flex-col items-center justify-center gap-0.5 text-[11px] font-medium transition
        {active ? 'text-accent' : 'text-muted'}">
        <Icon name={t.icon} size={24} stroke={active ? 2.4 : 1.8} />
        {t.label}
      </a>
    {/each}
  </div>
</nav>
