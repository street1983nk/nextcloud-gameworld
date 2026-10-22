---
phase: 04
slug: spielzeitlimits
status: verified
threats_open: 0
asvs_level: 1
block_on: high
register_authored_at_plan_time: true
created: 2026-10-22
---

# Phase 04: Security

> Sicherheitsvertrag der Phase "Spielzeitlimits": Threat Register, akzeptierte Risiken, Restrisiken und Audit-Trail.
> Nachgeholte Prüfung (Zustand B: Phase 04 war abgeschlossen, aber ohne 04-SECURITY.md). Geprüft am AKTUELLEN Code, Stand HEAD b80fccb (nach den 9 Review-Fixes aus 04-REVIEW-FIX.md und nach Phase 4.1, die auf demselben Code aufbaut). Das Register stammt vollständig aus den `<threat_model>`-Blöcken von 04-01 bis 04-08 (T-04-01 bis T-04-45 plus T-04-SC). Jede Mitigation ist mit Datei:Zeile im Implementierungscode belegt, nicht über SUMMARY-Aussagen. Wo Phase 4.1 eine Phase-4-Fläche bereits geprüft hat (Verwalter-Schnappschuss CR-01, Pause, "frei"), wird auf .planning/phases/04.1-eltern-handy-pause-hinweise-rueckblick/04.1-SECURITY.md verwiesen; die Phase-4-eigenen Mitigationen sind hier selbst geprüft.
>
> Auditor-Läufe: `PYTHONUTF8=1 uv run pytest -q -m "not docker" -p no:cacheprovider` 1355 passed, 28 deselected. Eigene Gegenproben mit Positivkontrolle (Scratchpad, nicht im Repo) siehe Abschnitt "Gegenproben", 69 von 69 grün. Docker-e2e, Abnahmeskripte, Dev-Stack und Container hat der Auditor bewusst nicht angefasst (RAM). Abnahmebelege laut Orchestrator: acceptance-phase4.sh am 22.10.2026 als Regression 109 von 109 (innerhalb acceptance-phase4_1.sh 133/133), Phase 1 bis 3 84/104/75.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| LAN-Client -> Luanti-UDP-Port (Prejoin) | Kinder und Fremde senden Join-Versuche, auch skriptiert und mit Namensvarianten | Spielername |
| ExApp -> Docker-Proxy -> Welt-Volume | Mod-Code und Regeldatei `gameworld_time.txt` per put_archive (root, 0444), kein exec | Grenzen als Epoch, Deckel, Anker, Namen |
| Luanti-Prozess -> Welt-Volume -> ExApp | Mod schreibt das Zählbuch `gameworld_time_used.txt` (uid 30000), die ExApp liest es per get_archive im 15-s-Takt; unvertrauenswürdig | Name und Sekundensumme |
| Browser (Verwalter) -> /api/playtime | Regeln, Ferien, Zeitzone, Welt-Fenster; AppAPI ADMIN plus `require_verwalter` | Wochenpläne, Datumsangaben, Zeitzonenname |
| Browser (Kind) -> /api/my/playtime, /api/my/worlds | USER-Routen, UID aus der signierten AppAPI-Anfrage | eigener Rest, nächste Zeit, Fensterstatus |
| ExApp -> Nextcloud (Gruppe admin) | Verwalter-Schnappschuss `time_admins` nur im Kontext eines geprüften Verwalters | Konto-IDs der Gruppe admin |
| PyPI -> .venv / Image | neue Laufzeitabhängigkeit tzdata | Zeitzonendaten |
| Abnahmeskript -> Dev-Stack / Welt-Port | Loopback-Dev-Konten, UDP-Prober | Dev-Passwörter, Spielpasswörter |

---

## Threat Register

Status: CLOSED (Mitigation im Code an der genannten Stelle nachgewiesen bzw. accept-Eintrag im Accepted Risks Log und Code entspricht der Annahme), OPEN.

| Threat ID | Category | Component | Disposition | Mitigation (Beleg) | Status |
|-----------|----------|-----------|-------------|--------------------|--------|
| T-04-01 | DoS | Skriptierter Sofort-Rejoin | mitigate | `COOLDOWN = 2` (src/gameworld/provisioner/access_mod.py:121), `too_soon` lehnt ab, solange der Name verbunden ist oder vor weniger als 2 s ging (:259-266), Aufruf im Prejoin vor jeder Passwortsetzung (:280); e2e tests/e2e/test_rejoin_guard_e2e.py (Docker, hier nicht ausgeführt); Abnahme K6 "fünf Rein-Raus-Runden 0,2 s, Bitte einen Moment warten" (scripts/dev/acceptance-phase4.sh:783-804, Lauf 109/109) | CLOSED |
| T-04-02 | Elevation of Privilege | Sofortiger Wiederbeitritt nach Trennen | mitigate | Prejoin lädt die Regeln und lehnt bei Rest unter `MIN_LEFT = 60` ab (src/gameworld/provisioner/time_mod.py:269,561-566); Rest gegen das Zählbuch `used[name]` (:439-440), auch nach Welt-Neustart (Zählbuch beim Start eingelesen, :320-333) | CLOSED |
| T-04-03 | Tampering | Welt-Neustart soll Zeit zurücksetzen | mitigate | Zählbuch im Volume, beim Start eingelesen (time_mod.py:320-333), beim Start, im Takt, beim Verlassen und beim Herunterfahren geschrieben (:342,578,607,611-615,618-622); alle Grenzen absolute Epoch (`os.time`, :315-317,429,435); `_launch` fasst das Zählbuch nicht an (src/gameworld/worlds/service.py:783-813). Seit WR-06 zusätzlich `@base`: liegt das Zählbuch unter dem Anker, verschiebt der Mod den Deckel (time_mod.py:409-414,439) | CLOSED |
| T-04-04 | Tampering | Rein-Raus-Wechsel unter der Taktgrenze | mitigate | Gutschrift ab Beitritt (`since` bei joinplayer, time_mod.py:568-570), anteilig beim Verlassen und sofort geschrieben (:572-579), Gutschrift über `get_us_time`-Differenz, nie pauschal (:553-559); Test tests/test_time_mod.py:403-408 | CLOSED |
| T-04-05 | Tampering / DoS | Halbe oder fehlende Regeldatei | mitigate | Ohne Kopf oder `end` bleibt der alte Stand, beim ersten Laden `valid = "broken"` (time_mod.py:354-359); `left` liefert dann 0, Grund `start` (alle zu, :423); fehlende Datei = keine Regeln nur, wenn nie eine gültige da war (:347-349); `_launch` schreibt die Regeldatei vor jedem Start (worlds/service.py:805-812) | CLOSED |
| T-04-06 | Tampering | Injektion in die Regeldatei | mitigate | `_player_line`: `PLAYER_NAME.fullmatch`, Namen `welt`/`end` case-insensitiv verboten (time_mod.py:112,751-758); Grund aus `REASONS`/`WORLD_REASONS`, nur ganze Zahlen, frei exakt `-1 -1 -1`, Token `[A-Za-z0-9:-]{1,16}` (:109-113,678-691,761-766); Kopf, `@tage`, `@start`, `@base`, `@pause`, `@morgen` je geprüft, ValueError statt Überspringen (:694-748,790-793); Ausgabe `encode("ascii")` (:817); Tests tests/test_time_mod.py:59-123,306,323,364; Auditor-Gegenprobe Zeilenumbruch im Namen, `WELT`, `End`, Leerzeichen, `@base`, 21 Zeichen, bool als Zahl, `-2`, Grund/Token mit Umbruch: alle ValueError | CLOSED |
| T-04-07 | Information Disclosure | Fremder erfährt über den Zeittext, dass ein Name existiert | mitigate | `depends = gameworld_access` (time_mod.py:625-629); der Zugangs-Mod stellt seinen Prejoin an Position 1 (access_mod.py:293-296) und lehnt Fremde mit festem Text ab (:270-277), Modus OR: erste Ablehnung gilt; Test tests/test_time_mod.py:430-431; Abnahme K4 "Fremder nicht eingeladen" (04-VERIFICATION.md Truth 4) | CLOSED |
| T-04-08 | Elevation of Privilege | Mod-Code mit erweiterten Rechten | mitigate | `secure.enable_security = true`, `secure.trusted_mods =`, `secure.http_mods =` (src/gameworld/provisioner/luanti_conf.py:52-54); Mod ohne `http`, `io.popen`, `os.execute`, `require` (Test tests/test_time_mod.py:410-414), reines ASCII (:417-419); Zugriff nur über put_archive/get_archive, kein exec (src/gameworld/provisioner/client.py:342,494-517). Schreibbarkeit des Weltordners siehe AR-4-09 | CLOSED |
| T-04-09 | Information Disclosure | IP-Adressen oder Sitzungszeitpunkte im Zählbuch | mitigate | Zählbuch nur Kopf mit Schreibzeitpunkt und Generation plus `Name Sekunden` (time_mod.py:335-343); Mod liest keine IP; Abnahme K6 "keine IP-ähnlichen Muster im Zählbuch" mit Positivkontrolle (04-VERIFICATION.md:39) | CLOSED |
| T-04-10 | Tampering | Zählbuch-Rücksprung schenkt oder stiehlt Zeit | mitigate | `increments`: Zuwachs nur bei bekanntem Namen und größerem Wert, Rücksprung und Erstkontakt nur verankern, nie negativ (src/gameworld/playtime/ledger.py:30-38); Verbuchung und Anker in EINER Transaktion (WR-05, src/gameworld/worlds/store.py:654-686); Tests tests/test_playtime_ledger.py:15,35, tests/test_playtime_engine.py:106,117; Auditor-Gegenprobe Rücksprung 2000 auf 5: Verbrauch bleibt 1000 | CLOSED |
| T-04-11 | Tampering | Manipulierte Riesenwerte im Zählbuch | mitigate | `parse_ledger`: Kopf und Zeilen per `fullmatch`, Name `PLAYER_NAME`, Wert höchstens `LEDGER_MAX_SECONDS = 10**9`, sonst übersprungen, ohne Kopf/`end` None (time_mod.py:115-118,820-847); ASCII-Decode mit `replace` (:827-830); Lesen gekappt auf `LEDGER_FILE_MAX = 256 KiB` (client.py:47-48,454-470); Auditor-Gegenprobe `10**11`, `-5`, `1.5`, Name ohne Wert, Zeile mit drei Feldern: alle verworfen, gültige Zeile übernommen | CLOSED |
| T-04-12 | Elevation of Privilege | Falsche Zeitzone/Sommerzeit verschiebt Grenzen | mitigate | `day_bounds` über `datetime.combine` bis Folgetag 00:00, nie feste Tageslänge (src/gameworld/playtime/plan.py:167-177,184-198); `tzdata==2026.5` (pyproject.toml:13); Golden Vectors tests/test_playtime_plan.py:62,72; Auditor-Gegenprobe 29.03.2026 23 h, 25.10.2026 25 h, `until` nie nach dem lokalen Tagesende | CLOSED |
| T-04-13 | Information Disclosure | Verhaltensprofil durch Spielzeitdaten | mitigate | `time_usage` nur Tagessumme je Konto und Tag (store.py:95-100); verbucht nur Kinder mit Regeln (src/gameworld/playtime/engine.py:171-179); `_RETENTION_DAYS = 7`, `prune_usage` höchstens stündlich (engine.py:58-60,312-317, store.py:641-644); Entfernen der Regeln löscht ältere Tage (store.py:592-602); Test tests/test_store.py:342 | CLOSED |
| T-04-14 | Tampering | Migration verliert Phase-3-Daten | mitigate | Schema nur `CREATE TABLE IF NOT EXISTS` (store.py:66-106), Spalten per `PRAGMA table_info(worlds)` und `ALTER TABLE ... ADD COLUMN` (:210-214,321-327), kein Drop (Docstring :311-316); Tests tests/test_store.py:273 (3 auf 4 mit Daten), :430 (4 auf 5 mit Daten), :91 (idempotent) | CLOSED |
| T-04-SC | Tampering | uv add tzdata (Supply Chain) | mitigate | Package Legitimacy Audit mit slopcheck [OK], Repo python/tzdata (PSF) (.planning/phases/04-spielzeitlimits/04-RESEARCH.md:116-122); exakter Pin `tzdata==2026.5` (pyproject.toml:13); uv.lock mit sha256 für sdist und Wheel (uv.lock:643-649) | CLOSED |
| T-04-15 | Elevation of Privilege | Kind ändert eigene Regeln | mitigate | Router `prefix="/api/playtime", dependencies=[Depends(require_verwalter)]` (src/gameworld/api/playtime.py:56); `require_verwalter` 403 für Nicht-Verwalter (src/gameworld/access/roles.py:104-112); AppAPI `^/api/.*` ADMIN, `^/api/my/.*` USER (appinfo/info.xml:78-95); Tests tests/test_playtime_api.py:203,532; Auditor-Gegenprobe: alle 8 Methoden/Pfade aus dem Router aufgezählt, gw-kind, Fremder und Ex-Verwalter je 403, Datenbank unverändert; admin 200 als Positivkontrolle | CLOSED |
| T-04-16 | Tampering | Ungültige Eingaben (Minuten, Fenster, Felder) | mitigate | `extra="forbid"` auf DayIn/ChildPlanIn (api/playtime.py:81-98), `weekday` 1..7 (:84), `DayRule.__post_init__` Limit 1..1440, Fenster 0..1439/1..1440, Anfang vor Ende, beide oder keins (plan.py:40-52), `WeekPlan` genau 1..7 (:67-69), ValueError -> 422 (api/playtime.py:300-301); zusätzlich CHECK-Constraints (store.py:71-80); Konto-ID `_clean_target` und `max_length=64` (:212,336,345); Tests tests/test_playtime_api.py:148; Auditor-Gegenprobe 19 manipulierte Körper alle 422, kein Plan gespeichert. Dubletten siehe AR-4-07 (Info) | CLOSED |
| T-04-17 | Elevation of Privilege | Zwei Welten parallel verdoppeln die Zeit | mitigate | Ein Kontingent je Konto und Tag (`time_usage`, store.py:95-100); Takt verbucht erst alle laufenden Welten, dann rendert er (worlds/service.py:464-487); Deckel je Welt `seen + Rest` (engine.py:217); Tests tests/test_playtime_engine.py:219; Auditor-Gegenprobe 3000 s in W1 ergeben Deckel in W2 genau 600 s Rest. Restrisiko ExApp-Ausfall dokumentiert (docs/install.md:177), siehe AR-4-08 | CLOSED |
| T-04-18 | DoS | Zeittakt blockiert Elternaktionen oder umgekehrt | mitigate | `tick_time` nur `try_mutation()` (worlds/service.py:452-454), `try_mutation` mit `acquire(blocking=False)` (:324-339); Regel-API blockierend unter `mutation()` (src/gameworld/playtime/service.py:500-559); Byte-Vergleich über Render-Cache (engine.py:279-302); seit CR-01 verwirft jedes gescheiterte Schreiben den Cache (`_write_time`, worlds/service.py:380-390, Takt :482-487, `_launch` :806-811); Tests tests/test_service_lifecycle.py:1443,1565,1588; Auditor-Gegenprobe gescheiterter push_time, nächster Takt schreibt, danach kein unnötiges Schreiben | CLOSED |
| T-04-19 | Tampering | Restore/neues Volume senkt Zählbuch | mitigate | Rücksprung verankert neu (T-04-10); `_time_file` verbucht das Zählbuch vor dem Rendern (worlds/service.py:278-291), aufgerufen in `_launch` (:805); Test tests/test_service_lifecycle.py:1421; seit WR-06 gewährt der Mod nach Rücksprung nie mehr als den Rest beim Ausstellen (`@base`, time_mod.py:409-414,439; engine.py:72-83) | CLOSED |
| T-04-20 | Information Disclosure | Regeln oder Zählbuch im Log | mitigate | Logs nur Welt-ID, feste Labels, Größe oder Typname (worlds/service.py:289,310-314,373,376,468,471,483,487; client.py:516; playtime/service.py:314,357,360,450,461; ticker.py:35-37); `ProvisionerError`-Texte sind feste Labels (client.py:513); Lua-Mod loggt nichts (Auditor-Grep `core.log`, `print(` in time_mod.py: 0 Treffer) | CLOSED |
| T-04-21 | DoS | ExApp aus über Mitternacht | accept | Siehe AR-4-01; Code entspricht: `until` nie nach dem lokalen Tagesende (plan.py:184-198,262-263), Mod sperrt ab `until` (time_mod.py:435); Kinder ohne Regeln haben keine Zeile (engine.py:210-211) | CLOSED |
| T-04-22 | Tampering | Zeitzonenname als Pfad | mitigate | `_TIME_ZONES = frozenset(available_timezones())`, `_known_zone` 422 sonst, `max_length=64`, `extra="forbid"` (api/playtime.py:62,74-78,118-121); Test tests/test_playtime_api.py:341; Auditor-Gegenprobe `../etc/passwd`, `/etc/passwd`, `Europe/../Europe/Berlin`, Zeilenumbruch, leer, `Mars/Base`, `UTC `, Kleinschreibung, Zusatzfeld: alle 422, nichts gespeichert; `Europe/Vienna` 200 | CLOSED |
| T-04-23 | Tampering | Ungültige oder riesige Ferienzeiträume | mitigate | `date` über Pydantic, `start <= end`, höchstens 366 Tage (api/playtime.py:101-115), Label `isprintable` und `max_length=60` (:64,67-71,104); `MAX_HOLIDAYS = 50` unter derselben Sperre gezählt (playtime/service.py:66,527-536); CHECK (store.py:81-87); Tests tests/test_playtime_api.py:299,308,316; Auditor-Gegenprobe 367 Tage, `\n`, U+202E, 61 Zeichen, Ende vor Beginn, 30. Februar, Zusatzfeld: alle 422 | CLOSED |
| T-04-24 | Elevation of Privilege | Kind legt Ferien an | mitigate | Router-Sperre wie T-04-15 (api/playtime.py:56) gilt auch für `/holidays` und `/time-zone` ohne eigenen `uid`-Parameter; Test tests/test_playtime_api.py:203 (Bestand unverändert); Auditor-Gegenprobe wie T-04-15 | CLOSED |
| T-04-25 | DoS | Ferienänderung erreicht laufende Welt nicht | mitigate | `_add_holiday_sync`/`_remove_holiday_sync`/`_set_time_zone_sync` unter `mutation()` mit `_refresh_all_worlds` = `push_time` aller Welten (playtime/service.py:527-559); `applied` an die UI (api/playtime.py:187-188); verpasste Schreibvorgänge holt der Takt nach (CR-01, T-04-18); Tests tests/test_playtime_api.py:388,410 | CLOSED |
| T-04-26 | Information Disclosure | Ferienbezeichnungen | accept | Siehe AR-4-02; Code entspricht: nur in `GET /api/playtime` hinter `require_verwalter` (api/playtime.py:56,323-328), nicht in `/api/my/*` (src/gameworld/api/me.py:89-98) | CLOSED |
| T-04-27 | Elevation of Privilege | Kind erhält "frei" | mitigate | `frei` nur für Konten in `time_admins` (engine.py:195,206-209); kaputter oder fehlender Schnappschuss ergibt keine Freistellung (`parse_admins`, engine.py:86-96); Schnappschuss nur aus `group_members(acting_uid, "admin")` nach `require_verwalter` (playtime/service.py:296-323; Aufrufer api/playtime.py:324-392, src/gameworld/api/worlds.py:71-82,175-179); Kinder können keine Regeln für Verwalter bekommen und umgekehrt (playtime/service.py:515-516); Tests tests/test_playtime_engine.py:495,515; Auditor-Gegenprobe 5 kaputte Schnappschüsse ohne `frei`, Positivkontrolle Papa (admin) `frei`, Kind `ok`. Hintergrund-Bestätigung siehe 04.1-SECURITY.md T-04.1-03/-18 (CR-01) | CLOSED |
| T-04-28 | Elevation of Privilege | Entfernter Verwalter behält "frei" | accept | Siehe AR-4-03; inzwischen durch Phase 4.1 CR-01 eingeengt: `verify_admins` bestätigt den Schnappschuss alle 60 s im Hintergrund und leert ihn, wenn niemand mehr Admin ist (playtime/service.py:325-361; 04.1-SECURITY.md AR-41-06) | CLOSED |
| T-04-29 | DoS | Gruppenauflösung fällt aus | mitigate | `DirectoryUnavailableError`: letzter Stand bleibt, Drossel zurückgesetzt (playtime/service.py:311-316); ohne Stand keine Freistellung (engine.py:86-96); Weltenliste fängt jeden Fehler (api/worlds.py:174-179, Handy-Seiten :79-82); Tests tests/test_playtime_api.py:578,648 | CLOSED |
| T-04-30 | Information Disclosure | Fremder erfährt Weltnamen/Spieler über den Fenstertext | mitigate | Wie T-04-07: Zugangs-Prejoin zuerst und mit festem Text (access_mod.py:270-277,293-296); Welttext `TEXT_WELT` ohne Weltnamen (time_mod.py:128); Abnahme K4 "Fremder nicht eingeladen" (04-VERIFICATION.md Truth 4); e2e tests/e2e/test_world_window_e2e.py (Docker) | CLOSED |
| T-04-31 | Tampering | Welt-Fenster stoppt Welt oder überschreibt Eltern-Soll | mitigate | Auditor-Grep `stop`, `restart`, `desired_state`, `remove_world` in src/gameworld/playtime/*.py und api/playtime.py: kein Aufruf (einziger Treffer ist das Datenfeld `restarted` in pause.py:143, Phase 4.1); `_window_sync` schreibt nur Tabelle und Regeldatei (playtime/service.py:500-510); Abnahme K4 "Container läuft weiter, StartedAt und desired_state unverändert" (04-VERIFICATION.md Truth 4) | CLOSED |
| T-04-32 | Tampering | Ungültige Fenster-Eingaben | mitigate | `WorldWindowIn` mit `extra="forbid"`, genau 7 Einträge und Wochentage 1..7 eindeutig (api/playtime.py:124-143); `_to_windows`: geschlossener Tag ohne Fenster, offener mit Fenster, `check_world_window` wie DayRule (:222-233, plan.py:55-58); mindestens ein offener Tag (playtime/service.py:413-414); `WorldId` `^[0-9a-f]{12}$` (api/worlds.py:206); Test tests/test_playtime_api.py:511,520; Auditor-Gegenprobe 9 manipulierte Körper 422, manipulierte IDs 404/422, unbekannte Welt 404, Positivkontrolle 200 | CLOSED |
| T-04-33 | Tampering | Browser-Prüfung umgangen | accept | Siehe AR-4-04; Code entspricht: Backend prüft unabhängig (T-04-16, T-04-22, T-04-23, T-04-32), Auditor-Gegenprobe direkt gegen die API ohne Frontend | CLOSED |
| T-04-34 | Information Disclosure | Spielzeitdaten im Kind-Bundle | mitigate | Spielzeit-Abschnitte nur in ParentView (frontend/src/views/ParentView.vue:211-232,249-258), ParentView nur im Zweig `me.role === 'verwalter'`, sonst PlayerView (frontend/src/App.vue:12,33,35); Daten nur über die gesperrte API (T-04-15) | CLOSED |
| T-04-35 | Spoofing | Konto-ID mit Sonderzeichen lenkt Anfrage um | mitigate | `encodeURIComponent` für Konto-, Ferien- und Welt-ID (frontend/src/api.js:165,171,182,194,199); Backend `_clean_target` (Cc/Cf, leer) und `max_length=64` (src/gameworld/api/invites.py:53-57, api/playtime.py:212,336,345), `holiday_id` `ge=1` (:361); Auditor-Gegenprobe `%0A`, U+202E, `%00`, Leerzeichen, 65 Zeichen: 404/422, kein Plan | CLOSED |
| T-04-36 | Information Disclosure | Externe Aufrufe aus der UI | mitigate | frontend/package.json in Phase 4 unverändert (letzte Änderung 627860b, 19.10.2026, Phase 1); Zeitzonenliste `NcTimezonePicker` aus @nextcloud/vue, Vorschlag `Intl.DateTimeFormat` lokal (frontend/src/components/TimeZoneSetting.vue:41,62); Auditor-Grep `https?://` in frontend/src: nur SVG-Namespace und der Phase-3-Link luanti.org (JoinGuide.vue:8) | CLOSED |
| T-04-37 | Information Disclosure | Kind liest Pläne oder Verbrauch anderer Kinder | mitigate | `/api/my/playtime` ruft `my_playtime(uid, ...)` mit der UID aus `UserDep` (api/me.py:173-181), Antwort nur `limited`, `state`, `remaining_minutes`, `until_minute`, `next` (:89-98) aus `child_state(uid)` (playtime/service.py:440-451, engine.py:252-262); Tests tests/test_my_playtime.py:191; Auditor-Gegenprobe zweites Kind mit Regeln, gw-kind sieht nur sein `limited false`, Positivkontrolle gw-kind2 `limited true`, Schlüsselmenge exakt | CLOSED |
| T-04-38 | Spoofing | Kind gibt fremde UID mit | mitigate | Keine UID-Parameter in `/api/my/*` (api/me.py:130-181); Test tests/test_my_playtime.py:212; Auditor-Gegenprobe `?nc_user=gw-kind2` und `?uid=gw-kind2` ignoriert; alle `/api/my/*`-Routen nur GET | CLOSED |
| T-04-39 | Information Disclosure | Verhaltensprofil über die Kind-API | mitigate | `MyPlaytime` bewusst ohne Pläne und Verbrauch (playtime/service.py:165-181), `MyWorldWindow` nur offen jetzt plus aktuelles oder nächstes Fenster (:198-206,264-280, api/me.py:48-75); keine Sitzungszeiten in der Datenbank (T-04-13) | CLOSED |
| T-04-40 | Repudiation | Anzeige und Durchsetzung weichen ab | accept | Siehe AR-4-05; Code entspricht: Kind-Ansicht und Regeldatei rechnen beide mit `evaluate_child` aus demselben Store (engine.py:215,252-262), Schwelle `MIN_LEFT_SECONDS = 60` wie `MIN_LEFT` im Mod (playtime/service.py:74, time_mod.py:269) | CLOSED |
| T-04-41 | Information Disclosure | Passwörter in Skriptausgabe oder Logs | mitigate | Ausgabe nur über `pass`/`fail` mit Beschreibungstext (scripts/dev/acceptance-phase4.sh:90-117), Passwörter nur als Länge `${#KID_PW}` (:508-510); Prober-Ausgabe in Dateien umgeleitet (:304-309); kein `set -x` | CLOSED |
| T-04-42 | Elevation of Privilege | gw-kind bleibt mit Regeln oder in admin | mitigate | `trap cleanup EXIT`, `trap 'exit 130' INT TERM` (acceptance-phase4.sh:265-266), `reset_fixtures` entfernt Regeln, Verbrauch, Testferien, Zeitzone, admin-Mitgliedschaft, Gastkonto (:231-238); Abschlussprüfungen "ohne Regeln", "keine Ferien", "Europe/Berlin", "keine Verbrauchszeile", "nicht in admin" mit Positivkontrolle (:821-833) | CLOSED |
| T-04-43 | DoS | ExApp-Neustart trifft fremde Python-Prozesse | mitigate | `kill_backend` nur PID aus `.dev/exapp.pid`, Rückfall nur der LISTEN-Prozess auf Port 10040, nie `taskkill /IM python.exe` (acceptance-phase4.sh:48-49,170-191) | CLOSED |
| T-04-44 | Tampering | Dev-Zugangsdaten im Repo | accept | Siehe AR-4-06 (wie AR-15 aus Phase 3) | CLOSED |
| T-04-45 | Repudiation | Abnahme ohne Owner | mitigate | `checkpoint:human-verify gate="blocking"` (.planning/phases/04-spielzeitlimits/04-08-PLAN.md:135); Owner-Antwort wörtlich "ok abgenommen" (04-08-SUMMARY.md:42,96) | CLOSED |

*Status: CLOSED · OPEN*
*Disposition: mitigate (Implementierung erforderlich) · accept (dokumentiertes Risiko) · transfer (Dritte/Betreiber)*

### Offene Threats

Keine. 46 von 46 Threats sind CLOSED (40 mitigate, 6 accept, 0 transfer).

### Prüfung der Review-Fixes gegen das Register

| Fix | Commit | Betroffene Threats | Ergebnis am aktuellen Code |
|-----|--------|--------------------|----------------------------|
| CR-01 Gescheitertes Schreiben nie nachgeholt (Fail-open) | 1c2b06f | T-04-18, -25, -05 | `TimeEngine.forget` (engine.py:243-250), `_write_time` verwirft bei jedem Fehler (worlds/service.py:380-390), Takt verwirft auch bei Datenbank- und Wertfehlern (:484-487), `_launch` ebenso (:806-811); Tests tests/test_service_lifecycle.py:1565,1588; Auditor-Gegenprobe unabhängig nachgestellt |
| WR-02 Fensterbeginn öffnet der Mod selbst | 458f654 | T-04-02, -21 | `cap_rest_s` vor dem Fenster (plan.py:261-271), Deckel daraus (engine.py:217); vor `from` sperrt der Mod über die Grenzen (time_mod.py:435). Kein Fail-open: `cap_rest_s` ist höchstens Limit minus Verbrauch |
| WR-03 Großes Zählbuch schaltet Verbuchung still ab | 2ffaf83 | T-04-11, -17 | `LEDGER_FILE_MAX = 256 KiB` (client.py:47-48), Warnung nur mit Größe (:514-516, worlds/service.py:307-314) |
| WR-04 "Regeln entfernen" setzt Verbrauch zurück | 937267d, 7fc1033 | T-04-13, -15 | `clear_child(nc_user, keep_from=heute)` (playtime/service.py:520-525, store.py:592-602); Kind kann die Route nicht erreichen (T-04-15) |
| WR-05 Verbuchung nicht atomar | e932318 | T-04-10 | `book_usage` in einer Transaktion (store.py:654-686); Test tests/test_playtime_engine.py:117 |
| WR-06 Deckel am ExApp-`seen` | b316f1c | T-04-03, -19 | `@base` nur zu Deckel und nie darüber (time_mod.py:708-716), Mod verschiebt Deckel (:409-414,439), Anker stabil bei gleichem Deckel (engine.py:72-83) |
| WR-07 Mitternachtstext | 01b636f | T-04-21 | Nur Text; Trennen am Tagesende bleibt fail closed (time_mod.py:490-493) |
| WR-08 Dialoge ignorieren `applied` | 60254fe | T-04-25 | Warnkarte bei `applied === false` (frontend/src/playtime.js:467 `notAppliedText`) |
| WR-01 Kind-Ansicht "Heute" | 395cc4a | T-04-40 | `next_time` aus absolutem Epoch (playtime/service.py:213-223) |

### Gegenproben des Auditors (mit Positivkontrolle)

Eigene Prüfdatei im Session-Scratchpad (`C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\a8f4f483-22df-4541-8cb7-650b29ce088b\scratchpad\p4audit\test_audit_p4.py`, mit `-p tests.conftest` gegen die volle App inklusive AppAPI- und CSRF-Middleware), 69 von 69 grün. Routen werden aus dem Router aufgezählt (Anzahl 8 als Kontrolle), nicht aus einer festen Liste. Beim ersten Lauf lieferte die Aufzählung über `APP.routes` wegen `_IncludedRouter` 0 Routen, die Rollenprobe lief also leer; das hat die Kontrolle "Anzahl" aufgedeckt, die Probe zählt seitdem über `playtime.router.routes`.

| Prüfung | Ergebnis | Positivkontrolle |
|---------|----------|------------------|
| gw-kind, Fremder, Ex-Verwalter (noch im Schnappschuss) auf alle 8 Methoden/Pfade unter /api/playtime | Alle 403; Pläne, Ferien, Zeitzone, Welt-Fenster unverändert | admin: GET 200, POST Kind 200 und Plan gespeichert |
| Kind-Plan: Limit 0, 1441, -5, 30.5, "abc"; Fenster gleich, umgekehrt, -1, 1441, nur Anfang; Wochentag 0/8; Zusatzfeld; `nc_user` im Körper; 6 Tage; Feld `used_today_s`; Ferienplan mit 3 Tagen; Montag fehlt; leer | 19 von 19 HTTP 422, kein Plan | (admin-Kontrolle oben) |
| Konto-ID im Pfad: `%0A`, U+202E, `%00`, Leerzeichen, 65 Zeichen | 404/422, kein Plan | |
| Zeitzone: 8 Pfad-/Formvarianten, Zusatzfeld | 422, nichts gespeichert | `Europe/Vienna` 200 und gespeichert |
| Ferien: 367 Tage, `\n`, U+202E, 61 Zeichen, Ende vor Beginn, 30.02., Zusatzfeld | 422, keine Ferien | |
| Welt-Fenster: 6 und 8 Tage, Dublette, zu mit Fenster, offen ohne Fenster, Anfang gleich Ende, 1441, alle zu, Zusatzfeld; IDs `..%2Fetc`, Großbuchstaben, 13 Zeichen | 422 bzw. 404/422, kein Fenster | gültiges Fenster 200 und gespeichert; unbekannte Welt 404 |
| Kind-API mit zweitem Kind, `?nc_user=`, `?uid=` | gw-kind sieht nur `limited false` | gw-kind2 `limited true`; Schlüssel exakt 5 |
| Weltwechsel: 3000 s in W1 verbucht | Deckel W2 = 600 (Rest), W1 = 3100 + 600 | |
| Namensvariante `KIND` im Zählbuch | wird gw-kind zugerechnet (1200 s), keine Umgehung | |
| Rücksprung und Riesenwerte | Verbrauch bleibt; 5 kaputte Zeilen verworfen; ohne `end` None | gültige Zeile übernommen |
| Schnappschuss leer, kaputt, String, Objekt, Zahlenliste | kein `frei` | gültiger Schnappschuss: Papa `frei`, Kind `ok` |
| Injektion in die Regeldatei (7 Namen, 5 Zeilen) | alle ValueError | gültige Zeile wird geschrieben |
| Zählbuch nicht lesbar im Takt | Regeldatei trotzdem geschrieben, Kindzeile vorhanden, uid 0, Modus 0444 | |
| Sommer-/Winterzeit 29.03., 25.10., normaler Tag | 23/25/24 h, `until` nie nach Tagesende | |
| `/api/my/*` | nur GET-Routen | Aufzählung findet sie |

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-01 bis AR-25 | T-01-* bis T-03-* | Unverändert aus Phase 1 bis 3 (.planning/phases/03-zugang-und-rollen/03-SECURITY.md); AR-16 mit Phase 4.1 IN-07 behoben | Phase 1 bis 3 | 2026-10-20 |
| AR-4-01 | T-04-21 | ExApp aus über Mitternacht: Kinder mit Regeln kommen nach Tagesende nicht mehr hinein, bis die ExApp neu schreibt (fail closed, O-04, O-11); Kinder ohne Regeln unberührt; dokumentiert in docs/install.md:178 | Plan 04-03, Owner O-04 | 2026-10-22 |
| AR-4-02 | T-04-26 | Ferienbezeichnungen sind kurzer freier Elterntext (höchstens 60 Zeichen, ohne Steuerzeichen), nur für Verwalter sichtbar, keine Weitergabe | Plan 04-04 | 2026-10-22 |
| AR-4-03 | T-04-28 | Ein aus admin entferntes Konto bleibt bis zur nächsten Bestätigung `frei`. Seit Phase 4.1 CR-01 höchstens etwa 60 s plus 30 s Rollen-Cache (04.1-SECURITY.md AR-41-06, AR-10); Familien- und Schulumgebung | Plan 04-05, eingeengt durch 04.1 CR-01 | 2026-10-22 |
| AR-4-04 | T-04-33 | Die Browser-Prüfung ist nur Komfort; jede Eingabe prüft das Backend unabhängig (Pydantic, DayRule, Allowlist) | Plan 04-06 | 2026-10-22 |
| AR-4-05 | T-04-40 | Die Kind-Ansicht ist nur Hinweis und rechnet mit derselben Engine; durchgesetzt wird allein im Welt-Mod. Bekannte Abweichung IN-01: Bei einem Abruffehler bleibt die alte Restzeit stehen (frontend/src/views/PlayerView.vue:66-70), die Fehlermeldung erscheint | Plan 04-07 | 2026-10-22 |
| AR-4-06 | T-04-44 | Dev-Zugangsdaten in den Abnahmeskripten sind reine Loopback-Dev-Konten, wie AR-15 in Phase 1 bis 3 | Plan 04-08 | 2026-10-22 |

### Bekannte Restrisiken (keine Blocker)

| Risk ID | Severity | Bezug | Beschreibung | Empfehlung |
|---------|----------|-------|--------------|------------|
| AR-4-07 | Info | T-04-16 | `ChildPlanIn.normal`/`holiday` haben keine Längengrenze und keine Eindeutigkeitsprüfung: 14 Einträge mit allen 7 Wochentagen doppelt werden mit 200 angenommen, der letzte Eintrag je Tag gewinnt (Auditor-Gegenprobe: Limit 1440 statt 60). Der Kommentar api/playtime.py:95 behauptet, Dubletten würden abgewiesen; `WeekPlan` prüft nur die Schlüsselmenge (plan.py:67-69) nach dem Zusammenfalten im Dict (api/playtime.py:217-219). Nur Verwalter erreichen die Route, jeder Tag ist trotzdem voll validiert, kein Rechtegewinn. **Behoben in 4ccd480:** `_to_week` weist Dubletten vor dem Zusammenfalten ab (422), normal und holiday; zwei neue 422-Fälle in tests/test_playtime_api.py, Gegenprobe ohne Fix 2 failed | Erledigt |
| AR-4-08 | Low | T-04-17 | Läuft die ExApp nicht, ruht der Abgleich zwischen den Welten: Wer in zwei Welten gleichzeitig spielt, kann bis zur Rückkehr bis zu doppelt so lange spielen (docs/install.md:177). Bei laufender ExApp beträgt der Überhang höchstens einen Takt (15 s plus 5-s-Mod-Takt) je Welt | Dokumentiert, keine Änderung |
| AR-4-09 | Low | T-04-08, T-04-05, AR-23 | Wie AR-23 (Phase 3) für die Zugangsdatei: Die Regeldatei ist root 0444, liegt aber im Weltordner der Luanti-UID; Code im Spiel-Lua könnte sie löschen oder per rename ersetzen und das Zählbuch beliebig schreiben. Spieler ohne Privilegien können das nicht; nötig wäre Codeausführung im Spiel (MTG/VoxeLibre gepinnt). Die ExApp schreibt die Regeldatei bei jeder Änderung und jedem Start neu (worlds/service.py:361-390,805) | Zusammen mit AR-23 prüfen (root-eigenes, für Mod-Security nur lesbares Verzeichnis) |
| AR-4-10 | Info | T-04-10 | Erstkontakt verankert nur: Pro Welt und Spielername geht beim allerersten Blick der ExApp die bis dahin gezählte Zeit (höchstens etwa 20 s) nicht ins Tageskontingent; der Mod zählt sie in dieser Welt trotzdem gegen den Deckel | Gewollt (Schutz gegen Doppelzählung) |
| AR-4-11 | Info | T-04-01 bis -09, -30 | Der Lua-Mod ließ sich im Audit nicht ausführen (kein Lua-Interpreter, Docker bewusst nicht angefasst). Lua-Belege sind statisch am Quelltext geprüft, dynamisch belegt durch die e2e-Tests (tests/e2e/test_time_mod_e2e.py, test_rejoin_guard_e2e.py, test_world_window_e2e.py) und die Abnahme 109/109 | Keine Änderung |
| AR-4-12 | Info | T-04-28, Doku | docs/install.md:145 sagt noch "bleibt frei, bis ein Verwalter das Dashboard öffnet"; seit 04.1 CR-01 prüft der Hintergrund-Abgleich alle 60 s. **Behoben in 58c8af9** | Erledigt |

### Vom Auditor betrachtete Flächen (nicht im Plan-Register, alle zugeordnet)

| Fläche | Herkunft | Zuordnung | Beleg |
|--------|----------|-----------|-------|
| Fail-open durch nie nachgeholtes Schreiben | 04-REVIEW CR-01 | T-04-18, -25 | siehe Review-Fix-Tabelle |
| Zählbuch-Anker `@base` (neue Durchsetzungslogik im Mod) | 04-REVIEW WR-06 | T-04-03, -19, Injektion T-04-06 | time_mod.py:409-414,439,708-716 |
| Kontingent-Reset über "Regeln entfernen" | 04-REVIEW WR-04 | T-04-13, -15 | nur Verwalter, heutiger Verbrauch bleibt (store.py:592-602) |
| CSRF über den AppAPI-Proxy auf /api/playtime | 04.1-REVIEW IN-08 | T-04-15, -16 | `JsonOnlyChangesMiddleware` (04.1-SECURITY.md, Abschnitt "Vom Auditor registrierte Flächen") |
| Pause `@pause`/`@morgen` in derselben Regeldatei | Phase 4.1 | T-04-06 | 04.1-SECURITY.md T-04.1-03, -04 |

### Unregistered Flags

Keine. Alle acht SUMMARYs (04-01 bis 04-08) führen einen Abschnitt `## Threat Flags` und melden keine neue Fläche; sie ordnen ihre Belege bestehenden IDs zu (T-04-01 bis T-04-45, T-04-SC). Neu genannt ist nur der Lesepfad `read_time_ledger` (04-01-SUMMARY), er fällt unter T-04-11 und ist mit WR-03 auf 256 KiB gekappt.

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-10-22 | 46 | 46 | 0 | gsd-security-auditor (nachgeholt, Stand HEAD b80fccb nach 9 Review-Fixes und Phase 4.1; pytest 1355 passed, 28 deselected; eigene Gegenproben 69/69; Abnahme acceptance-phase4.sh 109/109 laut Orchestrator) |
| 2026-10-22 | 46 | 46 | 0 | Orchestrator: AR-4-07 (4ccd480) und AR-4-12 (58c8af9) behoben, pytest 1357 passed, ruff/pyright/vulture grün |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-10-22
