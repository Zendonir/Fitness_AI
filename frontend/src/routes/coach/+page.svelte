<script>
  import { onMount, tick } from 'svelte';
  import { page } from '$app/state';
  import { api, stream } from '$lib/api.js';
  import { session } from '$lib/session.svelte.js';
  import { toastError } from '$lib/toast.svelte.js';
  import { fmtDate } from '$lib/units.js';
  import { md } from '$lib/markdown.js';
  import ActionCard from '$components/ActionCard.svelte';
  import Header from '$components/Header.svelte';
  import Icon from '$components/Icon.svelte';
  import Sheet from '$components/Sheet.svelte';

  let status = $state(null);
  let convId = $state(null);
  let messages = $state([]);
  let actions = $state({});
  let input = $state('');
  let busy = $state(false);
  let toolInfo = $state('');
  let hints = $state([]);
  let historyOpen = $state(false);
  let conversations = $state([]);
  let scroller = $state();
  let photo = $state(null);
  let ctrl;
  const formcheckId = page.url.searchParams.get('formcheck');
  let formcheckEx = $state(null);

  const QUICK = [['dinner', 'Was esse ich heute Abend?'], ['week', 'Wie war meine Woche?'], ['short_workout', 'Nur 30 Minuten Zeit'], ['plan_review', 'Plan überprüfen']];
  const TOOL_LABELS = { get_workouts: 'Workouts', get_nutrition: 'Ernährung', get_today_status: 'Tagesstand', get_exercise_progress: 'Übungsverlauf',
    get_weight_trend: 'Gewicht', get_active_plan: 'Trainingsplan', get_metrics: 'Metriken', search_foods: 'Lebensmittel', save_memory: 'Gedächtnis' };

  onMount(async () => {
    status = await api.get('/api/coach/status').catch(() => null);
    hints = await api.get('/api/coach/hints').catch(() => []);
    if (formcheckId) formcheckEx = await api.get(`/api/exercises/${formcheckId}`).catch(() => null);
  });

  async function scrollDown() { await tick(); scroller?.scrollIntoView({ behavior: 'smooth', block: 'end' }); }

  async function send(quick = null) {
    const text = input.trim();
    if ((!text && !quick && !photo) || busy) return;
    const label = quick ? QUICK.find((q) => q[0] === quick)?.[1] : text;
    messages = [...messages, { role: 'user', content: label || '📷 Foto', image: photo?.preview }, { role: 'assistant', content: '', pending: true, actions: [] }];
    const body = { message: quick ? '' : text, conversation_id: convId, quick_action: quick || (formcheckEx ? 'formcheck' : null),
      exercise_id: formcheckEx?.id, image: photo?.data, image_type: photo?.type };
    input = ''; photo = null; formcheckEx = null;
    busy = true; toolInfo = '';
    scrollDown();
    ctrl = new AbortController();
    const last = () => messages[messages.length - 1];
    try {
      await stream('/api/coach/chat', body, (ev, d) => {
        if (ev === 'meta') convId = d.conversation_id;
        else if (ev === 'text') { last().content += d.delta; scrollDown(); }
        else if (ev === 'tool') toolInfo = d.status === 'running' ? `Schaue nach: ${TOOL_LABELS[d.name] || d.name} …` : '';
        else if (ev === 'action') { last().actions = [...last().actions, d]; scrollDown(); }
        else if (ev === 'fallback') toolInfo = `Wechsle zu ${d.to} …`;
        else if (ev === 'error') { last().content += `\n\n⚠️ ${d.message}`; }
        else if (ev === 'done') { last().meta = d; }
      }, ctrl.signal);
    } catch (e) { if (e.name !== 'AbortError') { last().content = `⚠️ ${e.message}`; } }
    finally { last().pending = false; busy = false; toolInfo = ''; }
  }
  function stop() { ctrl?.abort(); }

  async function openHistory() {
    historyOpen = true;
    conversations = await api.get('/api/coach/conversations');
  }
  async function loadConv(id) {
    const c = await api.get(`/api/coach/conversations/${id}`);
    convId = c.id;
    const byId = Object.fromEntries(c.actions.map((a) => [a.id, a]));
    messages = c.messages.map((m) => ({ role: m.role, content: m.content, actions: (m.meta?.actions || []).map((i) => byId[i]).filter(Boolean), meta: m.meta }));
    historyOpen = false;
    scrollDown();
  }
  async function delConv(id) {
    await api.del(`/api/coach/conversations/${id}`);
    conversations = conversations.filter((c) => c.id !== id);
    if (convId === id) newChat();
  }
  function newChat() { convId = null; messages = []; }
  async function dismiss(h) {
    await api.post(`/api/coach/hints/${h.id}/dismiss`);
    hints = hints.filter((x) => x.id !== h.id);
  }
  function pickPhoto(e) {
    const f = e.currentTarget.files?.[0];
    if (!f) return;
    const img = new Image();
    img.onload = () => {
      const scale = Math.min(1, 1280 / Math.max(img.width, img.height));
      const c = document.createElement('canvas');
      c.width = img.width * scale; c.height = img.height * scale;
      c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
      const url = c.toDataURL('image/jpeg', 0.85);
      photo = { preview: url, data: url.split(',')[1], type: 'image/jpeg' };
    };
    img.src = URL.createObjectURL(f);
    e.currentTarget.value = '';
  }
</script>

<Header title="Coach">
  {#snippet actions()}
    <a href="/coach/memory" class="p-2 text-muted" aria-label="Gedächtnis"><Icon name="book" /></a>
    <button class="p-2 text-muted" onclick={openHistory} aria-label="Verlauf"><Icon name="list" /></button>
    <button class="p-2 text-accent" onclick={newChat} aria-label="Neues Gespräch"><Icon name="edit" /></button>
  {/snippet}
</Header>

<div class="px-4 pb-36">
  {#if status && !status.available}
    <div class="card mb-3 text-sm">
      <p class="font-semibold">KI-Coach nicht verfügbar</p><p class="text-muted">{status.reason}</p>
      <a href="/settings?tab=ai" class="btn-soft btn-sm mt-2">KI einrichten</a>
    </div>
  {/if}

  {#if !messages.length}
    {#each hints.slice(0, 3) as h}
      <div class="card mb-2 flex gap-3">
        <div class="h-fit rounded-xl bg-accent/15 p-2 text-accent"><Icon name={h.kind === 'new_pr' ? 'trophy' : 'sparkles'} size={18} /></div>
        <div class="flex-1"><div class="font-semibold">{h.title}</div><p class="text-sm text-muted">{h.body}</p>
          <p class="mt-1 text-xs text-muted">{fmtDate(h.created_at, { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}</p></div>
        <button class="h-fit text-muted" onclick={() => dismiss(h)} aria-label="Ausblenden"><Icon name="x" size={16} /></button>
      </div>
    {/each}
    <div class="mt-6 text-center">
      <div class="mx-auto mb-3 w-fit rounded-full bg-accent/15 p-4 text-accent"><Icon name="sparkles" size={30} /></div>
      <p class="font-semibold">Hi {session.user?.display_name?.split(' ')[0]}! Wobei kann ich helfen?</p>
      {#if status?.active}<p class="text-xs text-muted">{status.active.provider} · {status.active.model} · {status.month_cost_usd.toFixed(2)} $ / {status.limit_usd} $ diesen Monat</p>{/if}
    </div>
  {/if}

  <div class="mt-4 space-y-3">
    {#each messages as m}
      {#if m.role === 'user'}
        <div class="ml-10 flex flex-col items-end gap-1">
          {#if m.image}<img src={m.image} alt="" class="max-h-48 rounded-2xl" />{/if}
          <div class="rounded-3xl rounded-br-md bg-accent px-4 py-2.5 text-white">{m.content}</div>
        </div>
      {:else}
        <div class="mr-6 space-y-2">
          <div class="rounded-3xl rounded-bl-md bg-surface px-4 py-3 text-[15px] leading-relaxed">
            {#if m.content}{@html md(m.content)}{:else if m.pending}<span class="inline-flex gap-1"><span class="h-2 w-2 animate-bounce rounded-full bg-muted"></span><span class="h-2 w-2 animate-bounce rounded-full bg-muted [animation-delay:.15s]"></span><span class="h-2 w-2 animate-bounce rounded-full bg-muted [animation-delay:.3s]"></span></span>{/if}
          </div>
          {#each m.actions || [] as a (a.id)}<ActionCard action={a} />{/each}
        </div>
      {/if}
    {/each}
    {#if toolInfo}<p class="text-xs text-muted">{toolInfo}</p>{/if}
    <div bind:this={scroller}></div>
  </div>
</div>

<div class="fixed inset-x-0 z-30 bg-bg/90 px-3 pt-2 pb-2 backdrop-blur-xl" style="bottom: calc(env(safe-area-inset-bottom) + var(--tabbar-h))">
  <div class="mx-auto max-w-2xl">
    {#if !messages.length && !formcheckEx}
      <div class="no-scrollbar mb-2 flex gap-1.5 overflow-x-auto">
        {#each QUICK as [k, l]}<button class="chip" onclick={() => send(k)} disabled={busy || !status?.available}>{l}</button>{/each}
      </div>
    {/if}
    {#if formcheckEx}<div class="mb-2 chip-active w-fit">Formcheck: {formcheckEx.name} <button onclick={() => (formcheckEx = null)}><Icon name="x" size={14} /></button></div>{/if}
    {#if photo}<div class="relative mb-2 w-fit"><img src={photo.preview} alt="" class="h-16 rounded-xl" /><button class="absolute -right-2 -top-2 rounded-full bg-fg p-1 text-bg" onclick={() => (photo = null)}><Icon name="x" size={12} /></button></div>{/if}
    <form class="flex items-end gap-2" onsubmit={(e) => { e.preventDefault(); send(); }}>
      <label class="rounded-full bg-surface-2 p-3 text-muted" aria-label="Foto anhängen"><Icon name="camera" size={20} />
        <input type="file" accept="image/*" class="hidden" onchange={pickPhoto} /></label>
      <textarea rows="1" class="input max-h-32 flex-1 resize-none rounded-3xl py-2.5" placeholder={formcheckEx ? 'Beschreibe das Problem …' : 'Frag deinen Coach …'}
        bind:value={input} onkeydown={(e) => { if (e.key === 'Enter' && !e.shiftKey && window.innerWidth > 700) { e.preventDefault(); send(); } }}></textarea>
      {#if busy}
        <button type="button" class="rounded-full bg-fg p-3 text-bg" onclick={stop} aria-label="Stopp"><Icon name="pause" size={20} /></button>
      {:else}
        <button class="rounded-full bg-accent p-3 text-white disabled:opacity-40" disabled={!status?.available || (!input.trim() && !photo)} aria-label="Senden"><Icon name="send" size={20} /></button>
      {/if}
    </form>
  </div>
</div>

<Sheet bind:open={historyOpen} title="Gespräche">
  {#each conversations as c}
    <div class="list-row">
      <button class="flex-1 text-left" onclick={() => loadConv(c.id)}><div class="truncate text-sm font-medium">{c.title}</div>
        <div class="text-xs text-muted">{fmtDate(c.updated_at, { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}</div></button>
      <button class="text-muted" onclick={() => delConv(c.id)} aria-label="Löschen"><Icon name="trash" size={16} /></button>
    </div>
  {:else}<p class="text-sm text-muted">Noch keine Gespräche</p>{/each}
</Sheet>
