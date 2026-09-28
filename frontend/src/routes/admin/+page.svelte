<script>
  import { api } from '$lib/api.js';
  import { isAdmin, session } from '$lib/session.svelte.js';
  import { toast, toastError } from '$lib/toast.svelte.js';
  import { fmtDate } from '$lib/units.js';
  import Chart from '$components/Chart.svelte';
  import Header from '$components/Header.svelte';
  import Icon from '$components/Icon.svelte';
  import Sheet from '$components/Sheet.svelte';

  const TABS = { users: 'Benutzer', invites: 'Einladungen', settings: 'Einstellungen', costs: 'KI-Kosten', prompt: 'Systemprompt', audit: 'Audit-Log', system: 'Speicher & Backups' };
  let tab = $state('users');
  let users = $state([]), invites = $state([]), settings = $state(null), usage = $state([]), audit = $state([]), prompts = $state([]), storage = $state(null), backups = $state([]);
  let editUser = $state(null), newUser = $state(null), inviteForm = $state({ email: '', role: 'user', days: 7 }), lastLink = $state('');
  let promptDraft = $state(''), promptComment = $state(''), keyForm = $state({ anthropic_api_key: '', openai_api_key: '' });
  let defaultsJson = $state('');

  $effect(() => { const t = tab; if (isAdmin()) load(t); });
  async function load(t) {
    try {
      if (t === 'users') users = await api.get('/api/admin/users');
      if (t === 'invites') invites = await api.get('/api/admin/invites');
      if (t === 'settings') { settings = await api.get('/api/admin/settings'); defaultsJson = JSON.stringify(settings.user_defaults || {}, null, 2); }
      if (t === 'costs') usage = (await api.get('/api/admin/ai-usage')).rows;
      if (t === 'audit') audit = await api.get('/api/admin/audit?limit=200');
      if (t === 'prompt') { prompts = await api.get('/api/admin/prompts'); promptDraft = prompts.find((p) => p.is_active)?.content || ''; }
      if (t === 'system') { storage = await api.get('/api/admin/storage'); backups = await api.get('/api/admin/backups'); }
    } catch (e) { toastError(e); }
  }
  const mb = (b) => (b == null ? '–' : `${(b / 1024 / 1024).toFixed(1)} MB`);
  async function patchUser(u, patch) { try { await api.patch(`/api/admin/users/${u.id}`, patch); load('users'); toast('Gespeichert', 'success'); } catch (e) { toastError(e); } }
  async function deleteUser(u) { if (!confirm(`${u.email} inkl. aller Daten löschen?`)) return; await api.del(`/api/admin/users/${u.id}`); editUser = null; load('users'); }
  async function resetLink(u) { const r = await api.post(`/api/admin/users/${u.id}/reset-link`); lastLink = r.url; navigator.clipboard?.writeText(r.url); toast('Reset-Link kopiert', 'success'); }
  async function createUser() {
    try { const r = await api.post('/api/admin/users', newUser); if (r.reset_url) { lastLink = r.reset_url; navigator.clipboard?.writeText(r.reset_url); } newUser = null; load('users'); toast('Benutzer angelegt', 'success'); }
    catch (e) { toastError(e); }
  }
  async function createInvite() {
    try { const r = await api.post('/api/admin/invites', { ...inviteForm, email: inviteForm.email || null }); lastLink = r.url; navigator.clipboard?.writeText(r.url); toast('Einladungslink kopiert', 'success'); load('invites'); }
    catch (e) { toastError(e); }
  }
  async function patchSettings(patch) { try { settings = await api.patch('/api/admin/settings', patch); toast('Gespeichert', 'success'); } catch (e) { toastError(e); } }
  async function saveDefaults() { try { await patchSettings({ user_defaults: JSON.parse(defaultsJson || '{}') }); } catch (e) { toastError(e); } }
  async function savePrompt() { await api.post('/api/admin/prompts', { content: promptDraft, comment: promptComment }); promptComment = ''; load('prompt'); toast('Neue Version aktiv', 'success'); }
  async function activatePrompt(p) { await api.post(`/api/admin/prompts/${p.id}/activate`); load('prompt'); }
  async function backupNow() { const r = await api.post('/api/admin/backups'); toast(r.queued ? 'Backup gestartet' : r.ok ? `Backup ${r.file} erstellt` : `Fehler: ${r.error}`); setTimeout(() => load('system'), 3000); }

  const costByUser = $derived.by(() => {
    const m = {};
    for (const r of usage) { m[r.user] ??= 0; m[r.user] += r.cost_usd; }
    return Object.entries(m).sort((a, b) => b[1] - a[1]);
  });
  const months = $derived([...new Set(usage.map((r) => r.month))].sort());
</script>

<Header title="Administration" back="/profile" />
{#if !isAdmin()}<p class="px-4 text-muted">Kein Zugriff.</p>{:else}
<div class="px-4">
  <div class="no-scrollbar -mx-4 mb-4 flex gap-1.5 overflow-x-auto px-4">{#each Object.entries(TABS) as [k, l]}<button class={tab === k ? 'chip-active' : 'chip'} onclick={() => (tab = k)}>{l}</button>{/each}</div>
  {#if lastLink}<div class="card mb-3 text-sm"><div class="text-muted">Link (in Zwischenablage):</div><code class="block break-all select-all">{lastLink}</code></div>{/if}

  {#if tab === 'users'}
    <button class="btn-soft mb-3 w-full" onclick={() => (newUser = { email: '', display_name: '', role: 'user', password: '' })}><Icon name="plus" size={18} /> Benutzer anlegen</button>
    <div class="card p-0">
      {#each users as u}
        <button class="list-row w-full text-left" onclick={() => (editUser = { ...u })}>
          <div class="min-w-0 flex-1"><div class="truncate font-medium">{u.display_name} {#if !u.is_active}<span class="text-xs text-danger">gesperrt</span>{/if}</div>
            <div class="truncate text-xs text-muted">{u.email} · {u.role} · KI {u.ai_cost_month.toFixed(2)}/{u.ai_effective_limit} $ · {mb(u.storage.photos_bytes)} Fotos · {u.storage.sets} Sätze</div></div>
          <Icon name="right" size={18} class="text-muted" />
        </button>
      {/each}
    </div>

  {:else if tab === 'invites'}
    <div class="card mb-3 space-y-2">
      <input class="input" type="email" placeholder="E-Mail (optional, bindet die Einladung)" bind:value={inviteForm.email} />
      <div class="grid grid-cols-2 gap-2">
        <select class="input" bind:value={inviteForm.role}><option value="user">Benutzer</option><option value="trainer">Trainer</option><option value="admin">Admin</option></select>
        <select class="input" bind:value={inviteForm.days}>{#each [1, 3, 7, 14, 30] as d}<option value={d}>{d} Tage gültig</option>{/each}</select>
      </div>
      <button class="btn-primary w-full" onclick={createInvite}><Icon name="link" size={18} /> Einladungslink erzeugen</button>
    </div>
    <div class="card p-0">
      {#each invites as i}
        <div class="list-row text-sm"><div class="flex-1">{i.email || 'offen'} · {i.role}<div class="text-xs text-muted">{i.used_at ? `eingelöst ${fmtDate(i.used_at)}` : `gültig bis ${fmtDate(i.expires_at)}`}</div></div>
          <button class="text-muted" onclick={async () => { await api.del(`/api/admin/invites/${i.id}`); load('invites'); }}><Icon name="trash" size={16} /></button></div>
      {/each}
    </div>

  {:else if tab === 'settings' && settings}
    <div class="space-y-3">
      <label class="card flex items-center justify-between"><div><div class="font-semibold">Offene Registrierung</div><div class="text-sm text-muted">Sonst nur per Einladung</div></div>
        <input type="checkbox" class="h-6 w-6 accent-[var(--accent)]" checked={settings.open_registration} onchange={(e) => patchSettings({ open_registration: e.currentTarget.checked })} /></label>
      <label class="card flex items-center justify-between"><div><div class="font-semibold">KI-Funktionen global</div><div class="text-sm text-muted">Aus = App komplett ohne KI</div></div>
        <input type="checkbox" class="h-6 w-6 accent-[var(--accent)]" checked={settings.ai_enabled} onchange={(e) => patchSettings({ ai_enabled: e.currentTarget.checked })} /></label>
      <div class="card space-y-2">
        <div class="font-semibold">KI-Provider (global)</div>
        <label class="block"><span class="label">Standard-Provider</span><select class="input" value={settings.default_provider} onchange={(e) => patchSettings({ default_provider: e.currentTarget.value })}>
          <option value="anthropic">Anthropic (Claude)</option><option value="openai">OpenAI</option><option value="ollama">Ollama (lokal)</option></select></label>
        {#each ['anthropic', 'openai', 'ollama'] as p}
          <label class="block"><span class="label">Standardmodell {p}</span><input class="input" placeholder={p === 'anthropic' ? 'claude-opus-5' : p === 'openai' ? 'gpt-5' : 'llama3.1'} value={settings.default_models?.[p] || ''}
            onchange={(e) => patchSettings({ default_models: { ...settings.default_models, [p]: e.currentTarget.value } })} /></label>
        {/each}
        <label class="block"><span class="label">Anthropic-Key {settings.keys.anthropic ? `(${settings.keys.anthropic})` : ''}</span>
          <div class="flex gap-2"><input class="input" type="password" placeholder="sk-ant-…" bind:value={keyForm.anthropic_api_key} /><button class="btn-soft" onclick={() => patchSettings({ anthropic_api_key: keyForm.anthropic_api_key }).then(() => (keyForm.anthropic_api_key = ''))}><Icon name="check" /></button></div></label>
        <label class="block"><span class="label">OpenAI-Key {settings.keys.openai ? `(${settings.keys.openai})` : ''}</span>
          <div class="flex gap-2"><input class="input" type="password" placeholder="sk-…" bind:value={keyForm.openai_api_key} /><button class="btn-soft" onclick={() => patchSettings({ openai_api_key: keyForm.openai_api_key }).then(() => (keyForm.openai_api_key = ''))}><Icon name="check" /></button></div></label>
        <label class="block"><span class="label">Ollama-URL</span><input class="input" placeholder="http://192.168.1.50:11434" value={settings.keys.ollama_base_url || ''} onchange={(e) => patchSettings({ ollama_base_url: e.currentTarget.value })} /></label>
        <label class="block"><span class="label">Standard-Monatslimit pro Benutzer ($)</span><input class="input" type="number" step="0.5" value={settings.default_monthly_limit_usd} onchange={(e) => patchSettings({ default_monthly_limit_usd: Number(e.currentTarget.value) })} /></label>
        <p class="text-xs text-muted">Push: {settings.push_configured ? 'konfiguriert ✓' : 'VAPID-Schlüssel fehlen'} · OIDC: {settings.oidc_enabled ? 'aktiv' : 'aus'}</p>
      </div>
      <div class="card space-y-2"><div class="font-semibold">Standardwerte für Benutzereinstellungen (JSON)</div>
        <p class="text-xs text-muted">Z. B. {`{"meal_slots": ["Frühstück","Mittag","Abend"], "theme": {"accent": "#3b82f6"}}`} – Benutzer können sie überschreiben.</p>
        <textarea class="input font-mono text-xs" rows="8" bind:value={defaultsJson}></textarea>
        <button class="btn-soft w-full" onclick={saveDefaults}>Speichern</button></div>
    </div>

  {:else if tab === 'costs'}
    {#if months.length}
      <div class="card mb-3"><div class="mb-2 text-sm font-semibold">Kosten pro Monat & Provider ($)</div>
        <Chart name="ki-kosten" height={240} csv={usage} option={{
          legend: {}, xAxis: { type: 'category', data: months }, yAxis: { type: 'value' },
          series: ['anthropic', 'openai', 'ollama'].map((p) => ({ name: p, type: 'bar', stack: 'c', data: months.map((m) => +usage.filter((r) => r.month === m && r.provider === p).reduce((a, r) => a + r.cost_usd, 0).toFixed(4)) }))
        }} />
      </div>
    {/if}
    <div class="card p-0">
      {#each usage as r}
        <div class="list-row text-sm"><div class="flex-1">{r.user} · {r.provider}<div class="text-xs text-muted">{r.month} · {r.requests} Anfragen · {(r.input_tokens / 1000).toFixed(1)}k / {(r.output_tokens / 1000).toFixed(1)}k Tokens{r.errors ? ` · ${r.errors} Fehler` : ''}</div></div>
          <span class="font-semibold tabular-nums">{r.cost_usd.toFixed(3)} $</span></div>
      {:else}<p class="p-4 text-sm text-muted">Noch keine KI-Nutzung</p>{/each}
    </div>

  {:else if tab === 'prompt'}
    <div class="space-y-3">
      <p class="text-sm text-muted">Platzhalter: {'{name}'}, {'{style}'}, {'{kcal_floor}'}, {'{protein_floor}'}, {'{today}'}. Jede Speicherung erzeugt eine neue Version.</p>
      <textarea class="input font-mono text-xs" rows="18" bind:value={promptDraft}></textarea>
      <input class="input" placeholder="Änderungskommentar" bind:value={promptComment} />
      <button class="btn-primary w-full" onclick={savePrompt}>Als neue Version speichern & aktivieren</button>
      <div class="card p-0">{#each prompts as p}
        <div class="list-row text-sm"><div class="flex-1">Version {p.version} {#if p.is_active}<span class="text-accent">aktiv</span>{/if}<div class="text-xs text-muted">{fmtDate(p.created_at)} · {p.comment}</div></div>
          {#if !p.is_active}<button class="btn-soft btn-sm" onclick={() => activatePrompt(p)}>Aktivieren</button>{/if}
          <button class="btn-ghost btn-sm" onclick={() => (promptDraft = p.content)}>Laden</button></div>{/each}</div>
    </div>

  {:else if tab === 'audit'}
    <div class="card p-0">
      {#each audit as a}
        <div class="list-row text-sm"><div class="flex-1"><span class="font-medium">{a.action}</span> {a.target}<div class="text-xs text-muted">{fmtDate(a.created_at, { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' })} · {a.actor || '–'} · {a.ip}</div></div></div>
      {/each}
    </div>

  {:else if tab === 'system' && storage}
    <div class="grid grid-cols-2 gap-2">
      <div class="card p-3"><div class="text-xs text-muted">Datenbank</div><div class="font-bold">{mb(storage.database_bytes)}</div></div>
      <div class="card p-3"><div class="text-xs text-muted">Uploads</div><div class="font-bold">{mb(storage.uploads_bytes)}</div></div>
      <div class="card p-3"><div class="text-xs text-muted">Backups</div><div class="font-bold">{mb(storage.backups_bytes)}</div></div>
      <div class="card p-3"><div class="text-xs text-muted">Benutzer / Workouts</div><div class="font-bold">{storage.users} / {storage.workouts}</div></div>
    </div>
    <button class="btn-primary my-3 w-full" onclick={backupNow}><Icon name="download" size={18} /> Backup jetzt erstellen</button>
    <div class="card p-0">{#each backups as b}<div class="list-row text-sm"><span class="flex-1">{b.name}</span><span class="text-muted">{mb(b.bytes)}</span></div>{:else}<p class="p-4 text-sm text-muted">Noch keine Backups</p>{/each}</div>
  {/if}
</div>
{/if}

<Sheet open={!!editUser} title={editUser?.email || ''} onclose={() => (editUser = null)}>
  {#if editUser}
    <div class="space-y-3">
      <label class="block"><span class="label">Rolle</span><select class="input" value={editUser.role} onchange={(e) => patchUser(editUser, { role: e.currentTarget.value })}>
        <option value="user">Benutzer</option><option value="trainer">Trainer</option><option value="admin">Admin</option></select></label>
      <label class="block"><span class="label">KI-Monatslimit ($, leer = Standard)</span>
        <input class="input" type="number" step="0.5" value={editUser.ai_monthly_limit_usd ?? ''} onchange={(e) => patchUser(editUser, e.currentTarget.value === '' ? { clear_ai_limit: true } : { ai_monthly_limit_usd: Number(e.currentTarget.value) })} /></label>
      <button class="btn-soft w-full" onclick={() => resetLink(editUser)}><Icon name="link" size={18} /> Passwort-Reset-Link</button>
      <button class="btn-soft w-full" disabled={editUser.id === session.user.id} onclick={() => { patchUser(editUser, { is_active: !editUser.is_active }); editUser = null; }}>{editUser.is_active ? 'Sperren' : 'Entsperren'}</button>
      <button class="btn-danger w-full" disabled={editUser.id === session.user.id} onclick={() => deleteUser(editUser)}>Benutzer & Daten löschen</button>
    </div>
  {/if}
</Sheet>
<Sheet open={!!newUser} title="Benutzer anlegen" onclose={() => (newUser = null)}>
  {#if newUser}
    <div class="space-y-3">
      <input class="input" type="email" placeholder="E-Mail" bind:value={newUser.email} />
      <input class="input" placeholder="Name" bind:value={newUser.display_name} />
      <select class="input" bind:value={newUser.role}><option value="user">Benutzer</option><option value="trainer">Trainer</option><option value="admin">Admin</option></select>
      <input class="input" type="password" placeholder="Passwort (leer = Reset-Link erzeugen)" bind:value={newUser.password} />
      <button class="btn-primary w-full" onclick={createUser}>Anlegen</button>
    </div>
  {/if}
</Sheet>
