<script>
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { api } from '$lib/api.js';
  import { loadSession, session } from '$lib/session.svelte.js';
  import { toast, toastError } from '$lib/toast.svelte.js';
  import { GOALS } from '$lib/units.js';
  import { enablePush, isStandalone, pushSupported } from '$lib/push.js';
  import Icon from '$components/Icon.svelte';

  let step = $state(0);
  const steps = ['Willkommen', 'Körperdaten', 'Ziel', 'Trainingsplan', 'Coach-Profil', 'KI & Datenschutz', 'Fertig'];
  let profile = $state({ sex: 'male', birth_date: '1995-01-01', height_cm: 178, weight_kg: 78, activity_level: 'moderate', goal: 'maintain', training_days_per_week: 3 });
  let coach = $state({ experience: 'beginner', goals: '', equipment: 'Fitnessstudio', limitations: '', schedule: '', preferences: '', dislikes: '' });
  let ai = $state({ enabled: true, consents: { training: true, nutrition: true, body: false, metrics: false, photos: false }, style_length: 'short', style_tone: 'motivating' });
  let name = $state(session.user?.display_name || '');
  let plans = $state([]);
  let planId = $state(null);
  let preview = $state(null);
  let busy = $state(false);
  let aiStatus = $state(null);

  onMount(async () => {
    plans = (await api.get('/api/plans')).filter((p) => p.kind === 'template');
    aiStatus = await api.get('/api/coach/status').catch(() => null);
  });

  const activity = { sedentary: 'Sitzend (Büro, kaum Bewegung)', light: 'Leicht aktiv (1–3× Sport)', moderate: 'Mäßig aktiv (3–5× Sport)', active: 'Sehr aktiv (6–7× Sport)', very_active: 'Extrem aktiv (körperliche Arbeit + Sport)' };

  async function calcPreview() {
    try {
      await api.put('/api/me/profile', profile);
      preview = (await api.get('/api/me/profile')).targets;
    } catch (e) { toastError(e); }
  }
  $effect(() => { if (step === 2) calcPreview(); });

  async function finish() {
    busy = true;
    try {
      if (name) await api.patch('/api/me', { display_name: name });
      await api.post('/api/me/onboarding', { profile, coach, plan_template_id: planId, settings: { ai } });
      await loadSession();
      step = 6;
    } catch (e) { toastError(e); } finally { busy = false; }
  }
</script>

<div class="safe-top flex min-h-dvh flex-col px-5 pb-8">
  <div class="mb-6 flex gap-1 pt-2">
    {#each steps as _, i}<div class="h-1.5 flex-1 rounded-full {i <= step ? 'bg-accent' : 'bg-surface-2'}"></div>{/each}
  </div>
  <h1 class="mb-1 text-2xl font-bold">{steps[step]}</h1>

  <div class="flex-1 space-y-4 pt-3">
    {#if step === 0}
      <p class="text-muted">Schön, dass du da bist! In wenigen Schritten richten wir FitForge für dich ein: Ziele, Körperdaten, Trainingsplan und deinen KI-Coach.</p>
      <label class="block"><span class="label">Wie sollen wir dich nennen?</span><input class="input" bind:value={name} /></label>
    {:else if step === 1}
      <div class="grid grid-cols-2 gap-2">
        {#each [['male', 'Männlich'], ['female', 'Weiblich']] as [v, l]}
          <button class={profile.sex === v ? 'btn-primary' : 'btn-soft'} onclick={() => (profile.sex = v)}>{l}</button>
        {/each}
      </div>
      <label class="block"><span class="label">Geburtsdatum</span><input type="date" class="input" bind:value={profile.birth_date} /></label>
      <div class="grid grid-cols-2 gap-3">
        <label><span class="label">Größe (cm)</span><input class="input" inputmode="decimal" type="number" bind:value={profile.height_cm} /></label>
        <label><span class="label">Gewicht (kg)</span><input class="input" inputmode="decimal" type="number" step="0.1" bind:value={profile.weight_kg} /></label>
      </div>
      <span class="label">Alltag & Aktivität</span>
      {#each Object.entries(activity) as [v, l]}
        <button class="w-full rounded-2xl border p-3 text-left {profile.activity_level === v ? 'border-accent bg-accent/10' : 'border-line bg-surface'}"
          onclick={() => (profile.activity_level = v)}>{l}</button>
      {/each}
    {:else if step === 2}
      {#each Object.entries(GOALS) as [v, l]}
        <button class="w-full rounded-2xl border p-4 text-left {profile.goal === v ? 'border-accent bg-accent/10' : 'border-line bg-surface'}"
          onclick={() => { profile.goal = v; calcPreview(); }}>
          <div class="font-semibold">{l}</div>
          <div class="text-sm text-muted">{v === 'bulk' ? '+10 % über Bedarf – Muskelaufbau mit wenig Fettzuwachs' : v === 'cut' ? '−15 % unter Bedarf – nachhaltiger Fettabbau, Muskelerhalt' : 'Gewicht halten, Leistung steigern'}</div>
        </button>
      {/each}
      <label class="block"><span class="label">Trainingstage pro Woche: {profile.training_days_per_week}</span>
        <input type="range" min="1" max="7" class="w-full accent-[var(--accent)]" bind:value={profile.training_days_per_week} onchange={calcPreview} /></label>
      {#if preview}
        <div class="card grid grid-cols-2 gap-3 text-center">
          <div><div class="text-xs text-muted">Trainingstag</div><div class="text-xl font-bold">{preview.training.kcal} kcal</div>
            <div class="text-xs text-muted">{preview.training.protein} P · {preview.training.carbs} K · {preview.training.fat} F</div></div>
          <div><div class="text-xs text-muted">Ruhetag</div><div class="text-xl font-bold">{preview.rest.kcal} kcal</div>
            <div class="text-xs text-muted">{preview.rest.protein} P · {preview.rest.carbs} K · {preview.rest.fat} F</div></div>
          <div class="col-span-2 text-xs text-muted">Grundumsatz {preview.bmr} kcal · Bedarf {preview.tdee} kcal · Untergrenze {preview.floors.kcal} kcal</div>
        </div>
      {/if}
    {:else if step === 3}
      <p class="text-sm text-muted">Wähle eine Vorlage – du kannst sie später frei anpassen.</p>
      {#each plans as p}
        <button class="w-full rounded-2xl border p-4 text-left {planId === p.id ? 'border-accent bg-accent/10' : 'border-line bg-surface'}" onclick={() => (planId = p.id)}>
          <div class="font-semibold">{p.name}</div><div class="text-sm text-muted">{p.description}</div>
        </button>
      {/each}
      <button class="w-full rounded-2xl border p-4 text-left {planId === null ? 'border-accent bg-accent/10' : 'border-line bg-surface'}" onclick={() => (planId = null)}>
        <div class="font-semibold">Ohne Plan starten</div><div class="text-sm text-muted">Freies Training oder später eigenen Plan erstellen</div>
      </button>
    {:else if step === 4}
      <span class="label">Erfahrung</span>
      <div class="grid grid-cols-3 gap-2">
        {#each [['beginner', 'Einsteiger'], ['intermediate', 'Fortgeschritten'], ['advanced', 'Profi']] as [v, l]}
          <button class={coach.experience === v ? 'btn-primary btn-sm' : 'btn-soft btn-sm'} onclick={() => (coach.experience = v)}>{l}</button>
        {/each}
      </div>
      <label class="block"><span class="label">Deine Ziele</span><textarea class="input" rows="2" placeholder="z. B. 100 kg Bankdrücken, 5 kg abnehmen" bind:value={coach.goals}></textarea></label>
      <label class="block"><span class="label">Verfügbares Equipment</span><input class="input" bind:value={coach.equipment} /></label>
      <label class="block"><span class="label">Einschränkungen / Verletzungen</span><input class="input" placeholder="z. B. Knie links empfindlich" bind:value={coach.limitations} /></label>
      <label class="block"><span class="label">Trainingszeiten</span><input class="input" placeholder="z. B. Mo/Mi/Fr abends, max. 60 min" bind:value={coach.schedule} /></label>
      <label class="block"><span class="label">Ernährungsvorlieben / Abneigungen</span><input class="input" placeholder="z. B. vegetarisch, kein Fisch" bind:value={coach.preferences} /></label>
    {:else if step === 5}
      <label class="card flex items-center justify-between">
        <div><div class="font-semibold">KI-Coach aktivieren</div><div class="text-sm text-muted">Die App funktioniert auch komplett ohne KI.</div></div>
        <input type="checkbox" class="h-6 w-6 accent-[var(--accent)]" bind:checked={ai.enabled} />
      </label>
      {#if aiStatus && !aiStatus.available && ai.enabled}
        <p class="rounded-xl bg-warn/15 p-3 text-sm">Noch kein KI-Provider eingerichtet. Du kannst später unter Einstellungen → KI einen eigenen API-Key hinterlegen oder der Admin richtet einen globalen ein.</p>
      {/if}
      {#if ai.enabled}
        <p class="section-title">Was darf der Coach sehen?</p>
        {#each [['training', 'Training', 'Workouts, Sätze, Pläne, PRs'], ['nutrition', 'Ernährung', 'Mahlzeiten, Makros, Ziele'], ['body', 'Körperwerte', 'Gewicht, Umfänge, Alter, Größe'], ['metrics', 'Eigene Metriken', 'Schlaf, Stimmung, Schritte …'], ['photos', 'Fotos', 'Mahlzeiten- und Etikettenfotos zur Erkennung']] as [k, l, d]}
          <label class="flex items-center justify-between rounded-2xl bg-surface p-3">
            <div><div class="font-medium">{l}</div><div class="text-xs text-muted">{d}</div></div>
            <input type="checkbox" class="h-6 w-6 accent-[var(--accent)]" bind:checked={ai.consents[k]} />
          </label>
        {/each}
        <p class="section-title">Antwortstil</p>
        <div class="grid grid-cols-2 gap-2">
          <button class={ai.style_length === 'short' ? 'btn-primary btn-sm' : 'btn-soft btn-sm'} onclick={() => (ai.style_length = 'short')}>Knapp</button>
          <button class={ai.style_length === 'detailed' ? 'btn-primary btn-sm' : 'btn-soft btn-sm'} onclick={() => (ai.style_length = 'detailed')}>Ausführlich</button>
          <button class={ai.style_tone === 'motivating' ? 'btn-primary btn-sm' : 'btn-soft btn-sm'} onclick={() => (ai.style_tone = 'motivating')}>Motivierend</button>
          <button class={ai.style_tone === 'factual' ? 'btn-primary btn-sm' : 'btn-soft btn-sm'} onclick={() => (ai.style_tone = 'factual')}>Sachlich</button>
        </div>
      {/if}
    {:else}
      <div class="py-6 text-center"><div class="mx-auto mb-4 w-fit rounded-full bg-accent/15 p-5 text-accent"><Icon name="check" size={40} /></div>
        <p class="text-lg font-semibold">Alles bereit, {name || 'Champion'}!</p></div>
      {#if !isStandalone()}
        <div class="card text-sm"><p class="font-semibold">📱 Als App installieren</p>
          <p class="text-muted">iPhone/iPad: In Safari auf „Teilen“ → „Zum Home-Bildschirm“ tippen. Danach funktionieren auch Push-Benachrichtigungen.</p></div>
      {/if}
      {#if pushSupported()}
        <button class="btn-soft w-full" onclick={() => enablePush().then(() => toast('Push aktiviert ✓', 'success')).catch(toastError)}>
          <Icon name="bell" size={18} /> Benachrichtigungen aktivieren</button>
      {/if}
    {/if}
  </div>

  <div class="mt-6 flex gap-2">
    {#if step > 0 && step < 6}<button class="btn-soft" onclick={() => step--}><Icon name="back" /></button>{/if}
    {#if step < 5}
      <button class="btn-primary flex-1" onclick={() => step++}>Weiter</button>
    {:else if step === 5}
      <button class="btn-primary flex-1" disabled={busy} onclick={finish}>Einrichtung abschließen</button>
    {:else}
      <button class="btn-primary flex-1" onclick={() => goto('/', { replaceState: true })}>Los geht's</button>
    {/if}
  </div>
</div>
