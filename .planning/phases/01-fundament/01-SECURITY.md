---
phase: 01
slug: fundament
status: verified
threats_open: 0
asvs_level: 1
created: 2026-10-19
---

# Phase 01: Security

> Sicherheitsvertrag der Phase: Threat Register, akzeptierte Risiken und Audit-Trail.
> Geprüft gegen den Code nach den Review-Fixes (Commits 12c49a3 bis e5c560a). Jede Mitigation ist mit Datei:Zeile im Implementierungscode belegt, nicht nur über SUMMARY-Aussagen.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Nextcloud/AppAPI -> ExApp-HTTP | Anfragen tragen AppAPI-Signatur; Body (Weltname) und Pfad (world_id) sind Nutzereingabe | Weltname, world_id, Admin-Session |
| Browser -> Nextcloud | Session-Cookie plus requesttoken; Admin oder Nicht-Admin | Session, CSRF-Token |
| ExApp -> docker-socket-proxy | Wer den Proxy erreicht, kann Container beliebiger Spec erzeugen (CONTAINERS+POST) | Container-Specs, Tar-Payload mit minetest.conf (enthält Weltschlüssel) |
| LAN -> Welt-UDP-Port | Luanti-Clients erreichen den Container über 0.0.0.0:<port>/udp | Spielverkehr, SRP-Login mit Weltschlüssel |
| ExApp -> APP_PERSISTENT_STORAGE | SQLite mit Soll-Zustand und Weltschlüsseln im Klartext | world_key (sensibel) |
| Admin -> docs/install.md | Doku bestimmt die Proxy-Platzierung in echten Installationen | Konfiguration |
| Dev-Host 0.0.0.0:10040 -> ExApp | Dev-ExApp bindet auf alle Interfaces | signierte AppAPI-Anfragen |
| Abnahmeskript -> Dev-Stack | Skript legt Testkonto an, stoppt kurz den Proxy | Dev-Passwörter |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation (Beleg) | Status |
|-----------|----------|-----------|-------------|--------------------|--------|
| T-01-01 | Elevation of Privilege | docker-socket-proxy | mitigate | Proxy nur `127.0.0.1:23750` (scripts/dev/compose.yaml:53), übrige Flags explizit 0 (compose.yaml:33-46); world_spec fest kodiert, Name gelangt nicht in die Spec (src/gameworld/provisioner/spec.py:23-55); docker-py nur unter provisioner/ (Grep: nur client.py:18-22, spec.py:10; Gate scripts/dev/acceptance-phase1.sh:436-437); Restrisiko in docs/install.md:69-75 | closed |
| T-01-02 | Elevation of Privilege | Welt-Container | mitigate | spec.py:30 user 30000:30000, :49 cap_drop ALL, :50 no-new-privileges, :51 read_only, :40 nur benanntes Volume, Name mit Präfix `gameworld-<instanz>-` (spec.py:18-20); Tests tests/test_spec.py:26,55; K3 acceptance-phase1.sh:300-313 | closed |
| T-01-03 | Tampering | minetest.conf Key-Injection über Weltnamen | mitigate | normalize_world_name prüft Steuerzeichen vor Normalisierung, Whitelist `[\w .\-]+`, Länge 1-40 (src/gameworld/provisioner/luanti_conf.py:17-29); greift am API-Rand per AfterValidator (src/gameworld/api/worlds.py:62) und erneut im Dienst (src/gameworld/worlds/service.py:83); 422-Test tests/test_api_contract.py:14,17 | closed |
| T-01-04 | Tampering | minetest.conf durch den Luanti-Prozess | mitigate | conf uid 0, Modus 0444 (src/gameworld/provisioner/archive.py:113); Prozess als 30000 (spec.py:30); e2e tests/e2e/test_create_world_e2e.py:85-86; K4 acceptance-phase1.sh:334 | closed |
| T-01-05 | Information Disclosure | Serverliste | mitigate | luanti_conf.py:39-41 (server_announce false, send_players false, serverlist_url leer); kein Sichtbarkeitsfeld, `extra="forbid"` (api/worlds.py:59); 422-Test test_api_contract.py:12-13 | closed |
| T-01-06 | Spoofing | Fremd-Join über UDP im LAN | mitigate | Weltschlüssel `secrets.token_urlsafe(9)` (service.py:182), `disallow_empty_password = true` und `default_password` (luanti_conf.py:42-43); K4 acceptance-phase1.sh:328-329 | closed |
| T-01-07 | Information Disclosure | world_key (SQLite, API, Logs) | mitigate | Nur in SQLite (src/gameworld/worlds/store.py:27) und in der root-eigenen conf; nicht in Labels/Env (spec.py:31-39, keine `environment`-Angabe); GET-Modell ohne Schlüssel (api/worlds.py:65-73, 84-87), nur POST-Antwort (api/worlds.py:76-77, service.py:219); keine Log-Zeile referenziert den Schlüssel (alle LOG-Aufrufe in service.py:114,121,149,155,211,226,251, client.py:228 geprüft). Hinweis IN-02 siehe unten | closed |
| T-01-08 | Denial of Service | Heimserver-Ressourcen | mitigate | spec.py:45-48 (mem=memswap 512m, pids 128, 1 CPU), :53 restart no, :54 Log-Rotation 5m x 2; K3 acceptance-phase1.sh:300-303 | closed |
| T-01-09 | Spoofing | ExApp-HTTP ohne AppAPI-Signatur | mitigate | `APP.add_middleware(AppAPIAuthMiddleware)` global vor allen Routern (src/gameworld/main.py:42-44); Test test_api_contract.py:31-33, test_setup_check.py:262 | closed |
| T-01-33 | Information Disclosure | Rohe Docker-/requests-Ausnahmen | mitigate | `_guarded()` (src/gameworld/provisioner/client.py:98-125) umschließt jede öffentliche Methode (client.py:161,177,195,212,223,235,245); API wirft `HTTPException ... from None` mit deutscher Meldung (api/worlds.py:97-102,110-118,129-147); Tests tests/test_provisioner_errors.py:86-107,193 | closed |
| T-01-SC (01-01) | Tampering | uv/pip-Installs, Spiel-Zip, Images | mitigate | Exakte Pins (pyproject.toml:8-13, 15-23), uv.lock im Git; Luanti-Image per Digest (spec.py:13), Proxy-Image per Digest (compose.yaml:25, docs/install.md:17); Spiel-Zip SHA256 im Code (archive.py:21,34-38), Test tests/test_archive.py:44 | closed |
| T-01-10 | Elevation of Privilege | Nicht-Admin auf Seite/API | mitigate | Alle drei Routen ADMIN (appinfo/info.xml:51,57,63), Test tests/test_info_xml.py:35; `admin_required=True` (src/gameworld/lifecycle.py:39); Variante A belegt durch K1 acceptance-phase1.sh:219-226 | closed |
| T-01-11 | Spoofing | Dev-ExApp auf 0.0.0.0:10040 | mitigate | Secret pro Lauf aus openssl/urandom (scripts/dev/register-exapp.sh:50-56,261), Datei mit umask 077 (:263-264), `.dev/` gitignored (.gitignore:1); Einengung per GAMEWORLD_APP_HOST (:44); kein festes Secret (Grep auf 12345 nur Test-IDs `0123456789ab`); Middleware siehe T-01-09 | closed |
| T-01-12 | Tampering | CSRF auf POST/DELETE | mitigate | Alle Aufrufe über `@nextcloud/axios` (frontend/src/api.js:7,30-57), kein anderer HTTP-Client im Frontend | closed |
| T-01-13 | Information Disclosure | Weltschlüssel in der UI | accept | Siehe Accepted Risks Log AR-01; Code entspricht der Annahme: Anzeige nur aus POST-Antwort (frontend/src/App.vue:29-30,207), Listenmodell ohne Schlüssel | closed |
| T-01-14 | Information Disclosure | "Öffentlich machen"-Option | mitigate | Kein UI-Element; tests/test_frontend_privacy.py (verbotene Begriffe), tests/test_info_xml.py:59-62; K4 statisch acceptance-phase1.sh:345-347 mit Positivkontrolle | closed |
| T-01-15 | Elevation of Privilege | Proxy-Scope über die ExApp | mitigate | Wie T-01-01: docker-py nur provisioner/, fest kodierte Spec (spec.py:23-55), einziger `containers.create`-Aufruf mit `world_spec` (client.py:179-180), Proxy nur Loopback | closed |
| T-01-SC (01-02) | Tampering | npm-Installs | mitigate | Exakte Versionen ohne ^/~ (frontend/package.json:9-23), frontend/package-lock.json im Git, `npm ci --ignore-scripts` (register-exapp.sh:170) | closed |
| T-01-16 | Tampering | Stop/Remove fremder Container | mitigate | `_owned()` mit Label-Filter managed+instance+world_id und Nachprüfung `_is_owned` am Ergebnis (client.py:127-156); start/stop/remove lösen nur darüber auf (client.py:196,214,226); Volume-Löschung nur über instanz-präfixierten Namen (client.py:231); Test test_provisioner_errors.py:161, e2e Fremd-Instanz `fremd0000` (tests/e2e/test_world_lifecycle_e2e.py:21). Nach CR-01 unverändert | closed |
| T-01-17 | Tampering | Pfadinjektion über world_id | mitigate | `Path(pattern="^[0-9a-f]{12}$")` (api/worlds.py:107) auf allen drei Pfadrouten (:126,134,142); IDs nur `uuid4().hex[:12]` (service.py:181); Test tests/test_service_lifecycle.py:303-319 | closed |
| T-01-18 | Elevation of Privilege | Proxy-Scope bei Neuerzeugung | mitigate | Beide Neuerzeugungspfade in `_launch`, inklusive des neuen CR-01-Pfads (service.py:151 und :165), rufen `create_world_container`, das ausschließlich `world_spec(self._instance_id, world_id, host_port)` nutzt (client.py:179); keine neuen Nutzerwerte, Labels managed/instance/world_id bleiben gesetzt (spec.py:31-34) | closed |
| T-01-19 | Information Disclosure | Zusätzliche UDP-Ports | mitigate | Ports nur aus GAMEWORLD_PORT_RANGE (src/gameworld/worlds/ports.py:12-18), Bereich höchstens 200 Ports und >= 1024 (src/gameworld/config.py:35); Löschen entfernt die DB-Zeile und gibt den Port frei (service.py:268, store.py:131-133); jede Welt mit Schlüssel (T-01-06); kein UPnP (Grep ohne Treffer) | closed |
| T-01-20 | Denial of Service | Endlose Neuerzeugung | mitigate | `MAX_START_ATTEMPTS = 3` (service.py:34,156-157); CR-01-Neuerzeugung höchstens einmal pro Start (`recreated`-Flag service.py:136,146-148); danach NoFreePortError und `op_state failed` (service.py:168,170-171,237) | closed |
| T-01-21 | Repudiation / Datenverlust | Versehentliches Löschen | mitigate | Bestätigungsdialog mit Weltnamen (frontend/src/App.vue:79-85,123-125); DB-Zeile erst nach erfolgreichem Docker-Aufräumen (service.py:262-268) | closed |
| T-01-22 | Tampering | Setup-Check-Probes | mitigate | Schreibende Probes nur auf `gameworld-probe-nonexistent` (src/gameworld/provisioner/setup_check.py:67,90,103); Fake-Server protokolliert mutierende Pfade und prüft sie (tests/test_setup_check.py:41-42,85) | closed |
| T-01-23 | Elevation of Privilege | Zu weit offener Proxy (EXEC, INFO) | mitigate | Warn-Probes mit konkretem Flag (setup_check.py:100-121, eingebunden :237,245); install.md setzt übrige Flags explizit 0 (docs/install.md:25-39); Tests test_setup_check.py:171,180 | closed |
| T-01-24 | Elevation of Privilege | Proxy-Scope-Restrisiko | transfer | Transfer-Doku vorhanden: docs/install.md:69-75 (root-gleiches Restrisiko, kein Host-Port, andere ExApps im Deploy-Netz, Härtung fürs Store-Release); Snippet ohne `ports:` (install.md:40-48, :52); siehe Accepted Risks Log AR-04 | closed |
| T-01-25 | Information Disclosure | UDP-Ports ins Internet | mitigate | docs/install.md:62-67 (nur Heimnetz, keine Router-Freigabe, kein UPnP, VPN später) | closed |
| T-01-26 | Information Disclosure | Setup-Check-Meldungen | accept | Siehe Accepted Risks Log AR-02; Code entspricht der Annahme: Meldungen nennen nur Proxy-URL, Pfad, HTTP-Code und Ausnahmetyp (setup_check.py:154-163,211-227), Route `/api/*` ist ADMIN (info.xml:61-63) | closed |
| T-01-27 | Denial of Service | Hängender Proxy | mitigate | Timeout 3 s pro Probe (setup_check.py:249,152); Abbruch nach fehlgeschlagenem `_ping` (setup_check.py:230-232); Test test_setup_check.py:219 | closed |
| T-01-28 | Elevation of Privilege | Nicht-Admin auf Seite/API | mitigate | K1-Negativkontrollen mit gw-kind inklusive Positivkontrolle (acceptance-phase1.sh:211-234); Playwright-Schritt 8 bestanden (01-05-SUMMARY.md:22,61) | closed |
| T-01-29 | Elevation of Privilege | Proxy-Scope und Erreichbarkeit | mitigate | K5 EXEC 403, INFO 403, HostIp nur 127.0.0.1 (acceptance-phase1.sh:377-382); statische Prüfung docker-py nur provisioner/ mit Positivkontrolle (:436-438) | closed |
| T-01-30 | Information Disclosure | UDP-Exposition und Serverliste | mitigate | K4 conf unabhängig per docker cp (acceptance-phase1.sh:326-331); K2 nur UDP, kein TCP, zugewiesener Port (:268-270) | closed |
| T-01-31 | Elevation of Privilege | Container-Härtung | mitigate | K3 per docker inspect: CapDrop ALL, no-new-privileges, ReadonlyRootfs, Privileged false, User 30000:30000, keine Binds (acceptance-phase1.sh:304-313) | closed |
| T-01-32 | Information Disclosure | Testpasswörter im Skript | accept | Siehe Accepted Risks Log AR-03; Dev-Werte in acceptance-phase1.sh:29-30 und compose.yaml:17, Dev-Nextcloud seit WR-04 nur auf 127.0.0.1 (compose.yaml:13) | closed |

*Status: open · closed*
*Disposition: mitigate (Implementierung erforderlich) · accept (dokumentiertes Risiko) · transfer (Dritte/Betreiber)*

### Prüfung der Review-Fixes gegen das Register

| Fix | Commit | Betroffene Threats | Ergebnis |
|-----|--------|--------------------|----------|
| CR-01 `_launch` erzeugt fehlenden Container aus dem Volume neu | 12c49a3 | T-01-16, T-01-18, T-01-20 | Kein Rückschritt: Neuerzeugung über `create_world_container(..., reuse_volume=True)` (service.py:151) nutzt dieselbe fest kodierte `world_spec` mit eigenen Labels (client.py:179); spätere Mutationen laufen weiter nur über `_owned()`; Neuerzeugung durch `recreated` auf einmal pro Start begrenzt. `_stop_world_sync` behandelt fehlenden Container als No-op erst nach DB-Prüfung (service.py:244-251) |
| WR-01 Lifespan toleriert Konfigurationsfehler | 3e95c87 | T-01-09, T-01-33 | Kein Rückschritt: Middleware bleibt global (main.py:43); Fehler werden zu 503 mit deutscher Meldung ohne Stacktrace (api/worlds.py:47) |
| WR-02 NotFound in `start_world` nicht als 500 | 201e67a | T-01-16, T-01-33 | Kein Rückschritt: `_guarded` bildet NotFound auf WorldNotFoundError ab (client.py:111-112), Container weiter nur über `_owned` aufgelöst |
| WR-03 `errorText` wertet 422-Liste aus | 70cb094 | T-01-03 | Kein Rückschritt: Anzeige per Textinterpolation (App.vue:31-33), kein `v-html` im Frontend; Namensprüfung bleibt im Pydantic-Modell (api/worlds.py:62) |
| WR-04 Dev-Nextcloud auf 127.0.0.1 | e5c560a | T-01-11, T-01-32 | Stärkt die Mitigation (compose.yaml:13) |

### Informative Hinweise (keine offenen Threats)

- **IN-02 (T-01-07):** `world_key` liegt im Klartext in `gameworld.sqlite3` (store.py:27). Das entspricht der deklarierten Mitigation ("nur in SQLite unter APP_PERSISTENT_STORAGE"), ist für die deterministische Neuerzeugung nötig (service.py:72-73) und daher kein Gap. Folge: Backups von APP_PERSISTENT_STORAGE enthalten alle Beitrittsschlüssel. Die SQLite-Datei wird ohne explizite Dateirechte angelegt (store.py:62, Prozess-umask). Für spätere Phasen prüfen: Schlüssel aus der conf im Volume lesen statt aus der DB.
- **T-01-33:** `ProvisionerError`-Meldungen enthalten den Erklärungstext des Docker-Daemons (client.py:112,114,209). Das ist keine rohe Ausnahme und kein Stacktrace, gelangt aber über `last_error` in die Admin-Liste. Admin-only, daher unkritisch.
- **01-04-SUMMARY.md und 01-05-SUMMARY.md** haben keinen Abschnitt `## Threat Flags`. Die Summaries 01-01 bis 01-03 melden keine neue Angriffsfläche.

### Unregistered Flags

Keine. Kein SUMMARY meldet eine Threat-Flag ohne Zuordnung zu einer Threat-ID.

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-01 | T-01-13 | Weltschlüssel wird nur dem Admin einmalig nach Erstellung angezeigt, nie in der Liste; der Admin braucht ihn für den Test-Join bis zur Verbindungsinfo in Phase 3 | Plan 01-02 (Owner-Freigabe Phase 1, 19.10.2026) | 2026-10-19 |
| AR-02 | T-01-26 | Setup-Check-Meldungen nennen nur konfigurierte Proxy-URL, Pfade, HTTP-Codes und Flags; sichtbar nur für Admins (access_level ADMIN) | Plan 01-04 (Owner-Freigabe Phase 1, 19.10.2026) | 2026-10-19 |
| AR-03 | T-01-32 | Testpasswörter (gw-kind, Dev-Admin) betreffen nur Dev-Konten einer Loopback-Dev-Instanz, explizit als Dev markiert, keine echten Zugangsdaten | Plan 01-05 (Owner-Freigabe Phase 1, 19.10.2026) | 2026-10-19 |
| AR-04 | T-01-24 (transfer) | Restrisiko des Proxy-Scopes (CONTAINERS+POST ist root-gleich) liegt beim Betreiber: Netzplatzierung nur im Deploy-Netz, kein Host-Port; dokumentiert in docs/install.md Abschnitt 5; weitere Härtung im Store-Release (Open Question 1) | Plan 01-04, Betreiber per docs/install.md | 2026-10-19 |

*Akzeptierte Risiken tauchen in künftigen Audit-Läufen nicht erneut auf.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-10-19 | 35 | 35 | 0 | gsd-security-auditor (nach Review-Fixes 12c49a3..e5c560a) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-10-19
