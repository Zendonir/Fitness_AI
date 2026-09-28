<script>
  import { MUSCLES } from '$lib/units.js';
  // values: { muscle: Sätze pro Woche }
  let { values = {}, size = 150, onselect = null, selected = null } = $props();

  // Empfohlene Wochensätze: <4 wenig, 4-10 moderat, 10-20 optimal, >20 sehr hoch
  function color(m) {
    const v = values[m] || 0;
    if (!v) return 'var(--surface-2)';
    if (v < 4) return 'color-mix(in srgb, var(--accent) 30%, var(--surface-2))';
    if (v < 10) return 'color-mix(in srgb, var(--accent) 60%, var(--surface-2))';
    if (v <= 20) return 'var(--accent)';
    return 'var(--warn)';
  }
  const front = [
    ['traps', 'M84 58 L100 52 L116 58 L112 70 L88 70 Z'],
    ['front_delts', 'M62 78 C66 68 78 66 86 72 L82 96 C72 98 64 92 62 78 Z'],
    ['front_delts', 'M138 78 C134 68 122 66 114 72 L118 96 C128 98 136 92 138 78 Z'],
    ['side_delts', 'M56 84 C56 74 60 70 64 72 L66 98 C60 98 56 92 56 84 Z'],
    ['side_delts', 'M144 84 C144 74 140 70 136 72 L134 98 C140 98 144 92 144 84 Z'],
    ['chest', 'M86 74 L99 76 L99 116 C90 120 78 116 76 106 L80 88 Z'],
    ['chest', 'M114 74 L101 76 L101 116 C110 120 122 116 124 106 L120 88 Z'],
    ['biceps', 'M58 102 C64 100 70 102 72 110 L68 148 C62 150 56 146 54 138 Z'],
    ['biceps', 'M142 102 C136 100 130 102 128 110 L132 148 C138 150 144 146 146 138 Z'],
    ['forearms', 'M54 150 L68 152 L64 200 L52 198 C48 184 50 162 54 150 Z'],
    ['forearms', 'M146 150 L132 152 L136 200 L148 198 C152 184 150 162 146 150 Z'],
    ['abs', 'M88 120 L112 120 L112 196 C106 202 94 202 88 196 Z'],
    ['obliques', 'M76 118 L86 122 L86 194 L78 186 C74 160 74 136 76 118 Z'],
    ['obliques', 'M124 118 L114 122 L114 194 L122 186 C126 160 126 136 124 118 Z'],
    ['quads', 'M76 212 C84 206 96 208 98 216 L96 300 C88 306 80 302 76 294 C70 266 70 236 76 212 Z'],
    ['quads', 'M124 212 C116 206 104 208 102 216 L104 300 C112 306 120 302 124 294 C130 266 130 236 124 212 Z'],
    ['adductors', 'M98 216 L100 212 L102 216 L102 262 L98 262 Z'],
    ['calves', 'M78 318 C84 312 94 314 94 322 L92 380 C86 384 80 380 78 372 C74 356 74 334 78 318 Z'],
    ['calves', 'M122 318 C116 312 106 314 106 322 L108 380 C114 384 120 380 122 372 C126 356 126 334 122 318 Z']
  ];
  const back = [
    ['traps', 'M100 50 L122 66 L112 104 L100 112 L88 104 L78 66 Z'],
    ['rear_delts', 'M60 80 C62 70 72 66 80 70 L80 94 C70 98 62 92 60 80 Z'],
    ['rear_delts', 'M140 80 C138 70 128 66 120 70 L120 94 C130 98 138 92 140 80 Z'],
    ['upper_back', 'M82 74 L88 104 L100 114 L100 124 L84 118 L78 92 Z'],
    ['upper_back', 'M118 74 L112 104 L100 114 L100 124 L116 118 L122 92 Z'],
    ['lats', 'M78 96 L86 122 L98 128 L96 168 C88 164 80 152 76 138 C72 122 74 106 78 96 Z'],
    ['lats', 'M122 96 L114 122 L102 128 L104 168 C112 164 120 152 124 138 C128 122 126 106 122 96 Z'],
    ['lower_back', 'M90 168 L98 170 L98 200 L86 200 Z'],
    ['lower_back', 'M110 168 L102 170 L102 200 L114 200 Z'],
    ['triceps', 'M58 100 C64 98 70 100 72 108 L70 148 C62 150 56 146 54 138 Z'],
    ['triceps', 'M142 100 C136 98 130 100 128 108 L130 148 C138 150 144 146 146 138 Z'],
    ['forearms', 'M54 150 L68 152 L64 200 L52 198 C48 184 50 162 54 150 Z'],
    ['forearms', 'M146 150 L132 152 L136 200 L148 198 C152 184 150 162 146 150 Z'],
    ['glutes', 'M78 206 C86 198 98 202 99 212 L98 242 C88 248 78 244 76 234 Z'],
    ['glutes', 'M122 206 C114 198 102 202 101 212 L102 242 C112 248 122 244 124 234 Z'],
    ['hamstrings', 'M76 248 C84 246 96 248 98 254 L96 304 C88 308 80 304 78 296 C74 280 74 262 76 248 Z'],
    ['hamstrings', 'M124 248 C116 246 104 248 102 254 L104 304 C112 308 120 304 122 296 C126 280 126 262 124 248 Z'],
    ['calves', 'M78 316 C86 308 96 312 96 322 L92 370 C86 376 80 372 78 364 C74 348 74 332 78 316 Z'],
    ['calves', 'M122 316 C114 308 104 312 104 322 L108 370 C114 376 120 372 122 364 C126 348 126 332 122 316 Z']
  ];
  const silhouette = 'M100 12 C111 12 118 20 118 32 C118 44 111 52 100 52 C89 52 82 44 82 32 C82 20 89 12 100 12 Z M86 54 L114 54 L140 68 C150 74 150 90 148 100 L154 150 L152 204 L144 204 L136 150 L128 116 L128 200 L132 300 L128 390 L106 392 L102 262 L98 262 L94 392 L72 390 L68 300 L72 200 L72 116 L64 150 L56 204 L48 204 L46 150 L52 100 C50 90 50 74 60 68 Z';
</script>

<div class="flex justify-center gap-2">
  {#each [['Vorne', front], ['Hinten', back]] as [label, parts]}
    <div class="flex flex-col items-center">
      <svg viewBox="40 6 120 392" width={size} height={size * 2.6} role="img" aria-label="Muskelkarte {label}">
        <path d={silhouette} fill="var(--surface-2)" opacity="0.55" />
        {#each parts as [m, d]}
          <path {d} fill={color(m)} stroke={selected === m ? 'var(--text)' : 'var(--bg)'} stroke-width={selected === m ? 2 : 1}
            class="cursor-pointer transition-[fill] duration-500" role="button" tabindex="-1"
            onclick={() => onselect?.(m)} onkeydown={() => {}}>
            <title>{MUSCLES[m]}: {values[m] ?? 0} Sätze</title>
          </path>
        {/each}
      </svg>
      <span class="text-xs text-muted">{label}</span>
    </div>
  {/each}
</div>
