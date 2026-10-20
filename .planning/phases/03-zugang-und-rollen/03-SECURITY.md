---
phase: 03
slug: zugang-und-rollen
status: verified
threats_open: 0
asvs_level: 1
created: 2026-10-20
---

# Phase 03: Security

> Sicherheitsvertrag der Phase: Threat Register, akzeptierte Risiken, Restrisiken und Audit-Trail.
> Geprüft gegen den Code nach den Review-Fixes 7126f94 (WR-01) und 0760c7f (WR-02), Stand 905f780. Jede Mitigation ist mit Datei:Zeile im Implementierungscode belegt, nicht nur über SUMMARY-Aussagen. Ein früherer, abgebrochener Auditlauf hat kein Artefakt hinterlassen; dieser Bericht ist vollständig neu erstellt (Zustand B aus den Threat-Models von 03-01 bis 03-07).
>
> Auditor-Läufe: `uv run pytest -q --ignore=tests/e2e` 573 passed. Die e2e-Tests und die Abnahmeskripte hat der Auditor bewusst nicht ausgeführt (laufender Dev-Stack und Container bleiben unberührt); deren Belege stammen aus 03-07 (acceptance-phase3.sh 75/75 dreimal, Regression Phase 1 84/84, Phase 2 104/104) und sind hier als Testbelege mit Datei:Zeile zitiert. Eigene Gegenproben des Auditors mit Positivkontrolle siehe Abschnitt "Gegenproben".

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| LAN-Client -> Luanti-UDP-Port | Beliebige Geräte im Heimnetz senden Join-Versuche mit frei gewählten Namen und Passwörtern | Spielername, SRP-Handshake |
| ExApp -> Docker-Proxy -> Welt-Volume | Zugangsdatei und Mod-Code gelangen per `put_archive` in den Container | gameworld_access.txt (Verifier), init.lua |
| Welt-Volume -> Luanti-Prozess | Mod liest die Datei, die nur die ExApp schreibt (root, 0444) | Namen, Verifier, Generation |
| Browser -> AppAPI-Proxy -> ExApp | Jede Anfrage eines angemeldeten NC-Kontos, auch von Kindern; Nutzer-ID signiert in AUTHORIZATION-APP-API | Konto-/Gruppen-IDs, Spielernamen, join_host |
| ExApp -> Nextcloud OCS | Selbstauskunft (Rollen, eigene Gruppen) und Kontoprüfung im Namen des Verwalters | Gruppen, Kontostatus, Anzeigenamen |
| Nextcloud appconfig_ex -> ExApp | Geheimnis für die Passwort-Ableitung (sensitive) | 32-Byte-Geheimnis |
| ExApp-SQLite (AppAPI-Volume) | Namen, Rotation, Einladungen, Verifier, Fingerabdruck; keine Passwörter | Verifier, Fingerabdruck |
| API -> Browser | Abgeleitete Passwörter nur an Verwalter (alle Spieler) bzw. an das Kind selbst (eigenes) | Spielpasswörter |
| Abnahmeskript -> Dev-Stack / Welt-Port | Dev-Konten auf Loopback, UDP-Prober | Dev-Passwörter, Spielpasswörter |

---

## Threat Register

Status-Spalte: VERIFIED (Mitigation im Code an der genannten Stelle nachgewiesen bzw. Annahme dokumentiert und Code entspricht ihr), PARTIAL, MISSING.

| Threat ID | Category | Component | Disposition | Mitigation (Beleg) | Status |
|-----------|----------|-----------|-------------|--------------------|--------|
| T-03-01 | Spoofing | Join mit beliebigem Namen | mitigate | `register_on_prejoinplayer` gibt für Namen ohne Eintrag `DENY` zurück, vor der Authentifizierung (src/gameworld/provisioner/access_mod.py:137-145); Start mit leerer Liste `allowed = {}` (:80); e2e "Fremder" abgewiesen (tests/e2e/test_access_e2e.py:110-118), VoxeLibre ebenso (:177-186); live K2 (scripts/dev/acceptance-phase3.sh:377-388) | VERIFIED |
| T-03-02 | Spoofing | Kapern eines eingeladenen Namens vor dem ersten Login | mitigate | Im selben Prejoin-Callback `get_auth` und `set_player_password(name, hash)` vor der Anmeldung (access_mod.py:146-150); Weltschlüssel öffnet ein provisioniertes Konto nicht (tests/e2e/test_access_e2e.py:124-130) | VERIFIED |
| T-03-03 | Spoofing | Online-Passwortraten | mitigate | `register_on_authplayer` zählt Fehlversuche, `FAIL_LIMIT = 5`, `LOCK_SECONDS = 600` (access_mod.py:76-77,124-135), Prüfung im Prejoin vor allem anderen (:138); e2e 5 Fehlversuche sperren auch das richtige Passwort (tests/e2e/test_access_e2e.py:166-174); Passwortstärke siehe T-03-21 | VERIFIED |
| T-03-04 | Tampering / DoS | Halb geschriebene oder fehlende Zugangsdatei | mitigate | `load()` verlangt Kopf `gameworld-access 1 <Gen>` und Schlusszeile `end`, sonst bleibt der alte Stand; fehlende Datei ändert nichts (access_mod.py:88-104); Start ohne Datei: niemand (:80); e2e halbe Datei (tests/e2e/test_access_e2e.py:139-143) | VERIFIED |
| T-03-05 | Tampering | Injection in die Zugangsdatei | mitigate | `render_access_file` prüft jeden Namen per `PLAYER_NAME.fullmatch` und jeden Verifier per `VERIFIER.fullmatch` und wirft `ValueError`, nie stilles Überspringen; Ausgabe `encode("ascii")` (access_mod.py:51,171-185); Lua-Seite akzeptiert nur `^([%w_%-]+) (#1#...)$` und höchstens 20 Zeichen (:99-100); Tests tests/test_access_mod.py:46,55,60 | VERIFIED |
| T-03-06 | Information Disclosure | Klartextpasswort im Welt-Volume | mitigate | In die Datei gelangt nur `make_verifier(...)` (src/gameworld/access/service.py:593-596), SRP-6a in der ExApp (src/gameworld/provisioner/luanti_auth.py:39-49); Golden Vector tests/test_luanti_auth.py:16 | VERIFIED |
| T-03-07 | Elevation of Privilege | Mod-Code mit erweiterten Rechten | mitigate | `secure.enable_security = true`, `secure.trusted_mods =`, `secure.http_mods =` (src/gameworld/provisioner/luanti_conf.py:52-54); Mod als Konstante ohne `http`, `io.popen`, `os.execute`, `require` (Test tests/test_access_mod.py:81-83), reines ASCII (:105). Siehe AR-23 zur Schreibbarkeit des Weltordners | VERIFIED |
| T-03-08 | Elevation of Privilege | Neuer Docker-Pfad | mitigate | `write_world_files` nur `put_archive` über `_owned(world_id)` (src/gameworld/provisioner/client.py:332-343), `_owned` mit Label-, Instanz- und Welt-Filter plus Nachprüfung `_is_owned` (:244-273); Auditor-Grep `exec_run`/`.exec(` in src: keine Treffer; Proxy-Flags in Phase 3 unverändert (scripts/dev/compose.yaml:32-38 `EXEC: 0`, letzte Änderung aa927a4 aus Phase 2; docs/install.md:26); live: POST /exec/x/start weiter 403 (acceptance-phase3.sh:412-413) | VERIFIED |
| T-03-09 | DoS | Aussperren eines Kindes durch absichtliche Fehlversuche | accept | Siehe AR-08; Code entspricht der Annahme: Sperre nur im Speicher und 10 min (access_mod.py:113-122,129-133) | VERIFIED |
| T-03-10 | Information Disclosure | IP-Adressen abgelehnter Joins | accept | Siehe AR-09; Mod ignoriert `_ip` (access_mod.py:124), schreibt nur die Generation (:103); Container-Log rotiert 5 MB x 2 (src/gameworld/provisioner/spec.py:76) | VERIFIED |
| T-03-11 | Elevation of Privilege | Kind ruft Verwaltungs-API | mitigate | AppAPI-Auffangroute `^/api/.*` ADMIN (appinfo/info.xml:77-82); routerweit `Depends(require_verwalter)` in worlds, setup_check, invites (src/gameworld/api/worlds.py:37, src/gameworld/api/setup_check.py:20, src/gameworld/api/invites.py:38); `require_verwalter` 403 für Nicht-Admins (src/gameworld/access/roles.py:104-112); Tests tests/test_roles.py:50-57 (alle Verwaltungsrouten 403, Dienst nie aufgerufen). Auditor-Gegenprobe: alle 17 FastAPI-Routen aufgezählt, 15 tragen `require_verwalter`, nur `/api/me` und `/api/my/worlds` nicht (Positivkontrolle) | VERIFIED |
| T-03-12 | Elevation of Privilege | Routen-Regex ohne End-Anker | mitigate | `^/api/me$` mit Anker, `^/api/my/.*`, beide USER und vor der ADMIN-Auffangroute (info.xml:65-82); Tests Reihenfolge, Anker, genau eine ADMIN-Route am Ende (tests/test_info_xml.py:46-61); zweite Schicht `require_verwalter` fängt Pfadtricks wie `/api/my/../worlds` (siehe T-03-11) | VERIFIED |
| T-03-13 | Elevation of Privilege | Rollenprüfung bei Nextcloud-Ausfall | mitigate | Jede Ausnahme wird `RoleUnavailableError`, Cache-Eintrag entfernt, nur Erfolge gecacht (roles.py:64-75); 503 statt Verwalter (:106-109); Test tests/test_roles.py:85-93 | VERIFIED |
| T-03-14 | Spoofing | Gefälschte Nutzer-ID | mitigate | `AppAPIAuthMiddleware` vor allen Routern (src/gameworld/main.py:74-78); UID nur aus `request.scope["username"]`, leer -> 401 (roles.py:92-97); Tests tests/test_roles.py:96-98, tests/test_api_contract.py:32 | VERIFIED |
| T-03-15 | Elevation of Privilege | Rollen-Cache nach Entzug der Admin-Rechte | accept | Siehe AR-10; `CACHE_SECONDS = 30.0` (roles.py:24,67); live K5 Rolle nach Entfernen "spieler" (acceptance-phase3.sh:478-487) | VERIFIED |
| T-03-16 | Information Disclosure | Spieleransicht lädt Verwaltungsdaten | mitigate | PlayerView importiert nur `listMyWorlds` (frontend/src/views/PlayerView.vue:30), App.vue nur `getMe` (frontend/src/App.vue:26,36); `/api/worlds` liefert Kindern 403 (T-03-11) | VERIFIED |
| T-03-17 | Tampering | Manipulierte Einladung (fremde, deaktivierte, erfundene Konten) | mitigate | `invite_user` bestätigt das Konto bei Nextcloud im Namen des Verwalters, sonst `InviteTargetError` (access/service.py:146-150); Gruppen per `group_exists` (:165-166); Gruppenmitglieder nur aktiv (:369); kanonische UID aus Nextcloud (src/gameworld/access/directory.py:72-73), IDs im Pfad URL-kodiert (:63,80); 422 (invites.py:180-182); Tests tests/test_access_service.py:174, tests/test_invites_api.py:146 | VERIFIED |
| T-03-18 | Tampering | Injection über target oder Namen | mitigate | `extra="forbid"`, `target`/`nc_user` max 64 ohne Steuer-/Formatzeichen (invites.py:48-52,88-98); `kind` als Literal (:91); SQL mit Parameterbindung, dynamisch nur Spaltennamen aus Konstanten und `?`-Platzhalter (src/gameworld/worlds/store.py:157,167-170,220-227,272-279); Namen aus `suggest_player_name` mit Regex (src/gameworld/access/accounts.py:28,83); `render_access_file` prüft erneut (T-03-05); Test tests/test_invites_api.py:137 | VERIFIED |
| T-03-19 | Information Disclosure | Leck der ExApp-SQLite oder eines Backups | mitigate | Schema 3: `players` nur nc_user, player_name, rotation; `world_access` nur Verifier (store.py:43-61); Test keine Passwortspalte (tests/test_store.py:155); DB-Bytes ohne Passwort, mit Positivkontrolle Name (tests/e2e/test_invite_join_e2e.py:112-114); live K5 inkl. WAL (acceptance-phase3.sh:489-499). Auditor-Gegenprobe gegen die Dev-DB siehe unten | VERIFIED |
| T-03-20 | Information Disclosure | Leck des Geheimnisses aus appconfig_ex | mitigate | Erzeugung mit `sensitive=True` (src/gameworld/access/secret.py:94), Fehlertext nur mit Ausnahmetyp (:98-100); kein Zugriff aus src/gameworld/api außer Dependency-Übergabe (Grep); kein Feld in API-Modellen; Tests tests/test_accounts.py:156,207 | VERIFIED |
| T-03-21 | Spoofing | Offline-Raten gegen Verifier | mitigate | 12 Zeichen aus 31 = 59,4 Bit aus HMAC-SHA256 (accounts.py:18-20,60-76); Salz `secrets.token_bytes(16)` pro Verifier, also pro Welt und Spieler (luanti_auth.py:31,45); keine Nutzung von `random` (Grep) | VERIFIED |
| T-03-22 | Elevation of Privilege | Kind ruft Invites-API | mitigate | `router = APIRouter(..., dependencies=[Depends(require_verwalter)])` (invites.py:38) plus ADMIN-Route; Tests 403 je Route (tests/test_invites_api.py:112,321) | VERIFIED |
| T-03-23 | Repudiation | Wer hat eingeladen | mitigate | `invites.invited_by` und `created_at` NOT NULL (store.py:48-55), gesetzt aus der signierten UID (access/service.py:155-158,171-174), in der Verwalteransicht ausgegeben (invites.py:124-128,164-167) | VERIFIED |
| T-03-24 | DoS | Nextcloud kurz weg bei Einladung | accept | Siehe AR-11; Auflösung vor der Sperre, nichts halb geschrieben (access/service.py:146-160), 503 mit festem Text (invites.py:183); Test tests/test_access_service.py:186 | VERIFIED |
| T-03-25 | Information Disclosure | Passwort oder Geheimnis im Log | mitigate | Alle LOG-Aufrufe in access/ und api/ geben nur Welt-ID, Ausnahmetyp, Status oder Spielernamen aus (directory.py:67,70,84,87; access/service.py:222,405,562,604; worlds.py:142); Leck-Tests auf DEBUG über Erfolgs- und Fehlerpfade inkl. Verifier-Teilen (tests/test_invites_api.py:178-235,383-456). Auditor-Gegenprobe gegen .dev/exapp.log siehe unten | VERIFIED |
| T-03-26 | Elevation of Privilege | Ausgetretenes oder deaktiviertes Konto behält Zugang | mitigate | `sync_all` beim Verwalter-Besuch, Drossel 60 s (access/service.py:55,201-227), aufgerufen in GET /api/worlds (worlds.py:139-142); nur aktive Konten (:369); Kick-Takt 5 s im Mod (access_mod.py:153-162); Tests tests/test_access_service.py:275,327,359. Live-Kick mit echtem Client offen (AR-20) | VERIFIED |
| T-03-27 | Elevation of Privilege | Austritt wirkt erst beim nächsten Verwalter-Besuch | accept | Siehe AR-12; Code entspricht: kein Hintergrund-Abgleich, lazy Provisionierung nur Hinzufügen (access/service.py:544-563) | VERIFIED |
| T-03-28 | Tampering | Name-Injection über Umbenennen | mitigate | `validate_player_name` (accounts.py:49-57) vor allem anderen (access/service.py:249); NOCASE-Eindeutigkeit in DB (store.py:45) und Prüfung unter der Sperre (access/service.py:256-258); `render_access_file` prüft erneut; Tests tests/test_access_service.py:462, tests/test_store.py:164 | VERIFIED |
| T-03-29 | Spoofing | Geleaktes Spielpasswort | mitigate | `rotate_password`: Rotation +1, alle Verifier neu in einer Transaktion, sofort in jede Welt (access/service.py:229-241,575-585); Test tests/test_access_service.py:419; live altes Passwort WRONG_PASSWORD, neues auth_accept ohne Neustart (acceptance-phase3.sh:400-408) | VERIFIED |
| T-03-30 | Information Disclosure | Geheimniswechsel lässt alte Verifier gültig | mitigate | Fingerabdruck-Vergleich (access/service.py:391-406) in invite_user/group, revoke, sync_world, rotate, rename, sync_all, my_worlds; `reprovision_all` schreibt alle Welten neu (:434-463); Test tests/test_access_service.py:483. AR-25 (Verwalteransicht `list_players` ohne Fingerabdruck-Schritt) ist mit 9e8e5ed behoben | VERIFIED |
| T-03-31 | Information Disclosure | Fingerabdruck verrät Geheimnis | accept | Siehe AR-13; HMAC mit fester Nachricht, auf 16 Hex gekürzt (secret.py:47-58) | VERIFIED |
| T-03-32 | Elevation of Privilege | Kind ruft Passwort-/Namensrouten | mitigate | `/players/password` und `/players/name` im invites-Router mit `require_verwalter` (invites.py:38,231,252); Test tests/test_invites_api.py:321 | VERIFIED |
| T-03-33 | DoS | Nextcloud weg beim Verwalter-Besuch | mitigate | `sync_all` in try/except, nur Warnung mit Ausnahmetyp, Weltenliste kommt trotzdem (worlds.py:139-144); Fehler einer Welt isoliert (access/service.py:219-223); Test tests/test_invites_api.py:356 | VERIFIED |
| T-03-34 | Information Disclosure | Passwörter in der Verwalter-Ansicht | mitigate | Nur hinter ADMIN-Route plus `require_verwalter` (T-03-11); verdeckt bis "Anzeigen", Kopierknopf mit sichtbarem Wert erst nach dem Aufdecken (frontend/src/components/PlayerManager.vue:40-57,166-167,207-209); kein localStorage/sessionStorage/Cookie im Frontend (Grep ohne Treffer) | VERIFIED |
| T-03-35 | Tampering | XSS über Anzeige- oder Gruppennamen | mitigate | Auditor-Grep `v-html`, `innerHTML`, `outerHTML`, `insertAdjacentHTML` in frontend/src: keine Treffer (Positivkontrolle: dasselbe Grep-Verfahren findet `v-if` 12-mal in PlayerManager.vue); einzige SVG-Zeichenkette ist eine Konstante (frontend/src/components/InviteDialog.vue:72) | VERIFIED |
| T-03-36 | Spoofing | Browser liefert manipulierte Konto-IDs | mitigate | Backend bestätigt bei Nextcloud (T-03-17, access/service.py:148-150,363-371) | VERIFIED |
| T-03-37 | Information Disclosure | Weltschlüssel in UI oder API | mitigate | `WorldOut` ohne world_key (worlds.py:78-102), POST /api/worlds gibt `WorldOut` zurück (:147-161); Auditor-Grep `world_key\|worldKey\|weltschl` in src/gameworld/api und frontend/src: nur ein Kommentar (worlds.py:149); Positivkontrolle: Schlüssel weiter in conf (src/gameworld/worlds/service.py:291, luanti_conf.py:47) | VERIFIED |
| T-03-38 | Elevation of Privilege | Laufende Altwelt ohne Zugangsschutz | mitigate | `_access_restart_needed` aus State-Datei gegen StartedAt (worlds/service.py:389-412), Hinweis im Dashboard (frontend/src/views/ParentView.vue:90); Reconciler kennt den Zugangszustand nicht (Grep `access` in src/gameworld/worlds/reconciler.py ohne Treffer), also kein automatischer Neustart; Weltschlüssel schützt bis dahin (luanti_conf.py:46-47); Tests tests/test_service_lifecycle.py:1180-1219 | VERIFIED |
| T-03-39 | Information Disclosure | Kind liest fremde Passwörter oder Namen | mitigate | `/api/my/worlds` nur für die signierte UID (src/gameworld/api/me.py:58-86), Passwort nur für diese UID abgeleitet (access/service.py:565-573), `MyWorldOut` ohne Spielerliste (me.py:29-42); Leck-Test tests/test_my_worlds.py:131 | VERIFIED |
| T-03-40 | Elevation of Privilege | Kind provisioniert sich in fremde Welt | mitigate | Gruppen nur aus der Selbstauskunft (roles.py:49-54, access/service.py:328), nur Welten mit Einladung einer eigenen Gruppe, unter der Sperre neu geprüft, nur Hinzufügen (access/service.py:536-563); Tests tests/test_my_worlds.py:155,193,205 | VERIFIED |
| T-03-41 | Elevation of Privilege | Kind ändert Einstellungen | mitigate | GET/POST /api/settings im invites-Router mit `require_verwalter` (invites.py:38,240-249) plus ADMIN-Route; Test tests/test_settings_api.py:100 | VERIFIED |
| T-03-42 | Tampering | join_host mit Schema, Pfad oder Markup | mitigate | `_clean_host`: leer, IP-Literal oder Hostname-Labels `[A-Za-z0-9-]{1,63}`, kein `://`, `/`, Port, Steuerzeichen, max 253 (invites.py:55-81); Ausgabe nur per Interpolation (kein v-html, T-03-35); Tests tests/test_settings_api.py:84,93 | VERIFIED |
| T-03-43 | Information Disclosure | Externe Aufrufe zur Laufzeit | mitigate | luanti.org nur als Link mit `rel="noopener noreferrer"` (frontend/src/components/JoinGuide.vue:8); Auditor-Grep `luanti.org\|httpx\|aiohttp\|niquests\|urllib.request` in src: nur Docstring-Quellenangabe und Image-Digest, `requests` nur zum Docker-Proxy (setup_check.py, client.py) | VERIFIED |
| T-03-44 | Information Disclosure | Ausgetretenes Gruppenmitglied sieht weiter seine Verbindungsinfo | accept | Siehe AR-14 | VERIFIED |
| T-03-45 | Information Disclosure | Passwörter in Skriptausgabe oder Logs | mitigate | Ausgaben nur über `check`/`pass`/`fail` mit Beschreibungstext (acceptance-phase3.sh:65-92), darin nur Muster, Länge `${#KID_PW}`, Trefferzahlen und sha256-Vergleiche (:340,355,430-431,495-499); Prober druckt nur das Ergebnis-JSON ohne Passwort (tests/e2e/luanti_probe.py:219-236); kein `set -x` in scripts/dev. Rest: Passwort als Prozessargument (AR-18) | VERIFIED |
| T-03-46 | Elevation of Privilege | gw-kind bleibt nach K5 in admin | mitigate | `trap cleanup EXIT` und `trap 'exit 130' INT TERM` (acceptance-phase3.sh:161-162), cleanup ruft `reset_fixtures` (:157) mit `occ group:removeuser admin` (:128-129); Abschlussprüfung "nicht in admin" (:531-533) | VERIFIED |
| T-03-47 | Tampering | Dev-Zugangsdaten im Repo | accept | Siehe AR-15; `.dev/` (inkl. exapp.secret) per .gitignore:1 ausgeschlossen, `git ls-files .dev` leer | VERIFIED |
| T-03-48 | Repudiation | Abnahme ohne Owner | mitigate | Blockierender Checkpoint (.planning/phases/03-zugang-und-rollen/03-07-PLAN.md:121 `checkpoint:human-verify gate="blocking"`), Owner-Verdict "Abgenommen" und Entscheide A6, A8, A9 wörtlich (03-07-SUMMARY.md:83-90) | VERIFIED |

*Status: VERIFIED · PARTIAL · MISSING*
*Disposition: mitigate (Implementierung erforderlich) · accept (dokumentiertes Risiko) · transfer (Dritte/Betreiber)*

### Offene Threats

Keine. 48 von 48 Threats sind VERIFIED, kein PARTIAL, kein MISSING.

### Prüfung der Review-Fixes gegen das Register

| Fix | Commit | Betroffene Threats | Ergebnis |
|-----|--------|--------------------|----------|
| WR-01 Widerruf gewinnt gegen keep-Regel | 7126f94 | T-03-26, T-03-29, T-03-17 | Stärkt den Widerruf: `revoke` löst den widerrufenen Schlüssel mit auf (access/service.py:182-186), `_apply_sync` holt nur über ihn berechtigte Konten nie über `keep` zurück (:500-509) und hebt bei unaufgelösten Schlüsseln die Drossel auf (:496-499); Interleaving-Tests tests/test_access_service.py:586,615,638 |
| WR-02 Kein ungültiges Passwort nach Geheimniswechsel | 0760c7f | T-03-30, T-03-39, T-03-03 | `my_worlds` wertet `_ensure_fingerprint` aus und wirft `SecretUnavailableError` (access/service.py:324-327), API 503 mit festem Text (me.py:63-64); verhindert, dass Kinder sich mit einem noch nicht gültigen Passwort in die Sperre tippen; Test tests/test_my_worlds.py:274 |

### Gegenproben des Auditors (mit Positivkontrolle)

| Prüfung | Ergebnis | Positivkontrolle |
|---------|----------|------------------|
| Passwortmuster `[a-hj-km-np-z2-9]{4}-...{4}-...{4}`, 64-Hex (Geheimnis) und `#1#` (Verifier) in .dev/exapp.log (303 Zeilen, Lauf seit 07:17 mit Abgleich-Einträgen) | 0 / 0 / 0 Treffer | Dieselben drei Muster gegen eine Probedatei im Scratchpad: 1 / 1 / 1 Treffer |
| Dev-DB .dev/storage/gameworld.sqlite3 (read-only, inkl. WAL): Spalten und Inhalte | `players` = nc_user, player_name, rotation; meta-Schlüssel instance_id, join_host, schema_version, secret_fingerprint; Passwortmuster 0, 64-Hex 0 | `#1#` 2 Treffer in freien Seiten (Verifier dürfen in der DB stehen), belegt, dass die Rohsuche die Datei erfasst |
| Routen ohne `require_verwalter` (Router-Abhängigkeiten plus Dependant-Baum, alle 17 Routen) | Nur GET /api/me und GET /api/my/worlds, deckungsgleich mit den USER-Routen in info.xml:65-76 | Die beiden USER-Routen werden als "ohne" erkannt, das Verfahren unterscheidet also |
| `exec_run`/`.exec(` in src | keine Treffer | Live-Gate acceptance-phase3.sh:412-413 (Proxy antwortet 403) |

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-01 bis AR-04 | T-01-* | Unverändert aus Phase 1 (.planning/phases/01-fundament/01-SECURITY.md) | Phase 1 | 2026-10-19 |
| AR-05 bis AR-07 | T-02-* | Unverändert aus Phase 2 (.planning/phases/02-one-click-welten/02-SECURITY.md); AR-07 (Join-Schutz nur über Weltschlüssel) ist mit Phase 3 durch T-03-01/T-03-02 abgelöst | Phase 2 | 2026-10-19 |
| AR-08 | T-03-09 | Fehlversuch-Sperre ist ein Aussperr-Vektor: Jeder im Heimnetz kann einen eingeladenen Namen mit 5 falschen Passwörtern für 10 min sperren und das wiederholen (03-REVIEW IN-05). Bewusster Tausch gegen Online-Raten (A10); Sperre nur im Speicher. Option für Phase 4: zusätzlich pro Quell-IP sperren, ohne IP zu speichern | Plan 03-01 (A10, Owner-bekannt, LAN-Angreifer-Modell) | 2026-10-20 |
| AR-09 | T-03-10 | IP-Adressen abgelehnter Joins stehen nur im Container-Log von Luanti (rotiert 5 MB x 2), nie im Dashboard, nie in Mod-Dateien | Plan 03-01 | 2026-10-20 |
| AR-10 | T-03-15 | Rollen-Cache: Nach Entzug der Admin-Rechte höchstens 30 s Verwalterzugriff; Familienkontext, in docs/install.md Abschnitt 8 dokumentiert | Plan 03-02 | 2026-10-20 |
| AR-11 | T-03-24 | Nextcloud kurz weg bei Einladung: 503 mit deutscher Meldung, nichts halb geschrieben | Plan 03-03 | 2026-10-20 |
| AR-12 | T-03-27 | Austritt aus einer eingeladenen Gruppe wirkt erst beim nächsten Verwalter-Besuch (Abgleich höchstens alle 60 s); kein Hintergrund-Abgleich ohne Nutzerkontext (Open Question 4 DEFERRED) | Plan 03-04 | 2026-10-20 |
| AR-13 | T-03-31 | Fingerabdruck: HMAC-Ausgabe auf 64 Bit gekürzt, nicht umkehrbar, nur in der ExApp-SQLite | Plan 03-04 | 2026-10-20 |
| AR-14 | T-03-44 | Ausgetretenes Gruppenmitglied sieht seine Verbindungsinfo bis zum nächsten Verwalter-Abgleich; bis dahin nur LAN-Spielzugang | Plan 03-06 | 2026-10-20 |
| AR-15 | T-03-47 | Dev-Zugangsdaten in Skripten sind reine Loopback-Dev-Konten, wie in Phase 1/2 dokumentiert | Plan 03-07 | 2026-10-20 |

### Bekannte Restrisiken (Owner-bekannt, keine MISSING)

| Risk ID | Severity | Bezug | Beschreibung | Empfehlung |
|---------|----------|-------|--------------|------------|
| AR-16 | Low | 03-REVIEW IN-04, A5 | Namens-Enumeration: Eine Groß-/Kleinschreibungs-Variante bekommt vor jeder Anmeldung "Achte auf Groß- und Kleinschreibung: Mia" und bestätigt so eingeladene Namen samt Schreibweise (access_mod.py:106-111,141-144). UX-Kompromiss A5; Luanti leakt Ähnliches selbst | Optional Hinweis ohne Namen formulieren |
| AR-17 | Info | 03-REVIEW IN-01 | HMAC-Nachricht `f"{nc_user}:{rotation}"` ist nicht injektiv (accounts.py:69); heute nicht ausnutzbar, weil Nextcloud-Konto-IDs keinen Doppelpunkt erlauben; hängt an einer fremden Invariante | Längenpräfix vor dem ersten Release oder mit bewusster Rotation |
| AR-18 | Info | 03-REVIEW IN-06, T-03-45 | Spielpasswörter als Prozessargumente des Probers (acceptance-phase3.sh:226-231, tests/e2e/luanti_probe.py:229) sind während des Laufs in der Prozessliste sichtbar; Single-User-Dev-Maschine, Wegwerfkonten | Optional `--password-stdin` |
| AR-19 | Low | 03-VERIFICATION | Live-Join mit echtem Luanti-Client nicht geprüft; Ersatzbeleg UDP-Prober mit echtem SRP-Handshake gegen Luanti 5.17.0 und Golden Vector | Beim ersten Client-Test nachholen |
| AR-20 | Low | A7, T-03-26 | Kick laufender Spieler nach Widerruf mit echtem Client nicht live geprüft; der Mod-Code kickt im 5-s-Takt (access_mod.py:153-162) | Owner-offen, mit AR-19 prüfen |
| AR-21 | Low | T-03-30 | Neuinstallations-Randfall: Verlust des Geheimnisses rotiert alle Spielpasswörter einmalig; dokumentiert in docs/install.md Abschnitt 8 und secret.py:7-9 | Keine Codeänderung |
| AR-22 | Info | Hygiene | npm audit 12 low/moderate im Frontend-Build; `.gitattributes` mit `*.sh eol=lf` fehlt (Zeilenenden der Abnahmeskripte) | Mit nächstem Dependency-/Repo-Hygiene-Durchgang |

### Neue Befunde dieses Audits (keine Blocker)

| Risk ID | Severity | Bezug | Beschreibung | Empfehlung |
|---------|----------|-------|--------------|------------|
| AR-23 | Low | T-03-07, Boundary "Welt-Volume -> Luanti-Prozess" | Die Zugangsdatei ist root-eigen 0444 (archive.py:48,135-137), liegt aber im Weltordner, der der Luanti-UID gehört (0755, archive.py:105-109,190-197). Der Luanti-Prozess kann sie deshalb löschen oder per rename ersetzen, und der Mod-Code unter worldmods (Luanti-UID, 0644) ist für Lua im Weltpfad schreibbar. Spieler können das nicht; nötig wäre Codeausführung im Spiel-Lua (VoxeLibre/MTG sind per SHA256 gepinnt, T-02-10). Die ExApp schreibt Datei und Mods bei jeder Änderung bzw. jedem Start neu (worlds/service.py:261-277,467) | Boundary-Beschreibung präzisieren ("root 0444 verhindert nur Überschreiben, nicht Ersetzen"); prüfen, ob `worldmods/gameworld_access` und die Zugangsdatei in ein root-eigenes Verzeichnis passen, das Luantis Mod-Security nur lesend erlaubt |
| AR-24 | Info | T-03-39 | Die Kind-Ansicht übernimmt `status_text` der Weltansicht (me.py:79); bei `failed`-Welten ist das `last_error` (src/gameworld/worlds/status.py:101), der den Erklärtext des Docker-Daemons enthalten kann (Containername mit Instanz-ID, Port). Keine Daten anderer Konten, aber Interna in der Kinderansicht | **Fixed** (efba3d0): `/api/my/worlds` gibt bei `failed` den festen Kindertext aus (me.py, TEXT_WELT_PROBLEM); die Verwalter-Ansicht behält `last_error`. Regressionstest mit Positivkontrolle tests/test_my_worlds.py (test_failed_world_shows_fixed_text_to_child) |
| AR-25 | Low | T-03-30, analog WR-02 | `list_players` (GET /api/worlds/{id}/players) leitet Passwörter aus dem aktuellen Geheimnis ab, ohne `_ensure_fingerprint` (access/service.py:267-298). Scheitert nach einem Geheimniswechsel die nicht blockierende Neuprovisionierung in `sync_all` an einer belegten Sperre (:213-216), zeigt die Verwalteransicht kurzzeitig Passwörter, die die Welten noch nicht kennen; tippt ein Kind sie mehrfach, greift die Sperre. Nur im Neuinstallations-Randfall (AR-21), heilt beim nächsten erfolgreichen Abgleich | **Fixed** (9e8e5ed): `list_players` ruft `_ensure_fingerprint(secret, blocking=False)` vor der Ableitung (außerhalb von worlds.mutation()); bei ausstehender Neuprovisionierung `SecretUnavailableError` -> 503 mit festem Text, kein Passwort im Body. Regressionstest nach WR-02-Muster tests/test_invites_api.py (test_secret_change_with_busy_lock_hides_player_passwords) |

### Informative Hinweise

- **03-REVIEW IN-02:** `_http_error` gibt für jeden `ValueError` `str(exc)` als 422-Detail aus (invites.py:180-182,188). Kein Datenleck (keine Geheimnisse in diesen Texten), nur Abweichung von der Regel "nur feste deutsche Texte".
- **03-REVIEW IN-03, IN-07:** toter Produktionscode `sync_world` und Heimnetz-Heuristik in JoinHostSettings.vue ohne Sicherheitsbezug; die Backend-Validierung von join_host (T-03-42) ist davon unabhängig.
- **Umbenennen:** Ein alter Luanti-Name bleibt als verwaistes Konto in der Welt (access/service.py:243-248, dokumentiert). Wird derselbe Name später einem anderen Konto vergeben, setzt der Prejoin dessen Verifier auf das Altkonto (access_mod.py:147-150) und das neue Kind übernimmt Inventar und Spielstand. Keine Rechteausweitung (kein Konto hat Admin-Privs, T-02-02), nur ein Datenschutz-Detail für Phase 4.
- **Lockout-Schlüssel:** Fehlversuche zählen pro exaktem Namen (access_mod.py:124-135); Varianten in anderer Schreibweise kommen ohnehin nicht über den Prejoin hinaus, kein Umgehungsweg.

### Unregistered Flags

Keine. 03-06-SUMMARY und 03-07-SUMMARY melden unter `## Threat Flags` keine neuen Flächen; 03-01 bis 03-05 haben keinen Abschnitt `## Threat Flags`. Die vom Auditor zusätzlich betrachteten Flächen (lazy Provisionierung durch Kinder-Abrufe, Kind-Ansicht `status_text`, Ersetzbarkeit der Zugangsdatei, Verwalteransicht nach Geheimniswechsel) sind T-03-40, T-03-39, T-03-07 bzw. T-03-30 zugeordnet und als AR-23 bis AR-25 festgehalten.

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-10-20 | 48 | 48 | 0 | gsd-security-auditor (Stand 905f780, nach Review-Fixes 7126f94 und 0760c7f; erster Lauf abgebrochen ohne Artefakt) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-10-20
