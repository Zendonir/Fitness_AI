# FitForge – Architektur, Datenmodell & Rechtekonzept

## Überblick

```
iPhone/iPad (PWA)  ──HTTPS──▶  Nginx Proxy Manager  ──HTTP──▶  fitforge-app (FastAPI + statisches SvelteKit)
                                                                   │            │
                                                                   ▼            ▼
                                                             PostgreSQL 16    Redis 7 ◀── fitforge-worker (arq)
                                                                                           │
                                                          Anthropic / OpenAI / Ollama ◀────┘ (Zusammenfassungen, Briefings,
                                                                                              Hinweise, Push, Backups)
```

* **Ein Image, zwei Rollen**: `fitforge-app` (uvicorn, liefert API **und** das statisch gebaute
  Frontend unter `/`) und `fitforge-worker` (arq, Cron-Jobs). Beide nutzen denselben Code.
* **Frontend**: SvelteKit mit `adapter-static` (SPA-Fallback `index.html`), TailwindCSS, ECharts,
  ZXing, Service Worker mit Offline-Queue (IndexedDB).
* **Backend**: FastAPI, SQLModel (SQLAlchemy 2 async, asyncpg), Alembic, arq/Redis.
* **Netzwerk**: `macvlan` gibt der App eine eigene LAN-IP; ein zusätzliches Bridge-Netz
  (`fitforge_proxy`) verbindet die App mit Nginx Proxy Manager, weil macvlan-Container den Host
  (und damit NPM auf dem Host) nicht direkt erreichen. Postgres/Redis hängen nur im internen Netz.

## Backend-Module

| Paket | Zweck |
|---|---|
| `app/core` | Konfiguration, DB-Engine, Sicherheit (Argon2, Sessions, API-Tokens, Fernet) |
| `app/models` | SQLModel-Tabellen |
| `app/api` | REST-Router (alle unter `/api`) |
| `app/services` | Fachlogik: Makro-Rechner, Progression, Statistik, Open Food Facts, GPX/CSV, Export, Push, Backup |
| `app/ai` | Provider-Abstraktion (Anthropic, OpenAI, Ollama), Kosten, Kontextaufbau, Tools, Gedächtnis, Coach |
| `app/worker.py` | arq-Worker mit Cron-Jobs |
| `app/seed` | Übungen, Planvorlagen, Muskel-SVG-Mapping, Standard-Systemprompt |

## Datenmodell (Kurzform)

**Benutzer & System**
`user` (Rolle admin/user/trainer, Argon2-Hash, TOTP, OIDC-Sub, Sperre, KI-Limit) ·
`user_settings` (JSON: Einheiten, Theme, Farben, Sprache, Mahlzeiten-Slots, KI, Datenfreigaben, …) ·
`user_profile` (Körperdaten/Ziel für den Makro-Rechner) · `session` · `api_token` · `invite` ·
`password_reset` · `webauthn_credential` · `audit_log` · `app_setting` (globale Schalter, verschlüsselte
globale Keys, Standardwerte) · `trainer_link` · `trainer_comment` · `share_grant` · `push_subscription`

**Training**
`exercise` (global oder eigene, Muskeln, Equipment, eigene Felder, Progressionsregel) ·
`plan` → `plan_day` → `plan_exercise` (Wochen, Deload-Wochen, Supersatz-Gruppen) ·
`workout` → `workout_set` (Wdh., Gewicht, RPE, Aufwärmsatz, eigene Felder) · `cardio_session`

**Ernährung & Körper**
`food` (OFF-Cache global, eigene Lebensmittel) · `recipe` → `recipe_ingredient` · `meal_entry`
(Nährwert-Snapshot) · `favorite` · `day_template` · `water_entry` · `body_measurement` ·
`progress_photo` · `metric_definition` → `metric_entry` · `dashboard`

**KI-Coach**
`coach_profile` · `coach_note` (Langzeitgedächtnis) · `coach_summary` (Tag/Woche/Monat) ·
`chat_conversation` → `chat_message` · `pending_action` (bestätigungspflichtige Schreib-Tools) ·
`coach_hint` (proaktive Hinweise) · `ai_usage` (Provider, Modell, Tokens, Kosten, Dauer, optional Inhalt) ·
`user_ai_key` (verschlüsselt) · `prompt_template` (versioniert) · `meal_plan`

## Rechtekonzept

| Rolle | Rechte |
|---|---|
| **admin** | alles; Benutzerverwaltung, globale Vorlagen, Systemprompt, KI-Keys, Limits, Audit-Log |
| **user** | eigene Daten (CRUD), geteilte Ressourcen lesen/kopieren |
| **trainer** | wie user + Lesezugriff und Kommentare für Benutzer, die ihn explizit freigegeben haben (`trainer_link`) |

Regeln:

1. **Jede** Abfrage auf benutzerbezogene Tabellen läuft über `owned(select(Model), user)` bzw.
   `get_owned()` (siehe `app/core/access.py`) und filtert auf `user_id`. Fremde IDs liefern **404**
   (keine Existenz-Leaks).
2. Teilbare Ressourcen (`plan`, `recipe`, `food`, `exercise`) haben `visibility` ∈
   `private | shared | public` und optional `share_grant`-Einträge. Lesen = Eigentümer ∨ `public` ∨
   Grant ∨ globaler Eintrag (`owner_id IS NULL`). Schreiben = nur Eigentümer (globale nur Admin).
3. Der KI-Coach ruft Tools **immer** mit dem User-Kontext des Anfragenden auf – es gibt keinen
   `user_id`-Parameter im Tool-Schema. Schreibende Tools erzeugen nur eine `pending_action`,
   ausgeführt wird erst nach Bestätigung durch denselben Benutzer.
4. Sensible Kategorien (Körperwerte, Fotos, eigene Metriken, Ernährung) gehen nur an die KI, wenn
   `settings.ai.consents.<kategorie>` aktiv ist.
5. Authentifizierung: Session-Cookie (`ff_session`, httpOnly, SameSite=Lax, Secure hinter HTTPS)
   oder `Authorization: Bearer ff_…` (persönlicher API-Token, SHA-256-Hash in der DB).
6. Mutierende Requests mit Cookie-Auth benötigen den Header `X-Requested-With: fitforge` (CSRF-Schutz).

## KI-Leitplanken (technisch)

* `app/services/nutrition.py` definiert **harte Untergrenzen** (kcal ≥ max(1200/1500, BMR), Defizit
  ≤ 20 %, Protein ≥ 1,2 g/kg). `set_nutrition_goal` validiert KI-Vorschläge gegen dieselbe Funktion.
* Systemprompt enthält Regeln (keine Diagnosen, Arztverweis, keine Crash-Diäten); versioniert in
  `prompt_template`.
* Kostenlimit wird **vor** jedem Aufruf geprüft (`app/ai/usage.py`).
* Globaler Schalter `ai_enabled` + pro Benutzer `settings.ai.enabled`. Ohne KI bleiben alle
  anderen Funktionen voll nutzbar.
