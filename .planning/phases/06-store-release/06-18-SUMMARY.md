---
phase: 06-store-release
plan: 18
subsystem: backend, i18n
tags: [i18n, backend, d-25, exception-handler, account-language]
requires: ["06-12"]
provides:
  - "src/gameworld/i18n: normalize_language, translate, translate_optional, placeholders, SUPPORTED_LANGUAGES, SOURCE_LANGUAGE, FALLBACK_LANGUAGE"
  - "src/gameworld/i18n/catalog_en.py, catalog_fr.py: MESSAGES (144) und TEMPLATES (24) je Sprache, Schlüssel = importierte deutsche Konstanten"
  - "src/gameworld/api/language.py: request_language, LangDep, language_of, install_language_handlers"
  - "RoleService.language(uid) und Profile.language aus der bestehenden Selbstauskunft; GET /api/me liefert language"
  - "tests/i18n_exceptions.tsv: 13 interne raise-Literale mit Grund, vom AST-Test in beide Richtungen abgeglichen"
affects: [06-22, 06-23]
tech-stack:
  added: []
  patterns:
    - "Deutsch ist Nachrichten-ID (gettext-Prinzip): Dienste werfen deutsche Konstanten, übersetzt wird an der API-Grenze"
    - "Meldungen mit Werten als TEXT_-Schablone mit {name} plus .format() an der Aufrufstelle, nie f-String in raise"
    - "Gespeicherte Texte (last_error, Auftragsmeldungen) werden beim Ausliefern übersetzt, nie beim Speichern"
    - "Französisch im Quelltext: \\u00a0 vor ? ! ; : und \\u2019 als Apostroph (Escapes, RUF001)"
key_files:
  created:
    - src/gameworld/i18n/__init__.py
    - src/gameworld/i18n/catalog_en.py
    - src/gameworld/i18n/catalog_fr.py
    - src/gameworld/api/language.py
    - tests/test_i18n.py
    - tests/test_api_language.py
    - tests/i18n_exceptions.tsv
  modified:
    - src/gameworld/access/roles.py
    - src/gameworld/access/secret.py
    - src/gameworld/api/alerts.py
    - src/gameworld/api/backups.py
    - src/gameworld/api/csrf.py
    - src/gameworld/api/me.py
    - src/gameworld/api/playtime.py
    - src/gameworld/api/setup_check.py
    - src/gameworld/api/worlds.py
    - src/gameworld/config.py
    - src/gameworld/main.py
    - src/gameworld/playtime/plan.py
    - src/gameworld/provisioner/archive.py
    - src/gameworld/provisioner/client.py
    - src/gameworld/provisioner/presets.py
    - src/gameworld/provisioner/setup_check.py
    - src/gameworld/worlds/ports.py
    - tests/conftest.py
    - tests/test_roles.py
    - tests/test_verwalter_groups.py
decisions:
  - "Übersetzung an der API-Grenze mit Deutsch als Nachrichten-ID; Kontosprache aus der gecachten Nextcloud-Selbstauskunft (UserInfo.language), Rückfall en"
  - "RoleService.language fragt nach einer gescheiterten Selbstauskunft (30 s) nie erneut bei Nextcloud nach; nc_admin merkt sich nur die Sprache, nie das Profil (Rollen-Cache unverändert)"
  - "Konto nie gesehen und Nextcloud gestört: 503 auf Englisch (Rückfall en), test_roles angepasst"
  - "Setup-Check-Link als Platzhalter: 'Anleitung: {docs_url}' gehört zum übersetzten Text (en 'Guide:', fr 'Guide :')"
  - "Unbekannte Spielart und 'gemeldet: unbekannt' als vollständige Katalogeinträge mit übersetzten Einsätzen, nicht als Schablone"
  - "CSRF-Ablehnung (Middleware) und Konfigurationsfehler (config.py) zusätzlich übersetzt, obwohl nicht in der Dateiliste des Plans"
metrics:
  duration: "95 min"
  completed: "2026-10-24"
  tasks: 3
  files: 27
---

# Phase 6 Plan 18: Server-Texte nach Kontosprache Summary

Backend-Texte in der Nextcloud-Kontosprache: deutscher Text als Nachrichten-ID, Übersetzung an der API-Grenze (Exception-Handler, Validierungs-Handler, Antwort-Serialisierer, CSRF-Middleware), Sprache aus der ohnehin gecachten Selbstauskunft, Rückfall Englisch; Kataloge EN/FR mit 144 Meldungen und 24 Schablonen je Sprache, deutsch nachweislich zeichengleich.

**Basis-Commit (BASE):** `bc6dfb53123bc48f756619736faa6f84a72bcbf5` (bc6dfb5). Alle Diff-Nachweise laufen gegen diese ID.

## Commits

| Task | Commit | Inhalt |
|------|--------|--------|
| 1 | a6d05c1 | i18n-Kern, Profile.language, RoleService.language, Handler, /api/me language, Kern- und Handlertests |
| 2 | 1740860 | voller Katalog EN/FR, Schablonen statt f-Strings, übersetzte Antwortfelder, Abdeckungs-, Platzhalter-, Rundlauf-, Typografie- und Routentests |
| 3 (RED) | 4c8ae07 | AST-Scanner mit Positivkontrolle, Abgleich der Ausnahmenliste, Routentests Playtime-422 und Orphan-409 |
| 3 (GREEN) | 6dff83e | raise-Texte als Konstanten mit Katalogeintrag, tests/i18n_exceptions.tsv mit 13 internen Literalen |

## Katalogumfang

- en: 144 Einträge in MESSAGES, 24 in TEMPLATES (168)
- fr: 144 Einträge in MESSAGES, 24 in TEMPLATES (168); gleiche Schlüsselmenge wie en (Test)
- Abgedeckt: 169 Konstanten in den API-nahen Modulen (mehrere Konstanten tragen denselben deutschen Text, etwa MSG_UNAVAILABLE in roles, directory, invites, playtime), dazu Spielart-Titel und -Beschreibungen
- AST-Scan raise/HTTPException: 13 verbleibende Literale, alle intern und in tests/i18n_exceptions.tsv

## Übersetzte Antwortfelder

- `WorldOut.status_text`, `WorldOut.preset_title`, `WorldOut.last_error` (gespeichert), `WorldOut.backup_job.message` (gespeichert) in /api/worlds, POST /api/worlds, start/stop/restart und in den Antworten von POST backups/restore (api/backups.py `_current`)
- `PresetOut.title`, `PresetOut.description` (/api/presets)
- `MyWorldOut.status_text` (/api/my/worlds, auch TEXT_WELT_PROBLEM und TEXT_WELT_PAUSE)
- `CheckItemOut.message` (/api/setup-check, auch Befund "config")
- `ReviewWorldOut.world_name` nur für den Platzhalter DELETED_WORLD (/api/review)
- `MeOut.language` neu
- Jedes `HTTPException.detail` (String) und jede `msg` aus eigenen Validatoren ("Value error, ..."), dazu das detail der CSRF-Ablehnung
- Geprüft und bewusst nicht übersetzt (Nutzerdaten oder API-Werte): Welt- und Spielernamen, Anzeigenamen, `PlayerOut.via`, `StateOut.reason`, `StateOut.next_hint` (Token wie `Sa-10:00`, wertet die Oberfläche aus), `clock`, `until_clock`

## Gate-Ergebnisse

- `uv run ruff check`: All checks passed; `uv run ruff format --check`: 202 files already formatted
- `PYRIGHT_PYTHON_FORCE_VERSION=latest uv run pyright`: 0 errors, 0 warnings
- `uv run vulture`: kein Befund
- `uv run pytest -m "not docker" -q`: 2675 passed, 44 deselected (Stand nach Task 3; vor dem Plan 2591)
- `uv run pytest -q tests/test_i18n.py tests/test_api_language.py tests/test_playtime_api.py tests/test_orphans.py tests/test_provisioner_errors.py`: 239 passed
- `grep -n "normalize_language(info.language)" src/gameworld/access/roles.py`: genau 1 Treffer; `grep -n "install_language_handlers(APP)" src/gameworld/main.py`: genau 1 Treffer
- `grep -c` auf echtes U+00A0 und U+2019 in src/gameworld/i18n: 0 (nur Escapes; zusätzlich im Test geprüft)

### Diff-Nachweise gegen BASE

- `git diff --stat BASE -- tests/`: conftest.py, i18n_exceptions.tsv, test_api_language.py, test_i18n.py (neu bzw. erlaubt) sowie test_roles.py (5 Zeilen) und test_verwalter_groups.py (1 Zeile), siehe Abweichungen 1 und 2. Keine deutsche Soll-Zeichenfolge geändert.
- Literal-Gegenprobe (Skript im Scratchpad, `literal_diff.py`): `git diff -U0 BASE -- src/` hat 145 entfernte Zeilen; 98 Textbruchstücke aus entfernten String-Literalen (f-Strings an `{...}` geteilt) geprüft, 0 fehlen im aktuellen src/ (jeder entfernte deutsche Text steht wortgleich als Konstante oder Schablone wieder da).
- Bestehende Soll-Texte (test_setup_check, test_playtime_api, test_orphans, test_service_lifecycle, test_provisioner_errors) laufen unverändert grün.

## Für 06-22/06-23

**Katalog-API** (`from gameworld.i18n import translate, normalize_language, ...`):

- `translate(text, language) -> str`: "de" oder Text über 2000 Zeichen: unverändert (bei "de" dasselbe Objekt); sonst exakter Eintrag aus `MESSAGES`, dann die erste passende Schablone aus `TEMPLATES` (verankert, Platzhalter als nicht gierige Gruppe, wiederholter Platzhalter als Rückverweis), Werte unverändert eingesetzt; nichts gefunden: Text unverändert. Unbekannte Sprache wird wie en behandelt.
- `translate_optional(text | None, language)`, `normalize_language(raw)` (wie das Frontend), `placeholders(template)`.
- Sprache des Kontos: in Routen `language: LangDep` (aus `gameworld.api.language`); in Routen ohne Router-Sperre (me.py) erst nach der eigenen Selbstauskunft `await roles.language(uid)` aufrufen, damit eine Störung nie eine zweite Nextcloud-Abfrage auslöst. Außerhalb von Requests (Benachrichtigungen, 06-23): `await get_role_service().language(uid)`, wirft nie, Rückfall en.
- Neue Texte: Konstante (MSG_/TEXT_) im Quellmodul, Eintrag in catalog_en.py und catalog_fr.py mit der importierten Konstante als Schlüssel. Werte nie übersetzen, nur einsetzen; ist ein eingesetzter Wert selbst deutsch, einen vollständigen Eintrag bauen (Vorbild: unbekannte Spielart am Ende der Kataloge).
- Prüfungen, die neue Texte automatisch erfassen: `test_every_server_constant_has_en_and_fr` (Modulliste und EXTRA_TEXTS in tests/test_i18n.py), `test_every_raise_literal_is_translated_or_internal` (raise und HTTPException in api/, access/, backup/, talk/, playtime/, worlds/, provisioner/client.py, presets.py, archive.py), Platzhalter- und Rundlauftest, französische Typografie. 06-22 nimmt provisioner/access_mod.py und time_mod.py, 06-23 notify/texts.py neu in `_CONSTANT_FILES` auf.
- Ausnahmen nur in tests/i18n_exceptions.tsv: Kopf `file<TAB>line<TAB>reason`, Pfad relativ zum Repo, Grund beginnt mit `intern: `; veraltete Zeilen oder Zeilen für übersetzte Literale lassen den Test scheitern. Zeilennummern verschieben sich bei Änderungen oberhalb, dann die Zeile nachziehen.
- Werkzeug-Falle (wie 06-17): Write/Edit und Bash-Heredocs wandeln `\u00a0`/`\u2019` in echte Zeichen; danach mit einem Skript (chr(92) + "u00a0") zurückschreiben und `grep -c $'\xc2\xa0'` prüfen.

## Deviations from Plan

### Auto-fixed Issues / Anpassungen

**1. [Rule 3 - Blocking] Exakte /api/me-Erwartungen um language ergänzt**
- **Found during:** Task 1
- **Issue:** Drei bestehende Tests vergleichen die /api/me-Antwort als ganzes dict (test_roles.py zweimal, test_verwalter_groups.py einmal); das neue Pflichtfeld language aus dem Plan bricht sie zwangsläufig.
- **Fix:** Je Erwartung die Zeile `"language": "de",` ergänzt; keine Zeichenfolge geändert. Commit a6d05c1.

**2. [Rule 1 - Planwiderspruch] 503 für ein nie gesehenes Konto ist englisch**
- **Found during:** Task 1
- **Issue:** Der Plan verlangt "bei einem nie gesehenen Konto englisch"; test_roles.py::test_lookup_error_gives_503_and_is_not_cached prüfte für genau diesen Fall den deutschen Text.
- **Fix:** Planverhalten umgesetzt (Kontosprache unbekannt, Rückfall en wie im Frontend); die Prüfung erwartet jetzt den englischen Text, mit Kommentar. Für deutsche Konten bleibt alles zeichengleich (eigener Test test_outage_after_success_keeps_german). Commit a6d05c1.

**3. [Rule 2 - Correctness] Keine zweite Nextcloud-Abfrage nach einer Störung**
- RoleService merkt sich den Zeitpunkt einer gescheiterten Selbstauskunft; language() fragt dann 30 s lang nicht neu, sondern nimmt den zuletzt bekannten Wert oder en. Sonst hätte der Fehler-Handler jede 503 mit einem zweiten Nextcloud-Aufruf beantwortet (bestehende Aufrufzählungen in test_roles, test_my_worlds, test_my_playtime, test_verwalter_groups belegen das). nc_admin merkt sich die Sprache, nie das Profil (T-06-75). Commit a6d05c1.

**4. [Rule 2 - Vollständigkeit] Zusätzlich übersetzt: CSRF-Ablehnung, Konfigurationsfehler, gespeicherte Texte**
- csrf.py (Middleware-Antwort ohne HTTPException), config.py (Portbereich, Speicherpfad: landen im Setup-Check-Befund "config" und in 503), alle gespeicherten Texte aus worlds/service.py und backup/service.py (EXTRA_TEXTS im Test), PortInUseError, Status-Datei-Fehler. Nicht in der Dateiliste des Plans, aber nutzersichtbar. Commits 1740860, 6dff83e.

**5. [Rule 1 - Planannahme] Ungültige Container-ID erreicht die API nie als 409**
- Das Eingabemodell OrphanContainerIn prüft dasselbe Muster wie der Provisioner; eine ungültige ID ergibt schon 422 mit pydantics englischer Meldung. Der Routentest Orphan-409 nutzt darum den eigenen Container und das eigene Volume (OrphanRefusedError, MSG_ORPHAN_REFUSED); MSG_ORPHAN_BAD_ID und die beiden anderen Provisioner-Texte prüft test_orphan_refused_texts_are_translated direkt. api/admin.py blieb unverändert.

**6. [Prozess] RED-Commit von Task 3 ohne pyright-Lauf**
- 4c8ae07 enthält nur Tests, die auf noch nicht vorhandene Konstanten zugreifen; ruff lief, pyright nicht (es hätte die fehlenden Attribute gemeldet). Der GREEN-Commit 6dff83e lief durch alle Gates. Tasks 1 und 2 wurden nicht als getrennte RED/GREEN-Commits geführt (Tests und Umsetzung im selben Commit).

**7. Kleinigkeiten:** Die Logzeile "ist größer als ... gekappt" in client.py nennt jetzt den Dateipfad statt der deutschen Bezeichnung (der Parameter label wurde durch die fertige Meldung `unreadable` ersetzt; Tests prüfen nur "gekappt"). In playtime/plan.py liegt MSG_HOLIDAY_ENDS_BEFORE_START, api/playtime.py importiert sie (ein Text, eine Konstante).

## TDD Gate Compliance

- Task 3: RED 4c8ae07 (test), GREEN 6dff83e (feat) in dieser Reihenfolge. Tasks 1 und 2: kombinierte feat-Commits mit Tests (siehe Abweichung 6).

## Known Stubs

Keine. Spieltexte der Mods (06-22), Benachrichtigungen und Bot-Texte (06-23) sind laut Plan nicht Teil dieses Plans.

## Threat Flags

Keine neue Angriffsfläche. Umsetzung der Bedrohungen:

| Threat | Umsetzung |
|--------|-----------|
| T-06-75 | language reist nur mit der Selbstauskunft; role_of, verwalter_groups, nc_admin und CACHE_SECONDS unverändert; nc_admin füllt den Rollen-Cache nicht (Test test_nc_admin_check_remembers_the_language_without_caching_the_role); gesamte Rollen-Testsuite grün |
| T-06-76 | kein zusätzlicher Nextcloud-Aufruf: Wert aus dem 30-s-Profil-Cache, nach Störung zuletzt bekannter Wert oder en ohne neue Abfrage (Test test_outage_for_an_unseen_account_is_english_without_extra_lookup zählt die Aufrufe), ohne Konto sofort en |
| T-06-77 | Schablonen einmal kompiliert (functools.cache), verankert (fullmatch), nicht gierige Gruppen; Texte über 2000 Zeichen ohne Katalog- und Regex-Lauf (Tests mit 5000 Zeichen und 3000-stelligem Wert) |
| T-06-78 | translate ersetzt nur den deutschen Rahmen, eingesetzte Werte bleiben exakt die bisher ausgelieferten; Status-Code und Header (WWW-Authenticate) bleiben gleich (Test test_status_and_headers_survive_translation) |
| T-06-109 | AST-Abdeckungstest über raise und HTTPException(detail) mit Positivkontrolle; Ausnahmen nur in tests/i18n_exceptions.tsv mit Datei, Zeile, Grund "intern: ...", Abgleich in beide Richtungen (veraltete Zeile, leerer Grund, Zeile für übersetztes Literal scheitern) |

## Self-Check: PASSED

- Dateien vorhanden: src/gameworld/i18n/__init__.py, catalog_en.py, catalog_fr.py, src/gameworld/api/language.py, tests/test_i18n.py, tests/test_api_language.py (über 120 Zeilen), tests/i18n_exceptions.tsv
- Commits vorhanden: a6d05c1, 1740860, 4c8ae07, 6dff83e
