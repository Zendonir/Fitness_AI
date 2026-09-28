# FitForge 🏋️

**Self-hosted Trainings- & Ernährungstracker mit KI-Coach für mehrere Benutzer.**
Läuft als Custom App auf TrueNAS Scale und als PWA auf dem iPhone/iPad (sekundär am Desktop).

- **Training:** 82 Übungen mit Muskel-Grafik, 3 Planvorlagen (Ganzkörper 3×, Upper/Lower 4×, PPL 6×), Plan-Editor mit Drag & Drop, Deload-Wochen, Live-Workout mit Pausen-Timer, Supersätzen und Vorwerten, Double Progression, PR-Erkennung, Ausdauer mit GPX/CSV-Import
- **Ernährung:** Open-Food-Facts-Suche mit lokalem Cache, Barcode-Scanner (iPhone-Kamera), eigene Lebensmittel und Rezepte, Mahlzeiten-Slots, „Vortag kopieren“, Favoriten, Vorlagen-Tage, Wasser, Makroziele nach Mifflin-St-Jeor mit festen Untergrenzen
- **Visualisierung:** „Heute“-Dashboard als Baukasten (mehrere Dashboards), Muskel-Heatmap, 1RM-Verlauf, Kalender-Heatmap, Wochenvolumen, Ernährungsauswertung, Korrelationen, Wochen- und Monatsberichte, Export als PNG/CSV
- **KI-Coach:** Anthropic (Claude), OpenAI und Ollama mit Fallback, Kostenlimit, Gedächtnis, Tool-Calling mit Bestätigungsdialog, proaktive Hinweise, Briefings, Web-Push, Foto-Erkennung, Mahlzeitenplanung – und komplett abschaltbar
- **Mehrbenutzer:** Rollen Admin, Benutzer und Trainer, Einladungslinks, Passkeys, TOTP-2FA, optional OIDC (z. B. Authentik), strikte Datentrennung, Teilen, Export/Import, Konto löschen
- **Integration:** REST-API mit persönlichen Tokens (OpenAPI unter `/api/docs`), Home-Assistant-Sensoren, Apple-Health-Import über Kurzbefehle, nächtliche `pg_dump`-Backups

Architektur, Datenmodell und Rechtekonzept stehen in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Inhalt

1. [Schnellstart](#1-schnellstart)
2. [TrueNAS Scale: Custom App einrichten](#2-truenas-scale-custom-app-einrichten)
3. [Nginx Proxy Manager (HTTPS)](#3-nginx-proxy-manager-https)
4. [Pi-hole: lokaler DNS-Eintrag (Split-DNS)](#4-pi-hole-lokaler-dns-eintrag-split-dns)
5. [Erster Admin-Login & Benutzer einladen](#5-erster-admin-login--benutzer-einladen)
6. [iPhone/iPad: PWA installieren & Push aktivieren](#6-iphoneipad-pwa-installieren--push-aktivieren)
7. [KI-Provider einrichten](#7-ki-provider-einrichten)
8. [Home Assistant](#8-home-assistant)
9. [Apple Health über Kurzbefehle](#9-apple-health-über-kurzbefehle)
10. [Backup & Restore](#10-backup--restore)
11. [Updates](#11-updates)
12. [Entwicklung & Tests](#12-entwicklung--tests)
13. [Fehlerbehebung](#13-fehlerbehebung)

---

## 1. Schnellstart

Voraussetzungen: Docker mit Compose v2.

```bash
git clone https://github.com/zendonir/fitness_ai.git fitforge && cd fitforge
cp .env.example .env

# Schlüssel erzeugen und die Ausgabe in die .env übernehmen
docker run --rm ghcr.io/zendonir/fitness_ai:latest python -m app.cli gen-keys
```

Das Image `ghcr.io/zendonir/fitness_ai` baut die GitHub Action `.github/workflows/docker.yml` für amd64 und arm64.
Alternativ baust du es lokal: `docker compose build`. Mehr dazu unter [Updates](#11-updates).

**Zum Testen ohne macvlan**, direkt auf Port 8000:

```bash
docker compose -f docker-compose.yml -f docker-compose.bridge.yml up -d
# → http://<server-ip>:8000
```

**Produktiv mit macvlan** (eigene LAN-IP): zuerst `MACVLAN_PARENT`, `LAN_SUBNET`, `LAN_GATEWAY`, `LAN_IP_RANGE` und `APP_IP` in der `.env` setzen, dann:

```bash
docker compose up -d
```

Die App startet vier Container:

| Container | Aufgabe |
|---|---|
| `fitforge-app` | API und Web-Oberfläche. Führt beim Start die Datenbank-Migrationen aus. |
| `fitforge-worker` | Hintergrundjobs: Zusammenfassungen, Berichte, Hinweise, Briefings, Push, Backups |
| `fitforge-postgres` | PostgreSQL 16 |
| `fitforge-redis` | Redis 7 (Job-Queue) |

Alle Daten liegen im Dataset `DATA_ROOT`, standardmäßig `/mnt/tank/apps/fitforge`, in den Unterordnern `postgres/`, `redis/`, `uploads/` und `backups/`.

---

## 2. TrueNAS Scale: Custom App einrichten

Getestet mit TrueNAS Scale ab 24.10 („Electric Eel“), der Apps auf Docker-Compose-Basis ausführt.

### 2.1 Dataset anlegen

1. **Storage → Pools → tank → Add Dataset:** `apps/fitforge` (Preset „Apps“).
2. Unterordner anlegen, per Shell unter *System → Shell*:
   ```bash
   mkdir -p /mnt/tank/apps/fitforge/{postgres,redis,uploads,backups}
   chown -R 568:568 /mnt/tank/apps/fitforge/{uploads,backups}
   ```
   `568` ist der TrueNAS-Standardbenutzer `apps`. Er passt zu `PUID`/`PGID` in der `.env`.
   Den Ordner `postgres/` richtet der Postgres-Container selbst ein.

### 2.2 Netzwerk: macvlan und Bridge

- Die App bekommt per **macvlan** eine eigene IP im LAN, zum Beispiel `192.168.1.241`.
  Wähle einen Bereich außerhalb des DHCP-Pools deines Routers (`LAN_IP_RANGE`).
- **Wichtig: macvlan-Isolation.** Der TrueNAS-Host kann Container im macvlan **nicht** direkt erreichen, und umgekehrt.
  Läuft Nginx Proxy Manager auf demselben TrueNAS, kann er die macvlan-IP also nicht ansprechen.
  Deshalb hängt die App zusätzlich im **Bridge-Netz `fitforge_proxy`**. Darüber erreicht NPM die App unter `fitforge-app:8000`.
- `MACVLAN_PARENT` ist die physische Netzwerkkarte des Hosts. Du findest sie unter *Network → Interfaces* oder mit `ip link`, zum Beispiel `eno1` oder `enp3s0`.
  Hängt die Karte in einer Bridge (`br0`), trägst du `br0` ein.

### 2.3 App installieren

**Variante A: Custom App per YAML (empfohlen)** – fertige Vorlage: [`truenas/fitforge-truenas.yaml`](truenas/fitforge-truenas.yaml), nur die mit `ANPASSEN` markierten Werte ändern.

1. *Apps → Discover Apps → ⋮ → Install via YAML*.
2. Name: `fitforge`.
3. Den Inhalt von `docker-compose.yml` einfügen. Die Variablen `${…}` ersetzt du dabei durch deine Werte, denn die YAML-Maske liest keine `.env`-Datei.
   Einfacher geht das auf einem PC:
   ```bash
   docker compose --env-file .env config > fitforge-truenas.yaml
   ```
   Den Inhalt von `fitforge-truenas.yaml` fügst du dann in TrueNAS ein.
4. Mit *Save* installieren. Der Status sollte nach etwa einer Minute auf **Running** stehen.

**Variante B: per Shell mit Dockge oder Compose**

```bash
cd /mnt/tank/apps/fitforge
git clone https://github.com/zendonir/fitness_ai.git src && cd src
cp .env.example .env && nano .env
docker compose up -d
```

### 2.4 Prüfen

```bash
docker ps --filter name=fitforge            # alle vier Container "healthy"
curl http://192.168.1.241:8000/api/health   # {"status":"ok"}  (von einem anderen LAN-Gerät, nicht vom Host!)
```

---

## 3. Nginx Proxy Manager (HTTPS)

### 3.1 NPM mit FitForge verbinden

Läuft NPM als Docker-Container auf demselben Host, verbindest du ihn einmalig mit dem Bridge-Netz:

```bash
docker network connect fitforge_proxy <npm-container-name>   # z. B. ix-nginx-proxy-manager-npm-1
```

Dauerhaft geht das über die Compose-Datei von NPM:

```yaml
services:
  npm:
    networks: [default, fitforge_proxy]
networks:
  fitforge_proxy:
    external: true
```

Läuft NPM auf einem **anderen** Gerät, nutzt du stattdessen die macvlan-IP `APP_IP:8000` als Ziel.

### 3.2 Proxy-Host anlegen

*Hosts → Proxy Hosts → Add Proxy Host*:

| Feld | Wert |
|---|---|
| Domain Names | `fitforge.deine-domain.de` |
| Scheme | `http` |
| Forward Hostname / IP | `fitforge-app` (bzw. `APP_IP`) |
| Forward Port | `8000` |
| Block Common Exploits | ✓ |
| Websockets Support | ✓ |

Im Tab **SSL**:

- *Request a new SSL Certificate* mit **Use a DNS Challenge**, Provider wählen (z. B. Cloudflare, IONOS, Hetzner) und das API-Token eintragen.
- ✓ Force SSL, ✓ HTTP/2 Support, ✓ HSTS Enabled.

Im Tab **Advanced**, damit Chat-Streaming (SSE) und Foto-Uploads funktionieren:

```nginx
client_max_body_size 30M;
proxy_buffering off;
proxy_read_timeout 300s;
```

Setze `PUBLIC_URL=https://fitforge.deine-domain.de` in der `.env` **exakt** so, ohne Slash am Ende. Passkeys, Links und OIDC hängen davon ab.

---

## 4. Pi-hole: lokaler DNS-Eintrag (Split-DNS)

Damit die Domain im LAN direkt auf NPM zeigt, ohne Umweg über das Internet:

1. Pi-hole-Admin → **Local DNS → DNS Records**.
2. Domain `fitforge.deine-domain.de` → IP **deines NPM**, also die TrueNAS-Host-IP oder die IP von NPM.
3. *Add*. Unterwegs zeigt der öffentliche DNS-Eintrag auf deine WAN-IP bzw. nutzt das DNS-Challenge-Zertifikat hinter VPN.

Das Let's-Encrypt-Zertifikat aus der DNS-Challenge ist auch im LAN gültig. Das ist eine Voraussetzung für die PWA, Passkeys und Push.

---

## 5. Erster Admin-Login & Benutzer einladen

1. Rufe `https://fitforge.deine-domain.de` auf.
   - Sind `ADMIN_EMAIL` und `ADMIN_PASSWORD` in der `.env` gesetzt, meldest du dich damit an. Entferne danach das Passwort aus der `.env`.
   - Ohne diese Werte zeigt die App „Ersten Admin anlegen“: Das erste registrierte Konto wird automatisch Admin.
2. Der **Onboarding-Assistent** fragt Ziele, Körperdaten, Trainingsplan, Coach-Profil, KI und Datenfreigaben ab.
3. **Benutzer einladen:** *Profil → Administration → Einladungen*.
   Rolle (Benutzer, Trainer oder Admin) und Gültigkeit wählen, dann *Einladungslink erzeugen*. Der Link landet in der Zwischenablage; schicke ihn per Messenger.
4. Offene Registrierung ohne Einladung kannst du unter *Administration → Einstellungen* einschalten.
5. Admin-Werkzeuge per Kommandozeile:
   ```bash
   docker exec -it fitforge-app python -m app.cli create-admin admin@example.de 'neues-langes-passwort'
   docker exec -it fitforge-app python -m app.cli reset-link user@example.de
   ```

**Trainer:** Ein Benutzer gibt einen Trainer unter *Einstellungen → Trainer & Teilen* frei.
Der Trainer sieht dann unter *Profil → Meine Athleten* dessen Daten nur lesend und kann Kommentare schreiben.

---

## 6. iPhone/iPad: PWA installieren & Push aktivieren

1. Öffne die Domain in **Safari**. Andere Browser können auf iOS keine PWA installieren.
2. Tippe auf **Teilen → „Zum Home-Bildschirm“ → Hinzufügen**.
3. Starte FitForge vom Home-Bildschirm. Die App läuft im Vollbild, mit Safe-Area-Insets und offline nutzbar.
   Einträge ohne Verbindung landen in einer Warteschlange und werden automatisch synchronisiert.
4. **Push aktivieren** (ab iOS 16.4, nur in der installierten PWA):
   *Profil → Benachrichtigungen → Push auf diesem Gerät* einschalten und die Rückfrage mit *Erlauben* bestätigen, dann *Test-Benachrichtigung* senden.
   Voraussetzung: `VAPID_PUBLIC_KEY` und `VAPID_PRIVATE_KEY` sind gesetzt (`app.cli gen-keys`).
   Ändere die VAPID-Schlüssel danach nicht mehr, sonst müssen alle Geräte Push neu aktivieren.
5. **Face ID / Passkey:** *Einstellungen → Sicherheit → Passkey hinzufügen*. Danach meldest du dich per Face ID an.
6. Der Pausen-Timer meldet sich per Push, wenn die App im Hintergrund ist.
   iOS unterstützt keine Vibration im Browser; die Benachrichtigung ersetzt sie.

---

## 7. KI-Provider einrichten

Die App ist **ohne KI voll nutzbar**. Die KI schaltest du global unter *Administration → Einstellungen* ab, jeder Benutzer zusätzlich für sich selbst.

| Provider | Einrichtung |
|---|---|
| **Anthropic (Claude)** | Key unter console.anthropic.com erstellen und als `ANTHROPIC_API_KEY` in die `.env` oder unter *Administration → Einstellungen* eintragen. Standardmodell: `claude-opus-5`. |
| **OpenAI** | `OPENAI_API_KEY`, Standardmodell `gpt-5` |
| **Ollama (lokal)** | `OLLAMA_BASE_URL=http://<ollama-ip>:11434`, Modell z. B. `llama3.1` oder `qwen2.5`. Für Tool-Calling brauchst du ein Modell mit Function-Calling-Unterstützung. |

- **Globale Keys** setzt der Admin. Jeder Benutzer kann unter *Einstellungen → KI-Coach* zusätzlich **eigene Keys** hinterlegen; die haben Vorrang.
  Alle Keys werden mit Fernet (`FERNET_KEY`) verschlüsselt gespeichert. **Den `FERNET_KEY` sicher aufbewahren**: Ohne ihn sind gespeicherte Keys und 2FA-Secrets nicht mehr lesbar.
- **Pro Aufgabe:** Unter *Einstellungen → KI-Coach → Provider pro Aufgabe* wählst du getrennt für Chat, Foto-Erkennung, Berichte usw.
- **Fallback:** Fällt ein Provider aus oder greift ein Rate-Limit, wechselt die App automatisch zum nächsten konfigurierten Provider (abschaltbar).
- **Kosten:** Jede Anfrage wird mit Provider, Modell, Tokens, Dauer und geschätzten Kosten protokolliert.
  Das Monatslimit pro Benutzer gilt global (`AI_DEFAULT_MONTHLY_LIMIT_USD`) oder individuell unter *Administration → Benutzer*.
  Die Übersicht findest du unter *Administration → KI-Kosten*.
- **Datenfreigaben:** Training, Ernährung, Körperwerte, Metriken und Fotos gehen nur an die KI, wenn der Benutzer die jeweilige Kategorie freigibt.
- **Systemprompt:** *Administration → Systemprompt* ist versioniert. Jede Änderung erzeugt eine neue Version, frühere Versionen kannst du wieder aktivieren.
- **Leitplanken:** Keine Diagnosen, Verweis auf Ärztin oder Arzt, keine Crash-Diäten.
  Die kcal- und Protein-Untergrenzen erzwingt der Code (`backend/app/services/nutrition.py`), auch gegenüber KI-Vorschlägen.
- **Schreibende Aktionen** des Coaches, etwa Mahlzeit loggen, Plan anpassen oder Ziel ändern, erscheinen immer als Karte mit Diff und müssen bestätigt werden.

---

## 8. Home Assistant

1. In FitForge unter *Einstellungen → Integrationen* einen **API-Token** erstellen, z. B. „Home Assistant“.
2. In der `secrets.yaml`:
   ```yaml
   fitforge_token_sven: "Bearer ff_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
   ```
3. In der `configuration.yaml`, einmal pro Benutzer:
   ```yaml
   rest:
     - resource: https://fitforge.deine-domain.de/api/ha/summary
       scan_interval: 300
       headers:
         Authorization: !secret fitforge_token_sven
       sensor:
         - name: "FitForge Sven kcal heute"
           unique_id: fitforge_sven_kcal_today
           value_template: "{{ value_json.kcal_today }}"
           unit_of_measurement: "kcal"
           json_attributes: [kcal_target, kcal_remaining, day_type]
         - name: "FitForge Sven Protein heute"
           unique_id: fitforge_sven_protein_today
           value_template: "{{ value_json.protein_today }}"
           unit_of_measurement: "g"
           json_attributes: [protein_target]
         - name: "FitForge Sven Wasser"
           unique_id: fitforge_sven_water
           value_template: "{{ value_json.water_ml }}"
           unit_of_measurement: "mL"
         - name: "FitForge Sven letztes Training"
           unique_id: fitforge_sven_last_workout
           value_template: "{{ value_json.last_workout }}"
           json_attributes: [last_workout_at, last_workout_days_ago]
         - name: "FitForge Sven Gewicht (7-Tage-Mittel)"
           unique_id: fitforge_sven_weight
           value_template: "{{ value_json.weight_avg_7d }}"
           unit_of_measurement: "kg"
           device_class: weight
           json_attributes: [weight_trend_7d]
         - name: "FitForge Sven Streak"
           unique_id: fitforge_sven_streak
           value_template: "{{ value_json.streak_days }}"
           unit_of_measurement: "Tage"
         - name: "FitForge Sven Coach-Hinweis"
           unique_id: fitforge_sven_coach_hint
           value_template: "{{ value_json.last_hint_title }}"
           json_attributes: [last_hint]
   ```
4. Home Assistant neu starten. Die Sensoren heißen danach `sensor.fitforge_sven_kcal_heute` usw.

---

## 9. Apple Health über Kurzbefehle

Kurzbefehle-App → **Automation → Neue Automation → Tageszeit (z. B. 21:30), sofort ausführen**:

1. „Health-Samples suchen“: *Gewicht*, neuestes, Limit 1. Den Wert zusätzlich als Zahl holen, dasselbe für Schritte (Summe heute), Schlafanalyse, Ruhepuls usw.
2. Aktion **„Inhalte von URL abrufen“**:
   - URL: `https://fitforge.deine-domain.de/api/integrations/apple-health/raw`
   - Methode: `POST`
   - Header: `Authorization` = `Bearer ff_…` (API-Token aus Schritt 8.1)
   - Anfragetext **JSON**:

     | Schlüssel | Wert |
     |---|---|
     | `date` | Aktuelles Datum (Format `yyyy-MM-dd`) |
     | `weight_kg` | Gewicht |
     | `body_fat_pct` | Körperfett |
     | `steps` | Schritte |
     | `sleep_hours` | Schlaf |
     | `resting_hr` | Ruhepuls |
     | `active_kcal` | Aktive Energie |
     | `hrv_ms` | HRV |

Werte mit Einheit („80,4 kg“) liest die App tolerant ein, deutsche Zahlenformate eingeschlossen.
Schritte, Schlaf, Ruhepuls, aktive Energie und HRV legt die App automatisch als **eigene Metriken** mit Diagramm an.
Mehrfaches Senden am selben Tag aktualisiert die Werte statt Duplikate zu erzeugen.
Workouts lassen sich über den strukturierten Endpunkt `/api/integrations/apple-health` im Feld `workouts` übertragen.

---

## 10. Backup & Restore

**Automatisch:** Der Worker erstellt jede Nacht um `BACKUP_HOUR` (Standard 3 Uhr) ein `pg_dump`-Backup nach `DATA_ROOT/backups/fitforge_YYYY-MM-DD_HHMMSS.sql.gz`.
Die Aufbewahrung folgt dem Großvater-Vater-Sohn-Prinzip: `BACKUP_KEEP_DAILY=7`, `BACKUP_KEEP_WEEKLY=4`, `BACKUP_KEEP_MONTHLY=6`.
Manuell startest du ein Backup unter *Administration → Speicher & Backups* oder so:

```bash
docker exec fitforge-app /entrypoint.sh backup
```

Zusätzlich empfohlen: für das Dataset `apps/fitforge` einen TrueNAS **Periodic Snapshot Task** und eine Cloud-Sync- oder Replikationsaufgabe anlegen. Damit sind auch Fotos (`uploads/`) gesichert.

**Restore:**

```bash
docker compose stop app worker
gunzip -c /mnt/tank/apps/fitforge/backups/fitforge_2026-09-28_030000.sql.gz \
  | docker exec -i fitforge-postgres psql -U fitforge -d fitforge
docker compose start app worker
```

Das Backup enthält `DROP … IF EXISTS`, ersetzt also den aktuellen Stand.
Fotos stellst du bei Bedarf aus dem Snapshot von `uploads/` wieder her.
Wichtig: Nutze dieselben `SECRET_KEY` und `FERNET_KEY` wie beim Backup.

**Benutzer-Export:** Jeder Benutzer kann unter *Einstellungen → Daten & Konto* alle Daten als JSON oder als CSV-ZIP exportieren und in eine andere FitForge-Instanz importieren.

---

## 11. Updates

```bash
docker compose pull && docker compose up -d
```

Datenbank-Migrationen (Alembic) laufen beim Start automatisch.

**Eigenes Image bauen:**

```bash
docker compose build && docker compose up -d
```

Hinter einem Registry-Mirror kannst du die Basis-Images per Build-Arg setzen:
`--build-arg PYTHON_IMAGE=… --build-arg NODE_IMAGE=…`.

---

## 12. Entwicklung & Tests

```bash
# Backend
cd backend
python3.12 -m venv ../.venv && ../.venv/bin/pip install -r requirements-dev.txt
../.venv/bin/pytest -q                       # SQLite
TEST_DATABASE_URL=postgresql+asyncpg://fitforge:fitforge@localhost/fitforge_test ../.venv/bin/pytest -q   # PostgreSQL
DATABASE_URL=postgresql+asyncpg://… ../.venv/bin/alembic upgrade head
../.venv/bin/uvicorn app.main:app --reload

# Worker
../.venv/bin/arq app.worker.WorkerSettings

# Frontend (Proxy /api → localhost:8000)
cd ../frontend && npm install && npm run dev
npm run check && npm run build
```

Die Tests decken ab: Makro-Rechner und Untergrenzen, Double Progression, API, Datentrennung zwischen Benutzern, Rechteprüfung (Rollen, Trainer, Admin), Provider-Abstraktion mit gemockten SDKs, Fallback, Aufgaben-Routing, Tool-Calling-Rechte (der Coach sieht nur Daten des eigenen Benutzers, Datenfreigaben, Bestätigungspflicht), Kostenlimit, Export und Import, Home Assistant, Apple Health und die Backup-Aufbewahrung.

Projektstruktur:

```
backend/
  app/core        Konfiguration, DB, Sicherheit, Zugriffshelfer
  app/models      SQLModel-Tabellen
  app/api         REST-Router
  app/services    Makros, Progression, Statistik, Open Food Facts, Export, Push, Backup
  app/ai          Provider, Kontext, Tools, Aktionen, Jobs
  app/seed        Übungen, Planvorlagen, Systemprompt
  app/worker.py   arq-Worker
  alembic/        Migrationen
  tests/          pytest
frontend/
  src/routes      Seiten (SvelteKit, adapter-static)
  src/lib         API-Client mit Offline-Queue, Komponenten (Charts, Muskel-SVG, Ringe …)
  src/service-worker.js
docker/entrypoint.sh
docker-compose.yml, docker-compose.bridge.yml, .env.example
```

---

## 13. Fehlerbehebung

| Problem | Lösung |
|---|---|
| App vom TrueNAS-Host aus nicht erreichbar | Das ist die normale macvlan-Isolation. Teste von einem anderen Gerät oder nutze den Weg über NPM/Bridge. |
| Passkey-Fehler „origin“ | `PUBLIC_URL` muss exakt der aufgerufenen HTTPS-Adresse entsprechen. |
| Push kommt nicht an (iPhone) | Die App muss über „Zum Home-Bildschirm“ installiert sein (iOS 16.4+), VAPID-Keys müssen gesetzt sein und der Worker muss laufen. |
| Chat antwortet erst am Ende | In NPM `proxy_buffering off;` setzen (siehe 3.2). |
| Kamera für Barcode startet nicht | Nur über HTTPS möglich; Kamerazugriff in den iOS-Einstellungen für Safari erlauben. |
| „KI nicht verfügbar“ | Key hinterlegen (Admin oder eigener Key), KI global und im Profil aktivieren, Monatslimit prüfen. |
| Logs | `docker logs fitforge-app`, `docker logs fitforge-worker` |
