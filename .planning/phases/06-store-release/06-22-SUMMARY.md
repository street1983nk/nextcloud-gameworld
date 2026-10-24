---
phase: 06-store-release
plan: 22
subsystem: backend, provisioner, i18n
tags: [i18n, d-27, schema-9, luanti-mods, world-language]
requires: ["06-18"]
provides:
  - "Schema 9: worlds.language (NOT NULL DEFAULT 'de') und worlds.launched_language, WorldStore.set_world_language"
  - "access_mod/time_mod: ModTexts/TimeTexts, MOD_TEXTS[de|en|fr], mod_texts(language), mod_init_lua(language); MOD_INIT_LUA == mod_init_lua(\"de\")"
  - "kid_text(..., language=) und pause_text(..., language=) spiegeln die Lua-Sätze je Sprache"
  - "archive.world_mods(language), build_world_files(..., language=), build_world_payload(..., language=)"
  - "POST /api/worlds/{id}/language (Body {language: de|en|fr}), WorldOut.language und WorldOut.language_restart_needed"
  - "Neue Welt bekommt die Kontosprache des anlegenden Verwalters (LangDep, Rückfall en wie 06-18)"
affects: [06-23, 06-24, 06-27]
tech-stack:
  added: []
  patterns:
    - "Byte-Gleichheit je Sprache: Lua-Quelle als f-String in einer Funktion mod_init_lua(language), nur die {_lua_string(texts.x)}-Ausdrücke wechseln; Modulkonstante MOD_INIT_LUA = mod_init_lua(\"de\") hält alle Altaufrufer"
    - "Golden-SHA-256 der deutschen init.lua in tests/test_mod_texts.py, gemessen auf der Basis vor der Änderung"
    - "Sprachwert aus der Datenbank wählt nur einen festen Schlüssel (world_language(row) bzw. mod_texts()), landet nie selbst im Lua"
    - "Neustart-Hinweis aus Datenbank statt Docker: launched_language wird nach erfolgreichem start_world in _launch gesetzt; NULL (Start vor Schema 9) zählt als de"
    - "Französische Mod-Texte ohne ? ! ; : (kein NBSP nötig), Apostroph U+2019 als \\u2019-Escape im Quelltext (ruff RUF001)"
key_files:
  created:
    - tests/test_mod_texts.py
    - tests/test_world_language.py
  modified:
    - src/gameworld/provisioner/access_mod.py
    - src/gameworld/provisioner/time_mod.py
    - src/gameworld/provisioner/archive.py
    - src/gameworld/worlds/store.py
    - src/gameworld/worlds/service.py
    - src/gameworld/api/worlds.py
    - src/gameworld/i18n/catalog_en.py
    - src/gameworld/i18n/catalog_fr.py
    - tests/i18n_exceptions.tsv
    - tests/test_i18n.py
    - tests/test_service_lifecycle.py
    - tests/test_store.py
decisions:
  - "language_restart_needed = status running UND (launched_language oder 'de') != Weltsprache; Abweichung vom Planwortlaut 'launched_language gesetzt': sonst zeigte eine vor dem Update gestartete Welt nach dem Umstellen keinen Hinweis"
  - "Kein Neustart durch das Umschalten (T-06-88); Änderung nur im Store unter mutation(), kein Docker- oder Nextcloud-Aufruf"
  - "Mod-Texte laufen nicht über translate()/Kataloge: access_mod/time_mod bleiben aus _CONSTANT_FILES (anders als in 06-18 vorgemerkt); die Abdeckung prüft tests/test_mod_texts.py über MOD_TEXTS (alle Sprachen, Lua-Spiegel, Hygiene)"
  - "en: Kurzpause \"Short break! ...\" (wie de mit Ausrufezeichen), Schluss \"That is it for today.\"; fr: \"Petite pause.\" ohne Ausrufezeichen (sonst NBSP im Luanti-Text nötig)"
  - "fr geschlechtsneutral: \"Tu n’as pas d’invitation pour ce monde.\" statt \"invité(e)\""
  - "Einziger neuer Servertext: MSG_WORLD_LANGUAGE_UNSUPPORTED (nur außerhalb der API erreichbar, die Route nimmt nur das Literal), mit en/fr-Katalogeintrag"
metrics:
  duration: "30 min"
  completed: "2026-10-24"
  tasks: 2
  files: 14
---

# Phase 6 Plan 22: Weltsprache (Schema 9) und Mod-Texte in de/en/fr Summary

Jede Welt hat eine Spielsprache (Schema 9, Standard = Kontosprache des anlegenden Verwalters, Bestand de); beide Welt-Mods rendern ihre Kindertexte in dieser Sprache bei Zeichen für Zeichen gleichem Lua-Code, deutsche Welten belegt byte-gleich per Golden-SHA-256.

**Basis-ID:** 83c07300219aea42603e48777cf1c0bc2347631a (`$TEMP/gw-base-06-22`)

## Golden-Hash-Messung (vor der Änderung, auf 83c0730)

| Mod | SHA-256 von MOD_INIT_LUA (de) |
|-----|-------------------------------|
| gameworld_access | fc1e5327a9efc09f576a9acf7579a46b5b51f0822bc98aed86e03f55a5ae9c01 |
| gameworld_time | 5039a65470185799667ff9e3190048bd3bcbbb7fb73455221bba7f89ece259ad |

Nach beiden Commits erneut gemessen: `mod_init_lua("de")` und `MOD_INIT_LUA` liefern exakt diese Werte (test_golden_hash_german_access_mod, test_golden_hash_german_time_mod; Positivkontrolle: en/fr ergeben andere Hashes). `git diff --quiet 83c0730 -- tests/test_time_mod.py tests/test_access_mod.py tests/test_archive.py` exit 0.

## Tasks

| Task | Name | Commits | Files |
|------|------|---------|-------|
| 1 | Mod-Texte je Sprache bei unverändertem Lua-Code | 7c04ac5 (RED), 97eb215 (GREEN) | access_mod.py, time_mod.py, archive.py, tests/test_mod_texts.py, i18n_exceptions.tsv, test_i18n.py (Kommentar) |
| 2 | Schema 9, Weltsprache in Store, Dienst und API | 904b830 | store.py, service.py, api/worlds.py, catalog_en/fr.py, tests/test_world_language.py, test_store.py, test_service_lifecycle.py, i18n_exceptions.tsv |

Zwischen 97eb215 und 904b830 liegt der fremde Commit 57fa02b (docs(06), 06-24-PLAN.md, nicht aus diesem Plan).

## Satzbausteine (feste Reihenfolge Grundsatz + " " + Tagesangabe [+ CLOCK_FROM + Uhrzeit] + Schluss)

| Baustein | de | en | fr |
|----------|----|----|----|
| DAY_TODAY / TOMORROW | Heute / Morgen | Today / Tomorrow | Aujourd’hui / Demain |
| DAY_ON / DAY_NEXT | "Am " / "Nächsten " | "On " / "Next " | "Ce " / "La semaine prochaine, " |
| CLOCK_FROM / CLOCK_UNIT | " ab " / " Uhr" | " from " / ":00" | " à partir de " / " h" |
| PLAY / PLAY_AGAIN / OPEN_AGAIN | " kannst du (wieder) spielen." / " ist sie wieder offen." | " you can play (again)." / " it will be open again." | ", tu peux jouer." / ", tu pourras rejouer." / ", il sera de nouveau ouvert." |

Beispiele: "It is not playtime yet. Today from 15:00 you can play.", "Aujourd’hui, ce n’est pas un jour de jeu. Ce mercredi à partir de 9 h, tu pourras rejouer.", "C’est fini pour aujourd’hui. Demain à partir de 9 h, tu pourras rejouer." Uhrzeit ohne volle Stunde in allen Sprachen "9:30" (Lua string.format bleibt gleich). Nie "0 Uhr", "midnight", "minuit", kein Datum (Test über alle Gründe, Tage 0..7 und Grenzminuten).

## Für 06-23/06-24

**Weltsprache-API (Backend fertig, UI in 06-24 Bereich world):**
- `POST /api/worlds/{id}/language` mit `{"language": "de"|"en"|"fr"}` (extra="forbid"); 200 mit WorldOut, 422 bei anderem Wert oder Zusatzfeld, 403 für Spieler (routerweites require_verwalter), 404 unbekannte Welt (Text in Kontosprache). Kein PUT (AppAPI), kein Neustart.
- `WorldOut.language` (immer de/en/fr; ein Datenbankwert außerhalb ergibt "de") und `WorldOut.language_restart_needed` (nur bei status running: die laufenden Mods sprechen eine andere Sprache; Welt vor Schema 9 gestartet zählt als de). Nach Start/Neustart über die bestehenden Routen wird der Hinweis false. UI-Vorschlag: Hinweis wie access_restart_needed mit Neustart-Knopf, Kinder werden erst beim Neustart getrennt.
- POST /api/worlds (Body unverändert) setzt die Sprache aus der Kontosprache des Verwalters (LangDep); ein unbekanntes Konto ergibt en wie in 06-18.
- Dienst: `WorldService.create_world(name, preset_id, language="de")`, `await WorldService.set_world_language(world_id, language)` (ValueError MSG_WORLD_LANGUAGE_UNSUPPORTED, WorldNotFoundError), Hilfsfunktion `gameworld.worlds.service.world_language(row)`.

**Textbausteine für 06-23 (Benachrichtigungen, Bot):**
- Kindertexte je Weltsprache: `time_mod.kid_text(reason, days_ahead, weekday, minute, reached=..., language=row_language)`, `time_mod.pause_text(art, minute, language=...)`, Bündel `time_mod.MOD_TEXTS[lang]` / `access_mod.MOD_TEXTS[lang]` bzw. `mod_texts(lang)` mit Rückfall de. Bot-Texte, die Kindertexte zitieren, sollten dieselbe Weltsprache nehmen (`world_language(row)`), Eltern-Texte die Kontosprache.
- Neue Mod-Texte: Feld im NamedTuple ergänzen, alle drei Sprachen füllen, Lua-Literal per `{_lua_string(t.feld)}`; der Golden-Hash muss für de gleich bleiben (sonst bewusst neu messen und begründen).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] language_restart_needed für Welten, die vor Schema 9 gestartet sind**
- **Found during:** Task 2
- **Issue:** Planwortlaut "launched_language gesetzt und ungleich language" hätte für eine vor dem Update gestartete Welt (launched_language NULL, laufende Mods deutsch) nach dem Umstellen auf en keinen Neustart-Hinweis gezeigt.
- **Fix:** NULL zählt als de (LEGACY_LAUNCH_LANGUAGE); Test test_world_running_before_schema_9_counts_as_german.
- **Commit:** 904b830

**2. [Rule 3 - Blocking] Verschobene Zeilen in tests/i18n_exceptions.tsv**
- archive.py 183 -> 194 (97eb215), store.py 480 -> 500 und 1304 -> 1324 (904b830); nur Zeilennummern, Gründe unverändert (wie in 06-18 vorgesehen).

**3. [Rule 3 - Blocking] Test-Fakes ohne Schlüsselwort-Parameter**
- tests/test_service_lifecycle.py: `payload_args.wrapper` und `_no_space` nahmen nur `*args`; der Dienst übergibt jetzt `language=`. Beide nehmen und reichen `**kwargs` durch, keine Soll-Texte oder Erwartungen geändert (904b830).

**4. [Rule 3 - Blocking] Schema-Versions-Pins in tests/test_store.py**
- test_fresh_db_is_schema_8_with_role_tables prüfte `SCHEMA_VERSION == "8"` und drei Mal `_schema_version(db) == "8"`; jetzt `"9"` bzw. `== SCHEMA_VERSION` (Migration auf den neuesten Stand), Rollentabellen-Prüfungen unverändert (904b830).

**5. [Abweichung von 06-18-Vormerkung] access_mod/time_mod nicht in _CONSTANT_FILES**
- 06-18 hatte vorgemerkt, beide Module in den Katalog-Abdeckungstest aufzunehmen. Die Mod-Texte gehen aber nie durch translate(), sondern über MOD_TEXTS direkt in die init.lua; Katalogeinträge wären tote Doppelungen (und test_catalog_keys_are_german_sources verlangt keine verwaisten Schlüssel). Abdeckung, Lua-Spiegel, Typografie und Hygiene prüft tests/test_mod_texts.py; der Kommentar in tests/test_i18n.py sagt das jetzt (97eb215).

**6. [Prozess] RED-Commit 7c04ac5 ohne pyright-Lauf** (Tests greifen auf noch fehlende Attribute zu, wie 06-18); GREEN-Commits liefen durch alle Gates. Task 2 ohne getrennten RED-Commit (Tests und Umsetzung in 904b830, Gegenprobe per Mutation: Hinweis-Logik und Sprachübergabe in _launch einzeln ausgeschaltet ergaben 2 bzw. 4 rote Tests).

**Docker-e2e:** Der Plan sieht keinen e2e-Beleg vor; keiner gelaufen (freier RAM 2,3 bis 2,6 GB). Der englische Kick-Text ist über Tar-Inhalt (Fake-Provisioner) und Lua-Literaltests belegt; ein Lauf im echten Luanti steht für die Abnahme (06-27) an.

## Gate-Ergebnisse

- `uv run ruff check`: All checks passed; `uv run ruff format --check`: 204 files already formatted
- `PYRIGHT_PYTHON_FORCE_VERSION=latest uv run pyright`: 0 errors, 0 warnings
- `uv run vulture`: ohne Befund
- `uv run pytest -m "not docker" -q`: 2766 passed, 44 deselected (seriell, 6:31 min)
- Task-1-Verify: test_mod_texts, test_time_mod, test_access_mod, test_archive, test_i18n: 327 passed

## Threat Flags

Keine neue Oberfläche außerhalb des Threat-Modells: die neue Route liegt unter dem bestehenden Router mit require_verwalter (T-06-86), der Sprachwert ist Literal (T-06-85), keine Datei- oder Netzpfade neu. Die Backup-Härtung (keine Lua aus Archiven, RESTORE_DROP_DIRS worldmods/mods/game) ist unberührt; nach einem Restore schreibt _launch die Mods in der Weltsprache neu.

## Known Stubs

Keine. Die Bedienoberfläche für die Weltsprache ist bewusst 06-24 (Bereich world).

## Self-Check: PASSED

- FOUND: tests/test_mod_texts.py, tests/test_world_language.py, .planning/phases/06-store-release/06-22-SUMMARY.md
- FOUND: 7c04ac5, 97eb215, 904b830
