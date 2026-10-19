---
phase: 02
slug: one-click-welten
status: verified
threats_open: 0
asvs_level: 1
created: 2026-10-19
---

# Phase 02: Security

> Sicherheitsvertrag der Phase: Threat Register, akzeptierte Risiken und Audit-Trail.
> Geprüft gegen den Code nach den Review-Fixes (Commits 611744e, 320136f, 4ae11c0, 6f5c0a0, 36c7a34, e5772a6; Stand 8c198b7) sowie gegen den T-02-32-Fix 0caf7c6. Jede Mitigation ist mit Datei:Zeile im Implementierungscode belegt, nicht nur über SUMMARY-Aussagen. Testläufe des Auditors: `GAMEWORLD_REQUIRE_DOCKER=1 uv run pytest -q` 363 passed (Stand 8c198b7), nach 0caf7c6 366 passed, nichts übersprungen.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Browser (Admin) -> ExApp-API | preset und name im POST-Body, world_id im Pfad, neue Route /restart, Polling alle 5 s | Preset-ID, Weltname, world_id |
| ExApp -> minetest.conf im Container | Preset-Zeilen werden Serverkonfiguration der Kinderwelt | conf-Zeilen, default_privs |
| SQLite -> Service/Reconciler | Migrierte Altzeilen und Soll-Zustand steuern Neuerzeugung und automatische Aktionen | preset, desired_state, op_state |
| ContentDB-CDN -> Build-Rechner | Fremdes Spiel-Zip (Lua-Code) wird heruntergeladen | VoxeLibre-Zip |
| vendor/games -> Welt-Volume | Fremder Lua-Code läuft in jeder Welt | Spieldateien im Tar |
| Welt-Container -> ExApp | Status-Datei und Inspect-Daten aus einem Container mit fremdem Lua-Code | gameworld_players.txt (untrusted), mtime |
| Welt-Mod/Spieler -> Dashboard | Spielernamen landen im Eltern-Browser | Spielernamen |
| Reconciler -> Docker-Proxy | Mutationen ohne Elternklick (Start, Neuerzeugung, Löschen-Wiederholung) | Container-/Volume-Operationen |
| Abnahmeskript -> Dev-Stack | Stoppt Proxy und ExApp-Prozess, stoppt/tötet Welt-Container | Dev-Passwörter, Weltschlüssel in Antworten |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation (Beleg) | Status |
|-----------|----------|-----------|-------------|--------------------|--------|
| T-02-01 | Tampering | CreateWorldRequest.preset | mitigate | `AfterValidator(validate_preset_id)` plus `max_length=64` (src/gameworld/api/worlds.py:68), `extra="forbid"` (:60); Registry nur fest kodiert (src/gameworld/provisioner/presets.py:28-76, `get_preset` :84-89); Dienst prüft erneut vor Lock und DB (src/gameworld/worlds/service.py:205); conf-Zeilen nur aus `preset.conf_lines` (src/gameworld/provisioner/luanti_conf.py:48,58); Test 422 tests/test_api_contract.py:37 | closed |
| T-02-02 | Elevation of Privilege | default_privs pro Preset | mitigate | presets.py:37 (`interact, shout, fly, fast`), :60 (`interact, shout`); genau eine Zeile luanti_conf.py:48; parametrisierter Test über alle Presets mit Verbotsliste server, privs, ban, kick, password, basic_privs, protection_bypass, rollback, give, teleport, bring (tests/test_luanti_conf.py:30-42,108-119) | closed |
| T-02-03 | Tampering | Preset-Zeilen überschreiben Härtung | mitigate | Preset-Zeilen hinter den Basis-Keys (luanti_conf.py:41-59); Test: jeder Key genau einmal, kein `name`, kein Basis-Key (server_announce, default_password, secure.*, name, port, max_users) in conf_lines (tests/test_luanti_conf.py:44,108-122) | closed |
| T-02-04 | Denial of Service | failed-Zeilen belegen UDP-Ports | mitigate | `_discard_failed_create` löscht die Zeile, wenn nichts in Docker entstand oder Aufräumen gelang (service.py:398-414), für ProvisionerError und seit WR-01 für jede Ausnahme (service.py:458-467); Payload-Fehler als ProvisionerError (service.py:181-183); Tests tests/test_service_unavailable.py:128,144,161; Live K2 "keine Zeile nach gescheitertem POST" (scripts/dev/acceptance-phase2.sh:428-434) | closed |
| T-02-05 | Tampering | Schema-Migration | mitigate | ALTER nur nach Spaltenprüfung per PRAGMA (src/gameworld/worlds/store.py:86-88), Default `mtg_kreativ` (:35,40), kein Drop/Recreate; Tests mit echter Schema-1-Datei und Doppelmigration (tests/test_store.py:38,66,77) | closed |
| T-02-06 | Information Disclosure | GET /api/presets | accept | Siehe AR-05; Code entspricht der Annahme: `PresetOut` nur id, title, description (api/worlds.py:101-119), Route unter `^/api/.*` ADMIN (appinfo/info.xml:61-63); Test tests/test_api_contract.py:43 | closed |
| T-02-SC | Tampering | Download VoxeLibre-Zip | mitigate | scripts/fetch-games.sh: Erwarteter Hash aus SHA256SUMS (:49-50), Download in `.part` (:58-71), Hashvergleich vor `mv` (:74-80), `.part` bei Abweichung gelöscht (:76); auch Offline-Pfad geprüft (:61-65); Code prüft zusätzlich vor jeder Nutzung (T-02-10); Hashes der abgelegten Zips vom Auditor nachgerechnet und identisch mit SHA256SUMS und presets.py:33,56 | closed |
| T-02-07 | Tampering | Transport | mitigate | `curl -fsSL --proto '=https' --tlsv1.2` (scripts/fetch-games.sh:68). Siehe Hinweis IN-05 (kein Zeit-/Größenlimit, nur Verfügbarkeit) | closed |
| T-02-08 | Information Disclosure | Laufzeit-Downloads | mitigate | Auditor-Grep nach `content.luanti`, `cdn.`, `urllib.request`, `httpx`, `requests.get` in src/: keine Treffer; Positivkontrolle: URL steht in scripts/fetch-games.sh:27; dauerhaftes Gate acceptance-phase2.sh:476-479 mit Positivkontrolle | closed |
| T-02-09 | Repudiation | Lizenzpflichten GPL/CC-BY-SA | mitigate | vendor/games/README.md nennt Quelle, Release, Lizenzen und Ort der Lizenztexte; Auditor-Prüfung: `minetest_game/LICENSE.txt` und `mineclone2/LICENSE.txt` liegen in den Zips | closed |
| T-02-10 | Tampering | Spiel-Zip vor dem Einspielen | mitigate | `_verified_zip` vergleicht SHA256 mit der Preset-Konstante vor jeder Nutzung (src/gameworld/provisioner/archive.py:39-54, aufgerufen :123); Tests manipuliertes/fehlendes Zip und Konsistenz Konstante gegen SHA256SUMS (tests/test_archive.py:121,127,134) | closed |
| T-02-11 | Tampering | Pfade im Zip | mitigate | `_safe_relative` verwirft absolute Pfade, Backslash, Laufwerksdoppelpunkt und `..` (archive.py:57-66), auf jeden Eintrag angewandt (:75); Tar-Namen immer unter festem Präfix (:151); Tests tests/test_archive.py:102,108 | closed |
| T-02-12 | Denial of Service | VoxeLibre-Speicherbedarf | mitigate | `mem_limit="1g"` im Preset (presets.py:59), `mem_limit = memswap_limit = preset.mem_limit` (src/gameworld/provisioner/spec.py:67-68), `restart_policy no` (:75); Tests tests/test_spec.py:40-41,48,54; e2e tests/e2e/test_presets_e2e.py:82 | closed |
| T-02-13 | Denial of Service | ExApp-RAM beim Payload-Bau | mitigate | `SpooledTemporaryFile(max_size=8 MiB)` (archive.py:35,124), Zip-Einträge per `zipped.open` gestreamt (:149-152), Schließen bei Fehler (:154-156) und nach dem Einspielen im `finally` (service.py:184-187) | closed |
| T-02-14 | Elevation of Privilege | Welt-Mod | mitigate | Mod als Konstante (src/gameworld/provisioner/status_mod.py:20-43), schreibt nur per `core.safe_file_write` in den Weltpfad (:23,31); `secure.enable_security = true`, `secure.trusted_mods =` und `secure.http_mods =` leer (luanti_conf.py:52-54) | closed |
| T-02-15 | Information Disclosure | Status-Datei | mitigate | Mod schreibt nur `player:get_player_name()` (status_mod.py:27-31), keine IP-Abfrage; Datei nie im Payload (Test tests/test_archive.py:98) | closed |
| T-02-16 | Tampering | Neuerzeugung mit falschem Spiel | mitigate | `_payload(row)` nutzt `row.preset` (service.py:176-180) für alle drei Erzeugungspfade (service.py:374-375, 389-390, 455-456); Spec-Limit und Labels aus `payload.preset` (src/gameworld/provisioner/client.py:297); e2e tests/e2e/test_presets_e2e.py:128 | closed |
| T-02-17 | Elevation of Privilege | POST /api/worlds/{id}/restart | mitigate | Route unter `^/api/.*` ADMIN (info.xml:61-63), `WorldId` Pattern `^[0-9a-f]{12}$` (api/worlds.py:145,180); stop/start nur über `_owned` mit Label- und Instanzfilter plus Nachprüfung (client.py:241-270, 314, 332); Test 422 für /restart (tests/test_service_lifecycle.py:804-811) | closed |
| T-02-18 | Denial of Service | Status-Datei lesen | mitigate | Strom auf 64 KiB gekappt und geschlossen (client.py:38,127-139), Inhalt auf 4096 Bytes (`STATUS_FILE_MAX`, :37,154), Tar im Stream-Modus `r|` (:147), kein Follow; NotFound -> None (:421-423); Tar/EOF-Fehler -> ProvisionerError ohne Retry (WR-04, :424-430); pro Welt isoliert (service.py:310-315); Tests tests/test_provisioner_errors.py:374-403,412-433 (Müll, leer, abgeschnitten, PAX-Riese), tests/test_service_lifecycle.py:528 | closed |
| T-02-19 | Tampering | Manipulierte Status-Datei (mtime) | accept | Siehe AR-06; Code entspricht der Annahme: mtime wirkt nur in `_ready` (src/gameworld/worlds/status.py:75-84) auf die Anzeige; Reconciler entscheidet nur über Container-State/OOM (src/gameworld/worlds/reconciler.py:65-94) | closed |
| T-02-20 | Denial of Service | Polling-Last auf Docker | mitigate | `POLL_MS = 5000` und Poll nur bei `document.visibilityState === 'visible'` (frontend/src/App.vue:176,315-324,384,393); 2-s-Cache siehe T-02-25 | closed |
| T-02-21 | Tampering | Lese-Retry wiederholt Mutationen | mitigate | `_read` nur in volume_exists, used_host_ports, list_managed, read_status_file, memory_bytes (client.py:353,364,382,416,440); Mutationen nur über `_guarded` (:295,313,330,341); seit WR-03 keine Timeouts wiederholt (:235); Tests tests/test_provisioner_errors.py:305 (start nie wiederholt) und WR-03-Timeout-Fälle | closed |
| T-02-22 | Information Disclosure | Fehlertexte im Dashboard | mitigate | Statustexte als Konstanten (status.py:25-37, service.py:64-83), Ausgabe per Interpolation (App.vue:76,84); Auditor-Grep `v-html`/`innerHTML` in frontend/src: keine Treffer. Hinweis zu Docker-Erklärtexten in last_error siehe unten | closed |
| T-02-23 | Tampering / XSS | Spielernamen im Dashboard | mitigate | `parse_players` nur `[A-Za-z0-9_-]{1,20}` per fullmatch, höchstens 64, ohne Duplikate (status_mod.py:50-66); 4096-Byte-Kappe davor (client.py:154); Anzeige per `{{ playersText(world) }}` (App.vue:76,251-256); Tests inkl. `<script>`, IP, Umlaut, Überlänge, kaputtes UTF-8 (tests/test_players_memory.py:25-58); kein v-html (Grep) | closed |
| T-02-24 | Information Disclosure | Spieler-IPs | mitigate | Auditor-Grep `logs(` in src: keine Treffer; Gate acceptance-phase2.sh:474-475; Namensfilter verwirft IPv4/IPv6-artige Zeilen (Test tests/test_players_memory.py:32-33) | closed |
| T-02-25 | Denial of Service | Docker-Last durch Polling und Tabs | mitigate | `LIST_CACHE_SECONDS = 2.0` mit Generationszähler (service.py:63,195-200,472-486); `_mutating` verwirft den Cache vor und nach jeder Mutation, auch bei Fehlern (:259-267, genutzt :428,489,502,522,617), Boot-Abgleich (:556), periodisch bei Änderung (:613-614); Unknown nie gecacht (:482); stats nur für laufende Container mit `one_shot` (client.py:444-446, service.py:320); Tests tests/test_service_lifecycle.py:708-760, tests/test_reconciler.py:344 | closed |
| T-02-26 | Elevation of Privilege | memory_bytes | mitigate | `_memory_bytes` löst über `_owned` auf (client.py:443); Test fremde Instanz tests/test_players_memory.py:160 | closed |
| T-02-27 | Tampering | Reconciler fasst fremde Container an | mitigate | `list_managed` filtert auf managed plus eigene Instanz (client.py:385-388); Aktionen nur per world_id über `_owned`/instanz-präfixierte Volumes (client.py:250-270,349,357); Waisen nur gemeldet (service.py:547-550); Test tests/test_reconciler.py:292-307; Live K4-Negativkontrolle mit Positivkontrolle (acceptance-phase2.sh:504-559) | closed |
| T-02-28 | Denial of Service | Crash-/OOM-Schleife | mitigate | `decide_periodic` liefert nur ADOPT_RUNNING oder NONE (reconciler.py:85-94); Boot: OOM -> MARK_OOM statt START (:80-81), failed -> NONE (:70-71); restart_policy no (spec.py:75); Tabellentests tests/test_reconciler.py:88-110; e2e tests/e2e/test_reconcile_e2e.py:174 | closed |
| T-02-29 | Denial of Service | ExApp-Start blockiert | mitigate | `asyncio.create_task(reconcile_forever(...))` (src/gameworld/main.py:45), Docker über `to_thread` mit `abandon_on_cancel` (service.py:227-233), Task-Abbruch im finally (main.py:48-52); Test < 2 s mit unerreichbarem Proxy (tests/test_reconciler.py:524-539) | closed |
| T-02-30 | Tampering | Race Reconciler gegen Elternaktion | mitigate | `_LOCK.acquire(blocking=False)` in Boot und periodisch (service.py:540,601), Elternaktionen unter `_LOCK` (:264); Test tests/test_reconciler.py:310-322 | closed |
| T-02-31 | Tampering | Neuerzeugung ohne Weltdaten | mitigate | `volume_exists` vor RECREATE (service.py:562, reconciler.py:75), MARK_DATA_MISSING statt leerer Welt; seit CR-01 zusätzlich direkt vor jeder Neuerzeugung in `_launch` (service.py:367-370) und Abweisen von Start/Neustart im Zustand "nur löschen" (:420-423,491,524), API 409 (api/worlds.py:154-155); Tests tests/test_service_lifecycle.py:881-964, tests/test_reconciler.py:376 | closed |
| T-02-32 | Repudiation | Automatische Aktionen ohne Spur | mitigate | Aktionen geloggt mit Welt-ID, ohne Weltschlüssel (service.py:566, :608, reconciler.py:116). Im ersten Lauf OPEN (Logger effektiv WARNING, INFO verworfen); gefixt in 0caf7c6: `_setup_logging()` setzt Logger `gameworld` auf INFO mit eigenem StreamHandler, beim Import ausgeführt (src/gameworld/main.py:29-43). Auditor-Gegenprobe: nach `dictConfig(uvicorn.config.LOGGING_CONFIG)` bleibt `isEnabledFor(INFO) == True` und der Handler erhalten; Regressionstest ohne `caplog.at_level` (tests/test_logging_setup.py:16-40); Live-Beleg .dev/exapp.log: `INFO gameworld.worlds.reconciler: Boot-Abgleich der Welten abgeschlossen` | closed |
| T-02-33 | Tampering | Abnahme berührt fremde Container | mitigate | `foreign_snapshot` (ID, Name, State, StartedAt aller Nicht-Gameworld-Container) vor/nach K4 mit Positivkontrolle (acceptance-phase2.sh:229-240,504-559); docker stop/kill nur auf per Label ermittelte Abnahme-Welten (`container_of` :179-181, :369,394,403,502,538); Aufräumen nur per gemerkter world_id (:147-157) | closed |
| T-02-34 | Information Disclosure | Weltschlüssel in Skriptausgabe | mitigate | Skript liest Antworten nur gezielt per jq-Feld (`.id`, `.status` usw., acceptance-phase2.sh:188-191,219), kein Ausgeben ganzer Antworten (Auditor-Grep auf `cat`/`jq '.'`: nur PID-Datei und conf-Kopie); keine Screenshots im Repo (`git ls-files` ohne png/jpg) | closed |
| T-02-35 | Denial of Service | Dev-Proxy bleibt gestoppt | mitigate | `trap cleanup EXIT` plus `trap 'exit 130' INT TERM` startet Proxy und ExApp neu (acceptance-phase2.sh:131-162); Auditor-Prüfung 19.10.: `gameworld-dev-gameworld-docker-proxy-1` Up, keine Container mit `gameworld.managed=true` | closed |
| T-02-36 | Spoofing | Live-Join mit falschem Passwort | accept | Siehe AR-07; Phase-1-Schutz unverändert: `disallow_empty_password = true` und `default_password = <Weltschlüssel>` (luanti_conf.py:46-47), Schlüssel `secrets.token_urlsafe(9)` (service.py:431) | closed |

*Status: open · closed*
*Disposition: mitigate (Implementierung erforderlich) · accept (dokumentiertes Risiko) · transfer (Dritte/Betreiber)*

### Offene Threats

Keine. T-02-32 war im ersten Auditlauf offen und ist mit 0caf7c6 geschlossen (siehe Register und Audit Trail).

### Prüfung der Review-Fixes gegen das Register

| Fix | Commit | Betroffene Threats | Ergebnis |
|-----|--------|--------------------|----------|
| CR-01 Fehlendes Volume ergibt nie eine leere Welt | 611744e | T-02-31, T-02-16, T-02-27 | Stärkt T-02-31: `volume_exists` direkt vor jeder Neuerzeugung (service.py:367-370), `DeleteOnlyError` -> 409 (api/worlds.py:154-155), Vorab-Abweisung ohne Docker-Aufruf (service.py:420-423). Volume-Prüfung nur über instanz-präfixierten Namen (client.py:355-360), kein Rückschritt bei T-02-27 |
| WR-01 Aufräumen bei Nicht-ProvisionerError | 320136f | T-02-04, T-02-13 | Stärkt T-02-04 (service.py:181-183, 461-467); API-Meldung fest, Details nur im Log (LOG.exception ohne Schlüssel) |
| WR-02 Fehlerisolation im Boot-Abgleich | 4ae11c0 | T-02-28, T-02-29, T-02-01 | Kein Rückschritt: Unbekanntes Preset markiert nur diese Welt (service.py:574-578, 137-142), DockerUnavailable wiederholt weiter den ganzen Abgleich (:568-570) |
| WR-03 Timeouts nicht wiederholen | 6f5c0a0 | T-02-21 | Stärkt T-02-21 (client.py:235) |
| WR-04 Tar-Fehler der Status-Datei | 36c7a34 | T-02-18 | Schließt die Lücke "Fehler pro Welt isoliert" für untrusted Tar-Inhalt (client.py:424-430) |
| WR-05 Unterbrochen erzeugte Welten nur löschbar | e5772a6 | T-02-31, T-02-16 | Kein Rückschritt: `RECONCILE_INTERRUPTED` in `DELETE_ONLY_ERRORS` (service.py:87), halb befüllter Container wird nie gestartet |
| T-02-32 Logging-Einrichtung | 0caf7c6 | T-02-32, T-01-07 | Schließt T-02-32; Format ohne Weltschlüssel, kein LOG-Aufruf referenziert `world_key` (Grep), kein Rückschritt bei T-01-07 |

### Informative Hinweise (keine offenen Threats)

- **IN-03 (T-02-18):** `_read_capped` schließt nur den docker-py-Generator, nicht die zugrunde liegende requests-Response (client.py:135-138). Kein Sicherheitsgap (Kappe greift), aber möglicher Verbindungs-Leak bei übergroßer Status-Datei aus bösartigem Lua-Code; für Phase 3 empfohlen.
- **IN-05 (T-02-07):** `curl` ohne `--max-time`/`--max-filesize` (scripts/fetch-games.sh:68). Integrität bleibt durch den Hash geschützt; nur Verfügbarkeit von Einrichtung/Image-Bau betroffen.
- **T-02-22:** `last_error` kann bei `ProvisionerError` aus `_guarded` den Erklärtext des Docker-Daemons enthalten (client.py:206-208) und wird für `failed`-Welten als `status_text` gezeigt (status.py:100-101). Quelle ist der Docker-Daemon, nicht der Welt-Container; admin-only, Ausgabe per Interpolation. Wie Phase-1-Hinweis zu T-01-33.
- **T-02-23 Grep-Gate:** Das in 02-05 genannte v-html-Gate existiert nicht dauerhaft in tests/ oder acceptance-phase2.sh (nur einmalig im Plan ausgeführt). Der Code ist sauber (Auditor-Grep ohne Treffer); ein dauerhaftes Gate analog zu `logs(` wird empfohlen.
- **Status-Datei als Symlink:** Ein nicht regulärer Tar-Eintrag ergibt leeren Inhalt (client.py:149-150); `secure.enable_security` verhindert ohnehin Symlinks aus Lua.
- **IN-01, IN-02, IN-04** aus 02-REVIEW.md sind UX/Zustandsthemen ohne Sicherheitsbezug.

### Unregistered Flags

Keine. Die Summaries 02-03 bis 02-06 melden unter `## Threat Flags` keine neue Angriffsfläche über das Register hinaus; 02-01, 02-02 und 02-07 haben keinen Abschnitt `## Threat Flags`. Die vom Auditor geprüften neuen Flächen (Status-Datei, Preset-Registry, fetch-games.sh, Tar-Streaming, Reconciler, delete_only/409, Cache) sind alle T-02-* zugeordnet.

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-01 bis AR-04 | T-01-* | Unverändert aus Phase 1 (.planning/phases/01-fundament/01-SECURITY.md) | Phase 1 | 2026-10-19 |
| AR-05 | T-02-06 | GET /api/presets liefert nur id, title, description; keine Hashes, Limits oder conf-Zeilen; admin-only wie alle `/api`-Routen | Plan 02-01 (Owner-Freigabe Phase 2, 19.10.2026) | 2026-10-19 |
| AR-06 | T-02-19 | Ein manipulierter mtime der Status-Datei kann nur "läuft" statt "startet gerade" anzeigen; keine Aktion (Reconciler, Start, Löschen) hängt daran | Plan 02-04 (Owner-Freigabe Phase 2, 19.10.2026) | 2026-10-19 |
| AR-07 | T-02-36 | Join-Schutz über den Weltschlüssel ist Phase-1-Stand; Whitelist und Einladungen folgen in Phase 3 | Plan 02-07 (Owner-Freigabe Phase 2, 19.10.2026) | 2026-10-19 |

*Akzeptierte Risiken tauchen in künftigen Audit-Läufen nicht erneut auf.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-10-19 | 37 | 36 | 1 (T-02-32) | gsd-security-auditor (nach Review-Fixes 611744e..e5772a6) |
| 2026-10-19 | 37 | 37 | 0 | gsd-security-auditor (Nachprüfung nach 0caf7c6) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-10-19
