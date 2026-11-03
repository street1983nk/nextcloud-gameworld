---
phase: quick-261102-s2p
plan: 01
subsystem: api, ui, testing
tags: [i18n, require_nc_admin, nextcloud-vue, escape, lua51, docker, playwright]
requires:
  - phase: quick-261102-plj
    provides: Befunde B1 bis B8 und Testsuiten-Befund (8 Skips) aus dem Volltest
provides:
  - Server-Texte ohne Python-/pydantic-/Starlette-Rohtexte in de, en, fr
  - Lese-Variante der Admin-403-Meldung (MSG_NC_ADMIN_ONLY_READ)
  - Setup-Check-Link je Sprache (install.de.md für de)
  - Lua-5.1-Syntaxcheck der Welt-Mods ohne Skips (gepinntes Hilfs-Image)
  - Erwachsen-Marke und Schalter aus demselben Zustand
  - Escape schließt Einladen, Zeitfenster und Spieler auch mit Fokus in einem Feld
  - parallele Abfrage der Verwaltergruppen (POST /api/players/adult 8,8 s auf 2,8 s)
affects: [store-release-1.0, phase-06]
tech-stack:
  added: ["Test-Hilfs-Image nickblah/lua:5.1.5-alpine@sha256:4d1e728a... (nur e2e-Test, nicht im ExApp-Image)"]
  patterns:
    - "Escape aus Formularfeldern: Capture-Handler am Dialoginhalt ruft escapeShouldClose (frontend/src/dialogKeys.js) und den eigenen Schließweg"
    - "Leitfaden-Link als fester Text je Sprache statt Platzhalter, damit Übersetzungen nie den deutschen Link mitnehmen"
key-files:
  created:
    - frontend/src/dialogKeys.js
    - frontend/tests/dialogKeys.check.mjs
  modified:
    - src/gameworld/provisioner/setup_check.py
    - src/gameworld/i18n/catalog_en.py
    - src/gameworld/i18n/catalog_fr.py
    - src/gameworld/playtime/plan.py
    - src/gameworld/playtime/service.py
    - src/gameworld/api/language.py
    - src/gameworld/access/roles.py
    - frontend/src/components/PlayerManager.vue
    - frontend/src/components/InviteDialog.vue
    - frontend/src/components/WorldWindowDialog.vue
    - frontend/src/views/ParentView.vue
    - tests/e2e/test_mod_syntax_e2e.py
    - tests/test_api_language.py
    - tests/test_docs.py
    - tests/test_frontend_checks.py
    - tests/test_playtime_plan.py
    - tests/test_route_guards.py
    - tests/test_setup_check.py
    - tests/test_verwalter_groups.py
key-decisions:
  - "Setup-Check: Link ist fester Text je Sprache (kein {docs_url}-Platzhalter mehr); de zeigt install.de.md, en und fr install.md (keine install.fr.md vorhanden)"
  - "require_nc_admin bekommt den Request nur für die Textwahl (GET/HEAD = sehen, sonst ändern); Prüfung, Frische und Statuscodes unverändert"
  - "pydantic- und Starlette-Texte werden auch für en ersetzt; bestehender en-Text 'The input is not valid.' bleibt (nicht umformuliert)"
  - "Lua-Hilfs-Image nickblah/lua:5.1.5-alpine per Digest gepinnt (GUI/lua-docker, MIT, baut aus lua.org-Tarball mit SHA-1-Prüfung, seit 2021 eingefroren)"
  - "Erwachsen einschalten bleibt serverbestätigt (06-05: Bestätigung mit Ladeanzeige, Fehler im Bestätigungsdialog); keine optimistische Anzeige, daher Marke an = Dauer von POST /api/players/adult"
  - "Ursache der langen Speicherdauer behoben: Verwaltergruppen wurden nacheinander bei Nextcloud abgefragt (etwa 2 s je Gruppe), jetzt nebeneinander"
metrics:
  duration: "ca. 2 h 15 min"
  completed: 2026-11-02
---

# Quick 261102-s2p: Fixes aus dem Volltest 261102-plj Summary

Acht Owner-Punkte aus dem Volltest umgesetzt: Server-Texte ohne Rohtexte und mit Lese-Variante der Admin-Meldung, Setup-Check-Link je Sprache, Lua-5.1-Syntaxcheck ohne Skips, Erwachsen-Marke gekoppelt an den Schalter samt paralleler Gruppenabfrage im Backend, Escape in Dialogen mit Feldfokus, Weltentabelle wartet nicht mehr auf die eigenen Welten.

## Commits

| Task | Commit | Inhalt |
|------|--------|--------|
| 1 | 8040b50 | Server-Texte (Punkte 4 bis 7), Lua-5.1-Syntaxcheck (Punkt 8) |
| 2 | 5f6ef10 | Erwachsen-Marke (Punkt 1) mit Backend-Ursache, Escape (Punkt 3) |
| 3 | dbcde4a | Weltentabelle sofort nach der Verwalterliste (Punkt 2) |

Autor street1983nk, keine Co-Author-Zeilen, nicht gepusht.

## Je Punkt: Ursache, Fix, Tests

### Punkt 1 (B1): Erwachsen-Marke hinkt nach

- Ursache (gemessen, `.dev/audit/261102-s2p/before/adult-timeline.json`): Die Marke hing an `player.adult` aus der Serverliste. Einschalten: POST /api/players/adult dauerte 8,86 s, danach GET /players weitere 4,17 s, erst dann erschien die Marke (13,07 s); der Schalter sprang nach 8,96 s (nach dem POST). Ausschalten: Schalter sofort (8 ms, optimistisch), Marke erst nach POST 8,70 s plus GET /players 2,11 s (10,81 s).
- Backend-Ursache des langsamen POST: `refresh_admins(force=True)` liest alle Verwaltergruppen (admin, eltern, lehrkraefte, parents) nacheinander bei Nextcloud, im Log etwa 2 s je Gruppe.
- Fix Frontend: NcChip-Bedingung `v-else-if="adultShown[player.nc_user]"`, also derselbe Zustand wie der Schalter; die Rücksetzlogik im catch setzt damit Schalter und Marke gemeinsam zurück.
- Fix Backend: `_read_groups` liest die Gruppen nebeneinander (Task-Gruppe, höchstens 8 gleichzeitig); je Gruppe bleiben die Kandidaten in ihrer Reihenfolge, die 403-/Störungsregel je Gruppe ist unverändert, unerwartete Fehler werden wie vorher unverpackt geworfen (der erste in Gruppenreihenfolge). Keine Prüfung gelockert, kein Cache.
- Tests: `test_manager_groups_are_read_side_by_side` (Gleichzeitigkeit 3, Ergebnis wie nacheinander; Positivkontrolle: mit GROUP_READS = 1 schlägt der Test fehl), `test_parallel_read_keeps_the_403_rule_per_group`, `test_parallel_read_raises_an_unexpected_error_unwrapped`, statisch `test_adult_chip_reads_the_switch_state`.
- Ergebnis: siehe Tabelle. Ausschalten jetzt 7 ms (unter 1 s). Einschalten jetzt 2,80 s und damit NICHT unter 1 s: Marke und Schalter erscheinen zwar im selben Render (2,80 s / 2,86 s), aber erst nach der Serverantwort. Das ist die bestehende Owner-Entscheidung 06-05 (Bestätigung mit Ladeanzeige, Fehler bleibt im Bestätigungsdialog, Schalter folgt der Serverantwort). Unter 1 s ginge nur mit optimistischer Anzeige vor der Serverbestätigung; das habe ich bewusst nicht gebaut (offener Punkt unten).

### Punkt 2 (B2): Ladezeit Admin-Hauptansicht

- Messung vorher (heute, `.dev/audit/261102-s2p/before/loadtimes.json`): admin Median 2,40 s, also schon unter 3 s; der Wert 3,06 s aus 261102-plj war ein anderer Lastzustand. Langsamster Aufruf für die Tabelle ist /api/worlds selbst (Median 1,78 s); listMyWorlds kostet für admin nur etwa 40 ms.
- Fix: `refresh()` setzt die Weltentabelle sofort nach listWorlds und lädt die eigenen Welten danach; Reihenfolge und seq-Prüfung beider Zuweisungen bleiben. Zweiter Schritt (Admin-Abschnitte verzögern) nicht nötig, da der Median unter 3 s liegt. Kein Backend-Eingriff an require_nc_admin, CACHE_SECONDS unverändert.
- Ehrliche Einordnung: Der Fix spart für admin nur die Dauer von listMyWorlds (etwa 40 ms); die Verbesserung liegt im Messrauschen. Der Hauptanteil ist /api/worlds (Docker-Liste und Stats auf dem Windows-Dev-Host).
- Negativprobe nach dem Fix (`.dev/audit/261102-s2p/after/guard-probe.json`): gw-lehrer und mia bekommen auf /api/admin/orphans, /api/admin/verwalter-groups und /api/admin/groups 403 in de, en, fr; Admin-Abschnitte im DOM für gw-lehrer und mia 0, für admin 2. test_route_guards und test_orphan_section_gate grün.

### Punkt 3 (B3): Escape in Dialogen

- Ursache (nachgelesen in `frontend/node_modules/@nextcloud/vue/dist/chunks/NcModal.mjs` Zeile 131 und `dist/composables/useHotKey/index.mjs` Zeile 6 bis 10): NcModal schließt über `useHotKey("Escape", ..., { allowInModal: true })`; `shouldIgnoreEvent` verwirft aber jedes Tastenereignis, dessen Ziel ein `HTMLInputElement`, `HTMLTextAreaElement`, `HTMLSelectElement` oder contenteditable ist. Einladen öffnet mit Fokus im Suchfeld (Input), Zeitfenster mit Fokus auf dem ersten Schalter (Checkbox-Input), im Spieler-Dialog liegt der Fokus nach "Abbrechen" der Erwachsen-Bestätigung auf dem Schalter-Input bzw. nach "Abbrechen" von Neues Passwort/Name ändern auf keinem Element mehr (Knopf entfernt). vue-select (`@nextcloud/vue-select`, onEscape) schließt bei Escape nur die eigene Liste bzw. leert die Suche und lässt das Ereignis weiterlaufen.
- Fix: neues Modul `frontend/src/dialogKeys.js` (`escapeShouldClose`): nur Escape ohne Modifier, nur bei Fokus in einem Feld (dort, wo NcModal nicht greift, also nie doppelt), nicht während einer IME-Eingabe, und nicht, solange die Auswahlliste offen ist oder Suchtext steht (dann gehört das erste Escape der Liste). InviteDialog, WorldWindowDialog und der Spieler-Dialog fangen Escape in der Capture-Phase am Dialoginhalt ab und schließen über ihren vorhandenen Schließweg (`close()` mit Sperre während `inviting` bzw. `saving`, im Spieler-Dialog `emit('close')` wie bisher). Die Erwachsen-Bestätigung ist ein eigener Dialog (v-else) ohne diesen Handler und schließt weiter nur sich selbst. Zusätzlich gibt Abbrechen (und Erfolg) von Neues Passwort und Name ändern den Fokus an den auslösenden Knopf zurück.
- Tests: `frontend/tests/dialogKeys.check.mjs` (läuft über test_frontend_checks), statische Prüfungen `test_field_dialogs_close_on_escape`, `test_player_dialog_closes_on_escape_from_fields`, `test_player_dialog_returns_focus_after_cancel`, `test_adult_confirmation_keeps_its_own_escape`.
- Browser-Nachweis (`.dev/audit/261102-s2p/after/escape.json`, Wegwerf-Welt, de/en/fr, admin und gw-lehrer, 1280 px): 54 von 54 Fällen schließen mit dem ersten Escape, Escape in der Erwachsen-Bestätigung schließt in allen 6 Durchläufen nur die Bestätigung, Sicherungen und Löschen schließen weiterhin. Nicht im Browser geprüft: Escape bei offener Vorschlagsliste (die Liste öffnet beim Fokus nicht von selbst, listOpen 0); dieser Fall ist im Node-Check abgedeckt. 390 px nicht erneut gemessen.

### Punkt 4 (B4): Setup-Check-Link

- Fix: `DOCS_URL` (install.md, en/fr) und neu `DOCS_URL_DE` (install.de.md); deutsche Texte tragen `Anleitung: <install.de.md>`, die Kataloge en/fr `Guide: <install.md>`. Der Link ist kein `{docs_url}`-Platzhalter mehr, sonst hätte die Vorlagen-Übersetzung den deutschen Link in die en/fr-Texte übernommen. docs/install.fr.md gibt es nicht, daher fr auf install.md.
- Tests: test_docs prüft beide URLs gegen den Anker setup-check der jeweiligen Datei; `test_german_messages_link_the_german_guide` (Gegenprobe: kein "install.md#" im deutschen Text); `test_setup_check_in_english` erweitert um fr und die Gegenprobe "kein install.de.md" in en/fr.

### Punkt 5 (B6): Tageslimit-Meldung

- None heißt fachlich "kein Tageslimit" (Dialogoption "ohne Limit", `noLimitOption()` mit value null); der Dialog bietet 15 bis 240 Minuten, 0 ist nur über die API erreichbar.
- Tests: `test_limit_out_of_range_message_has_no_python_none` (0, 1441, -1 in de/en/fr, "None" case-sensitiv), `test_limit_bounds_and_no_limit_stay_valid` (1, 1440, None). Live (`msg-probe.json`): 422 mit neuem Text in allen drei Sprachen.
- Restliche grep-Treffer auf "or None." sind englische Docstrings in backup/files.py und worlds/store.py, keine Nutzertexte.

### Punkt 6 (B7): Rohtexte für en

- Fix in `api/language.py`: `translate_validation_message` liefert für jede Sprache MSG_INVALID_INPUT ("Value error, "-Meldungen weiter übersetzt in Kontosprache); `_translated_http_exception` ersetzt Starlette-Statusphrasen für jede Sprache durch MSG_REQUEST_FAILED.
- Tests: bestehende en-Erwartungen umgestellt; neu `test_pattern_literal_and_length_errors_are_never_raw` (Muster, Literal, Listenlänge in de/en/fr, "should match pattern", "Input should be", "should have at least" nicht im Körper), Positivkontrolle `test_valid_shapes_still_pass`, `test_value_error_keeps_the_account_language`, `test_method_not_allowed_is_never_raw`.
- Hinweis: Das 422-JSON enthält im Feld `ctx` weiterhin technische Angaben (z. B. das Regex-Muster); das war für de/fr schon vorher so, wird von der Oberfläche nicht angezeigt und ist nicht Teil dieses Auftrags.

### Punkt 7 (B8): Admin-403 beim Lesen

- Fix: `MSG_NC_ADMIN_ONLY_READ`, `nc_admin_only_text(method)`; `require_nc_admin(uid, roles, request)` wählt nur den Text (GET/HEAD = sehen, alles andere = ändern). Prüfung (`roles.nc_admin` frisch bei jeder Anfrage), 403/503 und Ausnahmeweg unverändert. Frontend gleicht den alten Text nirgends wörtlich ab.
- Negativtests: `test_nc_admin_refusal_text_follows_the_method` (GET, HEAD, get, POST, PUT, PATCH, DELETE, OPTIONS, je 403 und frische Abfrage), `test_nc_admin_passes_for_admin_with_every_method`, `test_nc_admin_outage_is_503_for_every_method`, `test_reading_admin_routes_say_see` (gw-lehrer und Kind, drei Routen, de/en/fr), `test_changing_admin_routes_still_say_change` (vier schreibende Routen), `test_admin_still_reads_admin_routes`. Route-Guard-Tests: Anzahl gesperrter Routen und Statuscodes unverändert (7 Admin-Routen), nur die erwartete Meldung folgt der Methode.

### Punkt 8: Lua-5.1-Syntaxcheck ohne Skips

- `tests/e2e/test_mod_syntax_e2e.py` nutzt `LUA51_IMAGE = "nickblah/lua:5.1.5-alpine@sha256:4d1e728ab63affad53db672f363ec2f416d83decbfd4c9741ee1055e112485c8"`, `luac -p /tmp/init.lua`, `network_disabled=True`, User 30000, Container immer entfernt. Fixture zieht das Image per Digest über den Socket-Proxy, wenn es fehlt (geprüft: Image gelöscht, Test zog es selbst, 9/9 grün); ein gescheiterter Pull lässt den Test fehlschlagen, kein Skip.
- Zusätzlich `test_helper_compiler_is_lua_51` (luac -v beginnt mit "Lua 5.1") und `test_lua52_goto_is_rejected` (goto/Label aus Lua 5.2 scheitern, der Check ist also nie laxer als LuaJIT). Positivkontrolle `test_broken_line_is_rejected` unverändert.
- Ergebnis: 10 passed, 0 skipped (vorher 8 skipped). Alle 7 generierten init.lua parsen unter Lua 5.1.

#### Herkunft Hilfs-Image (geprüft 02.11.2026)

| Punkt | Wert |
|-------|------|
| Referenz | nickblah/lua:5.1.5-alpine@sha256:4d1e728ab63affad53db672f363ec2f416d83decbfd4c9741ee1055e112485c8 |
| Quelle | Docker Hub nickblah/lua (737 431 Pulls), gebaut von github.com/GUI/lua-docker (MIT, aktiv, nicht archiviert) |
| Bau (docker history) | `curl https://www.lua.org/ftp/lua-5.1.5.tar.gz` plus `sha1sum -c` (b3882111ad02ecc6b972f8c1241647905cb2e3fc), Basis Alpine 3.12.7 |
| Erstellt | 2021-04-16, 5.1-Tags werden nicht mehr neu gebaut (Digest stabil) |
| Config | Volumes leer, User leer, Entrypoint leer, Cmd ["lua"], linux/amd64 |
| luac -v | `Lua 5.1.5  Copyright (C) 1994-2012 Lua.org, PUC-Rio` (`docker run --rm --network none`) |
| Einsatz | nur e2e-Test, nicht im ExApp-Image; ohne Netz, unprivilegiert, nur Parsen |
| Restrisiko | Alpine 3.12 ist ohne Sicherheitsupdates; vertretbar, da der Container kein Netz hat, nichts ausführt außer luac -p auf eigenem ASCII-Quelltext und sofort entfernt wird. Alternative bei Bedarf: imolein/lua:5.1 (codeberg.org/imo/lua-dockerfiles, wöchentlich neu gebaut, 22 272 Pulls) |

## Messwerte vorher / nachher

| Messung | Vorher | Nachher | Beleg |
|---------|--------|---------|-------|
| Marke an (adultOnChipMs) | 13 066 ms (plj: 11 300 ms) | 2 799 ms | adult-timeline.json |
| Schalter an | 8 958 ms | 2 859 ms | adult-timeline.json |
| Marke aus (adultOffChipMs) | 10 808 ms (plj: 13 100 ms) | 7 ms | adult-timeline.json |
| Schalter aus | 8 ms | 10 ms | adult-timeline.json |
| POST /api/players/adult (an / aus) | 8 857 / 8 697 ms | 2 798 / 2 566 ms | adult-timeline.json |
| admin Weltentabelle sichtbar, Median / Max | 2 401 / 2 799 ms (plj: 3 060 / 4 490) | 2 373 / 2 435 ms | loadtimes.json |
| admin mit Spielzeitliste, Median / Max | 2 667 / 2 922 ms | 2 798 / 3 167 ms | loadtimes.json |
| gw-lehrer sichtbar, Median / Max | 2 808 / 2 973 ms (plj: 2 410 / 2 660) | 2 372 / 2 829 ms | loadtimes.json |
| mia sichtbar, Median / Max | 1 764 / 1 945 ms (plj: 1 750 / 1 980) | 1 751 / 1 997 ms | loadtimes.json |
| Escape schließt (Einladen, Zeitfenster, Spieler) | 0 von 36 (plj, report.json) | 54 von 54 inkl. Spieler nach Abbrechen, Sicherungen und Löschen | escape.json |
| Escape in Erwachsen-Bestätigung schließt nur sie | nicht gemessen | 6 von 6 | escape.json |
| test_mod_syntax_e2e.py | 8 skipped | 10 passed, 0 skipped | pytest |

Alle Ladezeiten: Sprache de, je 3 Ladevorgänge, Dev-Host unter Windows. "admin mit Spielzeitliste" liegt nachher im Max knapp über 3 s (Rauschen; /api/playtime Median 2,32 s unverändert).

## Neue und geänderte nutzersichtbare Texte (wörtlich, zur Owner-Prüfung)

1. Tageslimit (plan.MSG_LIMIT_RANGE), geändert
   - de: Das Tageslimit muss zwischen 1 und 1440 Minuten liegen. Ohne Angabe gilt kein Tageslimit.
   - en: The daily limit must be between 1 and 1440 minutes. Without a value there is no daily limit.
   - fr: La limite quotidienne doit être comprise entre 1 et 1440 minutes. Sans valeur, il n’y a pas de limite quotidienne.
2. Admin-Ablehnung beim Lesen (roles.MSG_NC_ADMIN_ONLY_READ), neu
   - de: Nur Nextcloud-Admins dürfen das sehen.
   - en: Only Nextcloud admins can see this.
   - fr: Seuls les administrateurs Nextcloud peuvent voir ceci.
3. Admin-Ablehnung beim Ändern (unverändert, gilt jetzt nur für schreibende Anfragen)
   - de: Nur Nextcloud-Admins dürfen das ändern.
   - en: Only Nextcloud admins can change this.
   - fr: Seuls les administrateurs Nextcloud peuvent modifier ceci.
4. Ungültige Eingabe (api_language.MSG_INVALID_INPUT), Text unverändert, jetzt auch für en statt pydantic-Rohtext
   - de: Die Eingabe ist ungültig.
   - en: The input is not valid.
   - fr: La saisie n’est pas valide.
5. Anfrage nicht ausführbar (api_language.MSG_REQUEST_FAILED), Text unverändert, jetzt auch für en statt "Not Found" / "Method Not Allowed"
   - de: Diese Anfrage kann Gameworld nicht ausführen.
   - en: Gameworld cannot carry out this request.
   - fr: Gameworld ne peut pas exécuter cette requête.
6. Setup-Check: alle 17 Meldungen mit Anleitungslink, nur der Link geändert
   - de: "... Anleitung: https://github.com/street1983nk/nextcloud-gameworld/blob/master/docs/install.de.md#setup-check"
   - en: "... Guide: https://github.com/street1983nk/nextcloud-gameworld/blob/master/docs/install.md#setup-check" (unverändert)
   - fr: "... Guide : https://github.com/street1983nk/nextcloud-gameworld/blob/master/docs/install.md#setup-check" (unverändert, geschütztes Leerzeichen U+00A0 vor dem Doppelpunkt wie bisher)
   - Beispiel de: Der Docker-Proxy unter gameworld-docker-proxy:2375 nimmt keine Verbindung an. Läuft der Container gameworld-docker-proxy? Anleitung: https://github.com/street1983nk/nextcloud-gameworld/blob/master/docs/install.de.md#setup-check

Hinweis: Im Plan stand für en "The input is invalid."; der Katalog hatte schon "The input is not valid." und laut Plan werden vorhandene en-Texte nicht umformuliert. Keine neuen Frontend-Texte. Detektorprüfung der Texte oben: kein Fremdworttreffer in de/en/fr, Positivkontrolle (deutscher Satz als en) meldet de.

## Gates

- ruff check und ruff format --check: grün; pyright basic (PYRIGHT_PYTHON_FORCE_VERSION=latest): 0 errors; vulture: grün.
- pytest -m "not docker": 3065 passed, 54 deselected, 0 failed (6:33 min).
- Frontend: test_frontend_checks (18), test_frontend_i18n, test_frontend_privacy grün; Build über register-exapp.sh ok.
- dump_catalog.py und selftest.mjs: SELFTEST PASSED (Exit 0).
- GAMEWORLD_REQUIRE_DOCKER=1 pytest -m docker tests/e2e/test_mod_syntax_e2e.py: 10 passed, 0 skipped; docker volume ls vor und nach dem Lauf identisch, keine Hilfscontainer übrig.
- Textprüfung aller geänderten Dateien: keine U+2013/U+2014, keine Emojis.

## Aufräumnachweis

- cleanup.mjs --dry-run: audit worlds left: 0. Alle drei Wegwerf-Welten (zweimal audit261102-s2p-adult, einmal audit261102-s2p-esc) per DELETE 204 entfernt.
- docker ps -a und docker volume ls gegen `.dev/audit/261102-s2p/baseline.txt`: identisch (CONTAINERS_IDENTICAL, VOLUMES_IDENTICAL), keine Container oder Volumes mit audit261102; Welten 788fff30-/a60510fd- nicht angefasst.
- lang-Settings: admin = de, gw-lehrer = ungesetzt, mia = fr (wie vorher).
- mia nach jedem Messlauf nicht erwachsen (miaAdultAfter false).
- Verwaltergruppen nicht verändert (functional.mjs SECTIONS=2 bewusst nicht gefahren, eigene Zeitachsen-Skripte im Scratchpad statt dessen).
- Hilfs-Image nickblah/lua liegt lokal (nur per Digest), darf bleiben.
- git status: nur .planning/config.json (vorher schon geändert) und der Aufgabenordner.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Backend-Ursache von B1 behoben (POST /api/players/adult 8,8 s)**
- Found during: Task 2 (Zeitachse vor dem Fix)
- Issue: Verwaltergruppen wurden nacheinander bei Nextcloud gelesen.
- Fix: parallele Abfrage in `_read_groups`, Regeln je Gruppe unverändert. Datei `src/gameworld/playtime/service.py`, Tests in `tests/test_verwalter_groups.py`.
- Commit: 5f6ef10

**2. [Rule 1 - Bug] Escape im Spieler-Dialog auch nach Abbrechen der Erwachsen-Bestätigung**
- Found during: Task 2 (Audit-Ablauf endet mit Abbrechen der Bestätigung, Fokus auf dem Schalter-Input)
- Fix: derselbe Capture-Handler wie bei Einladen und Zeitfenster auch im Spieler-Dialog (nur im Hauptdialog, nicht in der Bestätigung).
- Commit: 5f6ef10

**3. [Rule 2] Neue Datei `frontend/src/dialogKeys.js` plus `frontend/tests/dialogKeys.check.mjs`**
- Gemeinsame, testbare Logik statt drei Kopien; nicht in der Dateiliste des Plans.

**4. Statische Prüfung für ParentView in tests/test_frontend_checks.py (Task 3)**

**5. Zusatztests im Lua-Check** (`luac -v`, goto-Ablehnung): 10 statt der geplanten 9 Tests.

## Offene Punkte

1. Marke an unter 1 s nicht erreicht (2,80 s): Die Anzeige wartet bewusst auf die Serverbestätigung (06-05). Restdauer des POST: parallele Gruppenabfrage (etwa 2 s für die langsamste Gruppe auf dem Dev-Nextcloud) plus Schreiben der Regeldateien. Owner-Entscheid nötig, ob "Als erwachsen markieren" optimistisch anzeigen soll (dann Fehler nachträglich im Spieler-Dialog statt im Bestätigungsdialog).
2. Admin-Ladezeit: Hauptanteil /api/worlds (1,7 s) und die parallelen Admin-Abfragen; weitere Beschleunigung nur im Backend (Docker-Stats), nicht Teil dieses Auftrags.
3. 422-JSON trägt in `ctx` technische Details (Regex-Muster), für alle Sprachen, nicht sichtbar in der Oberfläche.

## Self-Check: PASSED

Dateien dialogKeys.js, dialogKeys.check.mjs, Belege escape.json, loadtimes.json, adult-timeline.json vorhanden; Commits 8040b50, 5f6ef10, dbcde4a vorhanden.
