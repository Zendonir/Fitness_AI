<script>
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { api } from '$lib/api.js';
  import { loadSession, saveSettings, session } from '$lib/session.svelte.js';
  import { toast, toastError } from '$lib/toast.svelte.js';
  import { GOALS, MUSCLES, fmtDate } from '$lib/units.js';
  import { createPasskey, passkeysSupported } from '$lib/webauthn.js';
  import { currentSubscription, disablePush, enablePush, isStandalone, pushSupported } from '$lib/push.js';
  import Header from '$components/Header.svelte';
  import Icon from '$components/Icon.svelte';

  const TABS = { profile: 'Profil & Ziele', appearance: 'Darstellung', nutrition: 'Ernährung', ai: 'KI-Coach', notifications: 'Benachrichtigungen',
    security: 'Sicherheit', sharing: 'Trainer & Teilen', integrations: 'Integrationen', data: 'Daten & Konto' };
  let tab = $state(page.url.searchParams.get('tab') || 'profile');
  let s = $state(structuredClone($state.snapshot(session.settings)));
  let profile = $state(null), targets = $state(null);
  let custom = $state({ enabled: false, training: {}, rest: {} });
  let ai = $state(null), keys = $state({}), models = $state({}), newKey = $state({ provider: 'anthropic', key: '' });
  let tokens = $state([]), passkeys = $state([]), totp = $state(null), totpCode = $state(''), pw = $state({ old: '', new: '' });
  let trainers = $state([]), directory = $state([]);
  let pushOn = $state(false);
  let newSlot = $state('');
  let createdToken = $state(null);

  $effect(() => { const t = tab; loadTab(t); });
  async function loadTab(t) {
    try {
      if (t === 'profile') {
        const r = await api.get('/api/me/profile');
        profile = r.profile; targets = r.targets;
        custom = { enabled: !!(profile.custom_targets?.training || profile.custom_targets?.rest), training: { ...(profile.custom_targets?.training || targets.training) }, rest: { ...(profile.custom_targets?.rest || targets.rest) } };
      }
      if (t === 'ai') { ai = await api.get('/api/coach/status'); keys = await api.get('/api/coach/keys'); }
      if (t === 'security') { tokens = await api.get('/api/auth/tokens'); passkeys = await api.get('/api/auth/passkeys'); }
      if (t === 'integrations') tokens = await api.get('/api/auth/tokens');
      if (t === 'sharing') { trainers = await api.get('/api/me/trainers'); directory = (await api.get('/api/users/directory')).filter((u) => u.role !== 'user'); }
      if (t === 'notifications') pushOn = !!(await currentSubscription().catch(() => null));
    } catch (e) { toastError(e); }
  }

  async function save(patch) {
    try { s = structuredClone(await saveSettings(patch)); toast('Gespeichert', 'success'); } catch (e) { toastError(e); }
  }
  async function saveProfile() {
    try {
      const body = { ...profile, custom_targets: custom.enabled ? { training: custom.training, rest: custom.rest } : {} };
      const r = await api.put('/api/me/profile', body);
      profile = r.profile; targets = r.targets;
      toast('Profil gespeichert', 'success');
    } catch (e) { toastError(e); }
  }
  async function loadModels(p) {
    try { models[p] = await api.get(`/api/coach/models?provider=${p}`); } catch (e) { toastError(e); }
  }
  async function saveKey() {
    try { await api.put('/api/coach/keys', newKey); newKey.key = ''; keys = await api.get('/api/coach/keys'); ai = await api.get('/api/coach/status'); toast('API-Key gespeichert (verschlüsselt)', 'success'); } catch (e) { toastError(e); }
  }
  async function removeKey(p) { await api.put('/api/coach/keys', { provider: p, key: '' }); keys = await api.get('/api/coach/keys'); }
  async function addPasskey() {
    try {
      const opts = await api.post('/api/auth/passkey/register/options');
      const credential = await createPasskey(opts);
      await api.post('/api/auth/passkey/register/verify', { credential, name: navigator.userAgent.includes('iPhone') ? 'iPhone' : navigator.platform || 'Gerät' });
      passkeys = await api.get('/api/auth/passkeys'); toast('Passkey hinzugefügt', 'success');
    } catch (e) { if (e.name !== 'NotAllowedError') toastError(e); }
  }
  async function delPasskey(p) { await api.del(`/api/auth/passkeys/${p.id}`); passkeys = passkeys.filter((x) => x.id !== p.id); }
  async function totpSetup() { totp = await api.post('/api/auth/totp/setup'); }
  async function totpEnable() { try { await api.post('/api/auth/totp/enable', { code: totpCode }); totp = null; await loadSession(); toast('2FA aktiviert', 'success'); } catch (e) { toastError(e); } }
  async function totpDisable() { const code = prompt('Aktuellen 2FA-Code eingeben'); if (!code) return; try { await api.post('/api/auth/totp/disable', { code }); await loadSession(); toast('2FA deaktiviert'); } catch (e) { toastError(e); } }
  async function changePw() { try { await api.post('/api/auth/password/change', { old_password: pw.old, new_password: pw.new }); pw = { old: '', new: '' }; toast('Passwort geändert', 'success'); } catch (e) { toastError(e); } }
  async function createToken() { const name = prompt('Name des Tokens', 'Home Assistant'); if (!name) return; createdToken = await api.post('/api/auth/tokens', { name }); tokens = await api.get('/api/auth/tokens'); }
  async function delToken(t) { await api.del(`/api/auth/tokens/${t.id}`); tokens = tokens.filter((x) => x.id !== t.id); }
  async function addTrainer(id) { await api.post('/api/me/trainers', { trainer_id: Number(id) }); trainers = await api.get('/api/me/trainers'); toast('Trainer freigegeben', 'success'); }
  async function delTrainer(t) { await api.del(`/api/me/trainers/${t.id}`); trainers = trainers.filter((x) => x.id !== t.id); }
  async function togglePush() {
    try { if (pushOn) { await disablePush(); pushOn = false; } else { await enablePush(); pushOn = true; toast('Push aktiviert', 'success'); } } catch (e) { toastError(e); }
  }
  async function testPush() { const r = await api.post('/api/push/test'); toast(r.sent ? 'Test gesendet' : 'Kein Gerät registriert'); }
  async function importFile(e) {
    const f = e.currentTarget.files?.[0]; if (!f) return;
    const fd = new FormData(); fd.append('file', f);
    try { const r = await api.upload('/api/me/import', fd); toast(`Importiert: ${Object.values(r.imported).reduce((a, b) => a + b, 0)} Datensätze`, 'success'); } catch (err) { toastError(err); }
  }
  async function deleteAccount() {
    const confirm_ = prompt('Konto und ALLE Daten unwiderruflich löschen? Zum Bestätigen „LÖSCHEN“ eingeben.');
    if (confirm_ !== 'LÖSCHEN') return;
    const password = session.user.has_password ? prompt('Passwort zur Bestätigung') : null;
    try { await api.del('/api/me', { confirm: confirm_, password }); location.href = '/login'; } catch (e) { toastError(e); }
  }
  const ACCENTS = ['#22c55e', '#3b82f6', '#8b5cf6', '#ec4899', '#f97316', '#ef4444', '#14b8a6', '#eab308'];
  const NUTRIENTS = [['kcal', 'Kalorien'], ['protein', 'Protein'], ['carbs', 'Kohlenhydrate'], ['fat', 'Fett'], ['fiber', 'Ballaststoffe'], ['water', 'Wasser']];
  const PROACTIVE = [['plateau', 'Plateau erkannt'], ['protein_low', 'Protein mehrere Tage unter Ziel'], ['missed_training', 'Training ausgelassen'], ['new_pr', 'Neue PRs'], ['deload', 'Deload empfohlen']];
  const TASKS = { chat: 'Chat', vision: 'Foto-Erkennung', weekly_report: 'Wochen-/Monatsbericht', summary: 'Zusammenfassungen', briefing: 'Briefings', meal_plan: 'Mahlzeitenplanung' };
</script>

<Header title={TABS[tab]} back="/profile" />
<div class="px-4">
  <div class="no-scrollbar -mx-4 mb-4 flex gap-1.5 overflow-x-auto px-4">
    {#each Object.entries(TABS) as [k, l]}<button class={tab === k ? 'chip-active' : 'chip'} onclick={() => (tab = k)}>{l}</button>{/each}
  </div>

  {#if tab === 'profile' && profile}
    <div class="space-y-3">
      <label class="block"><span class="label">Anzeigename</span><input class="input" value={session.user.display_name} onchange={(e) => api.patch('/api/me', { display_name: e.currentTarget.value }).then(loadSession)} /></label>
      <div class="grid grid-cols-2 gap-2">
        <label><span class="label">Geschlecht</span><select class="input" bind:value={profile.sex}><option value="male">Männlich</option><option value="female">Weiblich</option></select></label>
        <label><span class="label">Geburtsdatum</span><input type="date" class="input" bind:value={profile.birth_date} /></label>
        <label><span class="label">Größe (cm)</span><input type="number" class="input" bind:value={profile.height_cm} /></label>
        <label><span class="label">Trainingstage/Woche</span><input type="number" min="0" max="7" class="input" bind:value={profile.training_days_per_week} /></label>
      </div>
      <label class="block"><span class="label">Aktivität</span><select class="input" bind:value={profile.activity_level}>
        <option value="sedentary">Sitzend</option><option value="light">Leicht aktiv</option><option value="moderate">Mäßig aktiv</option><option value="active">Sehr aktiv</option><option value="very_active">Extrem aktiv</option></select></label>
      <div><span class="label">Ziel</span><div class="grid grid-cols-3 gap-2">{#each Object.entries(GOALS) as [k, l]}<button class={profile.goal === k ? 'btn-primary btn-sm' : 'btn-soft btn-sm'} onclick={() => (profile.goal = k)}>{l}</button>{/each}</div></div>
      <label class="flex items-center gap-2 text-sm"><input type="checkbox" class="h-5 w-5 accent-[var(--accent)]" bind:checked={custom.enabled} /> Eigene Makroziele festlegen</label>
      {#if custom.enabled}
        {#each [['training', 'Trainingstag'], ['rest', 'Ruhetag']] as [k, l]}
          <p class="section-title">{l}</p>
          <div class="grid grid-cols-4 gap-1 text-xs">{#each [['kcal', 'kcal'], ['protein', 'Protein'], ['carbs', 'KH'], ['fat', 'Fett']] as [m, ml]}<label>{ml}<input class="input px-1 py-2 text-center" type="number" bind:value={custom[k][m]} /></label>{/each}</div>
        {/each}
        <p class="text-xs text-muted">Untergrenzen werden automatisch erzwungen (keine Crash-Diäten).</p>
      {/if}
      <button class="btn-primary w-full" onclick={saveProfile}>Speichern & neu berechnen</button>
      {#if targets}
        <div class="card grid grid-cols-2 gap-2 text-center text-sm">
          <div><div class="text-xs text-muted">Trainingstag</div><div class="font-bold">{targets.training.kcal} kcal</div><div class="text-xs">{targets.training.protein} P · {targets.training.carbs} K · {targets.training.fat} F</div></div>
          <div><div class="text-xs text-muted">Ruhetag</div><div class="font-bold">{targets.rest.kcal} kcal</div><div class="text-xs">{targets.rest.protein} P · {targets.rest.carbs} K · {targets.rest.fat} F</div></div>
          <div class="col-span-2 text-xs text-muted">Mifflin-St-Jeor: Grundumsatz {targets.bmr} kcal · Bedarf {targets.tdee} kcal · Untergrenzen {targets.floors.kcal} kcal / {targets.floors.protein} g Protein</div>
        </div>
      {/if}
    </div>

  {:else if tab === 'appearance'}
    <div class="space-y-4">
      <div><span class="label">Modus</span><div class="grid grid-cols-3 gap-2">{#each [['light', 'Hell'], ['dark', 'Dunkel'], ['system', 'System']] as [k, l]}<button class={s.theme.mode === k ? 'btn-primary btn-sm' : 'btn-soft btn-sm'} onclick={() => save({ theme: { mode: k } })}>{l}</button>{/each}</div></div>
      <div><span class="label">Akzentfarbe</span><div class="flex flex-wrap items-center gap-2">
        {#each ACCENTS as c}<button class="h-10 w-10 rounded-full {s.theme.accent === c ? 'ring-4 ring-offset-2 ring-offset-bg' : ''}" style="background:{c}; --tw-ring-color:{c}" onclick={() => save({ theme: { accent: c } })} aria-label={c}></button>{/each}
        <input type="color" class="h-10 w-12 rounded-lg" value={s.theme.accent} onchange={(e) => save({ theme: { accent: e.currentTarget.value } })} /></div></div>
      <div><span class="label">Darstellung</span><div class="grid grid-cols-3 gap-2">{#each [['compact', 'Kompakt'], ['comfortable', 'Normal'], ['large', 'Groß']] as [k, l]}<button class={s.theme.density === k ? 'btn-primary btn-sm' : 'btn-soft btn-sm'} onclick={() => save({ theme: { density: k } })}>{l}</button>{/each}</div></div>
      <div><span class="label">Makro-Farben</span><div class="grid grid-cols-4 gap-2">
        {#each [['protein', 'Protein'], ['carbs', 'KH'], ['fat', 'Fett'], ['fiber', 'Ballast.']] as [k, l]}<label class="text-center text-xs">{l}<input type="color" class="mt-1 h-10 w-full rounded-lg" value={s.theme.macro_colors?.[k]} onchange={(e) => save({ theme: { macro_colors: { [k]: e.currentTarget.value } } })} /></label>{/each}</div></div>
      <details class="card"><summary class="cursor-pointer text-sm font-medium">Farben pro Muskelgruppe</summary>
        <div class="mt-2 grid grid-cols-2 gap-2">{#each Object.entries(MUSCLES) as [k, l]}<label class="flex items-center justify-between gap-2 text-sm">{l}<input type="color" class="h-8 w-12 rounded" value={s.theme.muscle_colors?.[k] || '#22c55e'} onchange={(e) => save({ theme: { muscle_colors: { [k]: e.currentTarget.value } } })} /></label>{/each}</div></details>
      <p class="section-title">Einheiten</p>
      {#each [['weight', 'Gewicht', [['kg', 'kg'], ['lb', 'lb']]], ['distance', 'Distanz', [['km', 'km'], ['mi', 'mi']]], ['energy', 'Energie', [['kcal', 'kcal'], ['kJ', 'kJ']]]] as [k, l, opts]}
        <div class="flex items-center justify-between"><span>{l}</span><div class="flex gap-1">{#each opts as [v, vl]}<button class={s.units[k] === v ? 'chip-active' : 'chip'} onclick={() => save({ units: { [k]: v } })}>{vl}</button>{/each}</div></div>
      {/each}
      <p class="section-title">Pausen-Timer</p>
      <label class="flex items-center justify-between"><span>Standard-Pause (s)</span><input type="number" step="15" class="input w-24" value={s.rest_timer_default} onchange={(e) => save({ rest_timer_default: Number(e.currentTarget.value) })} /></label>
      <label class="flex items-center justify-between"><span>Vibration</span><input type="checkbox" class="h-6 w-6 accent-[var(--accent)]" checked={s.rest_timer_vibrate} onchange={(e) => save({ rest_timer_vibrate: e.currentTarget.checked })} /></label>
      <label class="flex items-center justify-between"><span>Push bei Ablauf (App im Hintergrund)</span><input type="checkbox" class="h-6 w-6 accent-[var(--accent)]" checked={s.rest_timer_push} onchange={(e) => save({ rest_timer_push: e.currentTarget.checked })} /></label>
    </div>

  {:else if tab === 'nutrition'}
    <div class="space-y-4">
      <div><span class="label">Mahlzeiten-Slots (Reihenfolge = Anzeige)</span>
        <div class="card p-0">{#each s.meal_slots as slot, i}
          <div class="list-row"><span class="flex-1">{slot}</span>
            <button class="text-muted" disabled={i === 0} onclick={() => { const a = [...s.meal_slots]; [a[i - 1], a[i]] = [a[i], a[i - 1]]; save({ meal_slots: a }); }} aria-label="Hoch">↑</button>
            <button class="text-danger" onclick={() => save({ meal_slots: s.meal_slots.filter((_, j) => j !== i) })} aria-label="Entfernen"><Icon name="x" size={16} /></button></div>{/each}
        </div>
        <form class="mt-2 flex gap-2" onsubmit={(e) => { e.preventDefault(); if (newSlot) { save({ meal_slots: [...s.meal_slots, newSlot] }); newSlot = ''; } }}>
          <input class="input" placeholder="Neuer Slot, z. B. Pre-Workout" bind:value={newSlot} /><button class="btn-soft"><Icon name="plus" /></button></form>
      </div>
      <div><span class="label">Angezeigte Nährwerte</span><div class="flex flex-wrap gap-1.5">
        {#each NUTRIENTS as [k, l]}<button class={s.visible_nutrients.includes(k) ? 'chip-active' : 'chip'} onclick={() => save({ visible_nutrients: s.visible_nutrients.includes(k) ? s.visible_nutrients.filter((x) => x !== k) : [...s.visible_nutrients, k] })}>{l}</button>{/each}</div></div>
      <label class="flex items-center justify-between"><span>Wasserziel (ml)</span><input type="number" step="250" class="input w-28" value={s.water_goal_ml} onchange={(e) => save({ water_goal_ml: Number(e.currentTarget.value) })} /></label>
    </div>

  {:else if tab === 'ai' && ai}
    <div class="space-y-4">
      <label class="card flex items-center justify-between"><div><div class="font-semibold">KI-Funktionen</div><div class="text-sm text-muted">{ai.available ? `Aktiv: ${ai.active?.provider} · ${ai.active?.model}` : ai.reason}</div></div>
        <input type="checkbox" class="h-6 w-6 accent-[var(--accent)]" checked={s.ai.enabled} onchange={(e) => save({ ai: { enabled: e.currentTarget.checked } })} /></label>
      <p class="text-sm text-muted">Verbrauch diesen Monat: <b>{ai.month_cost_usd.toFixed(3)} $</b> von {ai.limit_usd} $ Limit</p>
      <p class="section-title">Datenfreigaben – was darf an die KI?</p>
      {#each [['training', 'Training'], ['nutrition', 'Ernährung'], ['body', 'Körperwerte'], ['metrics', 'Eigene Metriken'], ['photos', 'Fotos']] as [k, l]}
        <label class="flex items-center justify-between rounded-xl bg-surface px-3 py-2.5"><span>{l}</span><input type="checkbox" class="h-6 w-6 accent-[var(--accent)]" checked={s.ai.consents[k]} onchange={(e) => save({ ai: { consents: { [k]: e.currentTarget.checked } } })} /></label>
      {/each}
      <label class="flex items-center justify-between rounded-xl bg-surface px-3 py-2.5"><span>Chat-Inhalte protokollieren (Debugging)</span><input type="checkbox" class="h-6 w-6 accent-[var(--accent)]" checked={s.ai.log_content} onchange={(e) => save({ ai: { log_content: e.currentTarget.checked } })} /></label>
      <p class="section-title">Provider & Modell</p>
      <div class="grid grid-cols-2 gap-2">
        <select class="input" value={s.ai.provider} onchange={(e) => save({ ai: { provider: e.currentTarget.value, model: '' } })}>
          <option value="">Standard (Admin)</option>{#each Object.entries(ai.providers) as [p, info]}<option value={p} disabled={!info.configured}>{p}{info.configured ? '' : ' (nicht eingerichtet)'}</option>{/each}</select>
        <div class="flex gap-1">
          {#if models[s.ai.provider]}<select class="input" value={s.ai.model} onchange={(e) => save({ ai: { model: e.currentTarget.value } })}><option value="">Standard</option>{#each models[s.ai.provider] as m}<option>{m}</option>{/each}</select>
          {:else}<input class="input" placeholder="Modell (Standard)" value={s.ai.model} onchange={(e) => save({ ai: { model: e.currentTarget.value } })} />
            {#if s.ai.provider}<button class="btn-soft px-3" onclick={() => loadModels(s.ai.provider)} title="Modelle laden"><Icon name="refresh" size={18} /></button>{/if}{/if}
        </div>
      </div>
      <label class="block"><span class="label">Temperatur: {s.ai.temperature} (wird von neueren Modellen ignoriert)</span><input type="range" min="0" max="1" step="0.1" class="w-full accent-[var(--accent)]" value={s.ai.temperature} onchange={(e) => save({ ai: { temperature: Number(e.currentTarget.value) } })} /></label>
      <div class="grid grid-cols-2 gap-2">
        <select class="input" value={s.ai.style_length} onchange={(e) => save({ ai: { style_length: e.currentTarget.value } })}><option value="short">Knapp</option><option value="detailed">Ausführlich</option></select>
        <select class="input" value={s.ai.style_tone} onchange={(e) => save({ ai: { style_tone: e.currentTarget.value } })}><option value="motivating">Motivierend</option><option value="factual">Sachlich</option></select>
      </div>
      <label class="flex items-center justify-between"><span>Automatischer Fallback auf anderen Provider</span><input type="checkbox" class="h-6 w-6 accent-[var(--accent)]" checked={s.ai.fallback} onchange={(e) => save({ ai: { fallback: e.currentTarget.checked } })} /></label>
      <details class="card"><summary class="cursor-pointer text-sm font-medium">Provider pro Aufgabe</summary>
        <div class="mt-2 space-y-2">{#each Object.entries(TASKS) as [task, l]}
          <div class="grid grid-cols-3 items-center gap-2 text-sm"><span>{l}</span>
            <select class="input py-1.5" value={s.ai.task_routing?.[task]?.provider || ''} onchange={(e) => save({ ai: { task_routing: { [task]: { provider: e.currentTarget.value, model: '' } } } })}>
              <option value="">Standard</option>{#each Object.keys(ai.providers) as p}<option>{p}</option>{/each}</select>
            <input class="input py-1.5" placeholder="Modell" value={s.ai.task_routing?.[task]?.model || ''} onchange={(e) => save({ ai: { task_routing: { [task]: { ...(s.ai.task_routing?.[task] || {}), model: e.currentTarget.value } } } })} />
          </div>{/each}</div></details>
      <p class="section-title">Eigene API-Keys (optional, verschlüsselt gespeichert)</p>
      {#each Object.entries(keys) as [p, masked]}<div class="flex items-center justify-between rounded-xl bg-surface px-3 py-2 text-sm"><span>{p}: {masked}</span><button class="text-danger" onclick={() => removeKey(p)}><Icon name="trash" size={16} /></button></div>{/each}
      <div class="flex gap-2"><select class="input w-32" bind:value={newKey.provider}><option value="anthropic">Anthropic</option><option value="openai">OpenAI</option></select>
        <input class="input" type="password" placeholder="sk-…" bind:value={newKey.key} /><button class="btn-soft" onclick={saveKey}><Icon name="check" /></button></div>
      <p class="section-title">Proaktive Hinweise</p>
      <label class="flex items-center justify-between"><span>Hinweise aktiv</span><input type="checkbox" class="h-6 w-6 accent-[var(--accent)]" checked={s.ai.proactive.enabled} onchange={(e) => save({ ai: { proactive: { enabled: e.currentTarget.checked } } })} /></label>
      {#each PROACTIVE as [k, l]}<label class="flex items-center justify-between pl-3 text-sm"><span>{l}</span><input type="checkbox" class="h-5 w-5 accent-[var(--accent)]" checked={s.ai.proactive[k]} onchange={(e) => save({ ai: { proactive: { [k]: e.currentTarget.checked } } })} /></label>{/each}
      <p class="section-title">Morgen-Briefing & Abend-Check-in</p>
      {#each [['morning', 'Morgen-Briefing'], ['evening', 'Abend-Check-in']] as [k, l]}
        <div class="flex items-center justify-between gap-2"><label class="flex items-center gap-2"><input type="checkbox" class="h-5 w-5 accent-[var(--accent)]" checked={s.ai.briefing[`${k}_enabled`]} onchange={(e) => save({ ai: { briefing: { [`${k}_enabled`]: e.currentTarget.checked } } })} />{l}</label>
          <input type="time" class="input w-32" value={s.ai.briefing[`${k}_time`]} onchange={(e) => save({ ai: { briefing: { [`${k}_time`]: e.currentTarget.value } } })} /></div>
      {/each}
    </div>

  {:else if tab === 'notifications'}
    <div class="space-y-3">
      {#if !isStandalone()}<p class="rounded-xl bg-warn/15 p-3 text-sm">Auf iPhone/iPad funktionieren Push-Benachrichtigungen nur, wenn FitForge über „Teilen → Zum Home-Bildschirm“ installiert ist (iOS 16.4+).</p>{/if}
      <label class="card flex items-center justify-between"><div><div class="font-semibold">Push auf diesem Gerät</div><div class="text-sm text-muted">{pushSupported() ? '' : 'Nicht unterstützt'}</div></div>
        <input type="checkbox" class="h-6 w-6 accent-[var(--accent)]" checked={pushOn} disabled={!pushSupported()} onchange={togglePush} /></label>
      {#each [['hints', 'Coach-Hinweise'], ['briefings', 'Briefings & Berichte'], ['timer', 'Pausen-Timer']] as [k, l]}
        <label class="flex items-center justify-between rounded-xl bg-surface px-3 py-2.5"><span>{l}</span><input type="checkbox" class="h-6 w-6 accent-[var(--accent)]" checked={s.ai.push[k]} onchange={(e) => save({ ai: { push: { [k]: e.currentTarget.checked } } })} /></label>
      {/each}
      <button class="btn-soft w-full" onclick={testPush}><Icon name="bell" size={18} /> Test-Benachrichtigung</button>
    </div>

  {:else if tab === 'security'}
    <div class="space-y-4">
      <div class="card space-y-2"><div class="font-semibold">Passkeys</div>
        {#each passkeys as p}<div class="flex justify-between text-sm"><span>{p.name} · {fmtDate(p.created_at)}</span><button class="text-danger" onclick={() => delPasskey(p)}><Icon name="trash" size={16} /></button></div>{/each}
        <button class="btn-soft w-full" disabled={!passkeysSupported()} onclick={addPasskey}><Icon name="lock" size={18} /> Passkey hinzufügen (Face ID / Touch ID)</button></div>
      <div class="card space-y-2"><div class="font-semibold">Zwei-Faktor (TOTP)</div>
        {#if session.user.totp_enabled}<p class="text-sm text-accent">Aktiv ✓</p><button class="btn-soft w-full" onclick={totpDisable}>Deaktivieren</button>
        {:else if totp}
          <p class="text-sm">Füge diesen Schlüssel in deiner Authenticator-App hinzu:</p>
          <code class="block break-all rounded-xl bg-surface-2 p-2 text-sm">{totp.secret}</code>
          <a class="text-sm text-accent" href={totp.uri}>In Authenticator-App öffnen</a>
          <input class="input text-center tracking-[0.3em]" inputmode="numeric" maxlength="6" placeholder="Code" bind:value={totpCode} />
          <button class="btn-primary w-full" onclick={totpEnable}>Aktivieren</button>
        {:else}<button class="btn-soft w-full" onclick={totpSetup}>2FA einrichten</button>{/if}</div>
      <div class="card space-y-2"><div class="font-semibold">Passwort ändern</div>
        {#if session.user.has_password}<input class="input" type="password" placeholder="Aktuelles Passwort" bind:value={pw.old} autocomplete="current-password" />{/if}
        <input class="input" type="password" placeholder="Neues Passwort (min. 10 Zeichen)" bind:value={pw.new} autocomplete="new-password" />
        <button class="btn-soft w-full" onclick={changePw}>Ändern</button></div>
    </div>

  {:else if tab === 'sharing'}
    <div class="space-y-3">
      <p class="text-sm text-muted">Gib einem Trainer Lesezugriff auf deine Daten. Er kann Kommentare hinterlassen, aber nichts ändern.</p>
      {#each trainers as t}<div class="card flex items-center justify-between py-3"><span>{t.display_name}</span><button class="text-danger" onclick={() => delTrainer(t)}>Entziehen</button></div>{/each}
      {#if directory.length}
        <select class="input" onchange={(e) => e.currentTarget.value && addTrainer(e.currentTarget.value)}><option value="">Trainer hinzufügen …</option>
          {#each directory.filter((d) => !trainers.some((t) => t.trainer_id === d.id)) as d}<option value={d.id}>{d.display_name}</option>{/each}</select>
      {:else}<p class="text-sm text-muted">Keine Trainer auf dieser Instanz.</p>{/if}
      <p class="text-sm text-muted">Pläne, Rezepte, eigene Lebensmittel und Übungen teilst du direkt über das <Icon name="share" size={14} class="inline" />-Symbol auf der jeweiligen Seite.</p>
    </div>

  {:else if tab === 'integrations'}
    <div class="space-y-3">
      <div class="card space-y-2"><div class="font-semibold">Persönliche API-Tokens</div>
        <p class="text-sm text-muted">Für Home Assistant, Apple-Kurzbefehle und eigene Skripte (Header <code>Authorization: Bearer …</code>).</p>
        {#if createdToken}<div class="rounded-xl bg-accent/10 p-2 text-sm">Neuer Token (nur jetzt sichtbar):<code class="mt-1 block break-all select-all">{createdToken.token}</code></div>{/if}
        {#each tokens as t}<div class="flex justify-between text-sm"><span>{t.name} · {t.prefix}… {t.last_used_at ? `· zuletzt ${fmtDate(t.last_used_at)}` : ''}</span><button class="text-danger" onclick={() => delToken(t)}><Icon name="trash" size={16} /></button></div>{/each}
        <button class="btn-soft w-full" onclick={createToken}><Icon name="plus" size={18} /> Token erstellen</button></div>
      <div class="card space-y-1 text-sm"><div class="font-semibold">Home Assistant</div>
        <p class="text-muted">REST-Sensor-URL:</p><code class="block break-all rounded bg-surface-2 p-2">{location.origin}/api/ha/summary</code>
        <p class="text-muted">Beispielkonfiguration siehe README.</p></div>
      <div class="card space-y-1 text-sm"><div class="font-semibold">Apple Health (Kurzbefehle)</div>
        <p class="text-muted">Automation „Täglich 21:00“ → „Inhalte von URL abrufen“ (POST, JSON) an:</p>
        <code class="block break-all rounded bg-surface-2 p-2">{location.origin}/api/integrations/apple-health/raw</code>
        <p class="text-muted">Felder: date, weight_kg, body_fat_pct, steps, sleep_hours, resting_hr, active_kcal, hrv_ms</p></div>
      <a class="btn-soft w-full" href="/api/docs" data-sveltekit-reload>OpenAPI-Dokumentation</a>
    </div>

  {:else if tab === 'data'}
    <div class="space-y-3">
      <a class="btn-soft w-full" href="/api/me/export" data-sveltekit-reload download><Icon name="download" size={18} /> Alle Daten als JSON exportieren</a>
      <a class="btn-soft w-full" href="/api/me/export?format=csv" data-sveltekit-reload download><Icon name="download" size={18} /> Als CSV (ZIP) exportieren</a>
      <label class="btn-soft w-full"><Icon name="share" size={18} /> FitForge-JSON importieren<input type="file" accept="application/json" class="hidden" onchange={importFile} /></label>
      <div class="card border-danger/40"><div class="font-semibold text-danger">Konto löschen</div>
        <p class="mb-2 text-sm text-muted">Löscht dein Konto und alle Daten unwiderruflich (Trainings, Ernährung, Fotos, Coach-Gedächtnis).</p>
        <button class="btn-danger w-full" onclick={deleteAccount}>Konto endgültig löschen</button></div>
    </div>
  {/if}
</div>
