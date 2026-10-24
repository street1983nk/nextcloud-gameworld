---
phase: 06-store-release
plan: 23
subsystem: notify, talk
tags: [i18n, d-25, d-27, notifications, talk-bot, daily-summary]
requires:
  - 06-18 (RoleService.language, gameworld.i18n.translate)
  - 06-22 (WorldRow.language, world_language)
provides:
  - NOTIFY_TEXTS / BOT_TEXTS je Sprache (de, en, fr) in notify/texts.py
  - Glocke in der Kontosprache jedes Empfängers, Talk-Bot in der Weltsprache
  - englische Talk-Bot-Beschreibung
affects:
  - notify/loop.py (_deliver nimmt eine Bau-Funktion), backup/service.py (_finish_failed)
tech-stack:
  added: []
  patterns:
    - "TextBuilder = Callable[[str], NotifyText]: Text wird je Empfänger mit dessen Sprache gebaut"
    - "NamedTuple-Bündel je Sprache, deutsche Konstanten bleiben Quelle (wie MOD_TEXTS aus 06-22)"
key_files:
  created:
    - tests/test_notify_language.py
  modified:
    - src/gameworld/notify/texts.py
    - src/gameworld/notify/review.py
    - src/gameworld/notify/loop.py
    - src/gameworld/backup/service.py
    - src/gameworld/talk/bot.py
decisions:
  - "Notify-Rückfall en (Kontosprache außerhalb de/en/fr), Bot-Rückfall de (Weltzeile, Bestandswelten deutsch)"
  - "FAILED_SUBJECTS entfällt, failed_subject(kind, language) in texts.py; kind ungleich restore ergibt wie bisher den Sicherungs-Betreff"
  - "Englischer Bot-Schluss-Text: Playtime is over for today. (statt That's it, kein ASCII-Apostroph)"
metrics:
  duration: ~45 min
  completed: 2026-10-24
  tasks: 2
  files: 6
---

# Phase 6 Plan 23: Benachrichtigungen je Empfängersprache, Talk-Bot je Weltsprache Summary

Glocken-Benachrichtigungen (Beitrittsversuch, Sammelnachricht, Tagesrückblick, Sicherung/Wiederherstellen fehlgeschlagen) werden je Empfänger in dessen Nextcloud-Kontosprache gebaut (RoleService.language, Rückfall en), Talk-Bot-Nachrichten folgen der Weltsprache (world_language, Rückfall de); deutsche Texte byte-gleich, Bot-Beschreibung englisch.

Basis-Commit: d13e4305d184925d50ff678381c2b31569f81534

## Commits

| Task | Commit | Inhalt |
|------|--------|--------|
| 1 RED | effb19d | test: Texttabellen, Zeichen-/Platzhalterregeln, FR-Typografie, Bot-Beschreibung mit Positivkontrolle |
| 1 GREEN | 23e7e6f | feat: NOTIFY_TEXTS/BOT_TEXTS, language-Parameter, review_line je Sprache, failed_subject, bot_text, BOT_DESCRIPTION |
| 2 RED | 214a556 | test: Versand je Empfängersprache, Bot je Weltsprache, Sicherungsfehler fr |
| 2 GREEN | 5e10e78 | feat: _deliver mit Bau-Funktion, Bot-Handler mit Weltsprache, _finish_failed mit translate |

## Was gebaut wurde

- **texts.py:** `NotifyStrings`/`BotStrings` (NamedTuples), `NOTIFY_TEXTS`, `BOT_TEXTS`, `notify_strings(language)`, `failed_subject(kind, language)`, `bot_text(key, language, **values)`. Alle Bau-Funktionen haben `language: str = "de"` als Schlüsselwort; ohne Angabe exakt wie vorher. Deutsche Konstanten (ATTEMPT_SUBJECT, BOT_JOIN usw.) unverändert, sie bilden den de-Eintrag.
- **Übersetzungen** nach Begriffstabelle 06-17: "join attempts", "Daily summary", "Backup/Restore of {world} failed"; fr "tentatives de connexion", "Récap du jour", "Échec de la sauvegarde/restauration de {world}". FR mit echten Akzenten, ` ` vor ":" und `’` als Escape im Quelltext (Test prüft das).
- **review.py:** `review_line(entries, language=...)`: de "Min." und " (Limit erreicht)", en/fr "min" und " (limit reached)"/" (limite atteinte)".
- **loop.py:** `_deliver(context, uids, build, page, params)` fragt je uid `get_role_service().language(uid)` und baut den Text; Drosselung, Reihenfolge und claim-Logik unverändert. `_room_token`/`_bot_room` liefern (Token, Weltsprache); `_fixed(key)`, `_presence(key)`, `handle_warn10`, `handle_pause_start` nutzen `bot_text`. bot_name/md_escape laufen weiterhin vor dem Einsetzen.
- **backup/service.py:** `_finish_failed` holt die Sprache des auslösenden Verwalters, Betreff via `failed_subject`, Grund via `translate(message, language)` (unbekannte Docker-Anteile bleiben, clean_value und Kappung unverändert).
- **talk/bot.py:** `BOT_DESCRIPTION = "Reports events from Gameworld worlds"`; Route, Name "Gameworld", BOT_URL_SUFFIX unverändert. Die neue Beschreibung erscheint in Talk erst nach dem nächsten Aktivieren der App (Registrierung in lifecycle.py beim Aktivieren).

## Gate-Ergebnisse

- ruff check, ruff format --check, pyright latest (0 errors), vulture: ohne Befund vor jedem Commit
- `uv run pytest -m "not docker" -q`: 2801 passed, 44 deselected (seriell, 2,2 GB frei)
- tests/test_notify_language.py: 35 Tests; RED-Nachweis Task 2: gegen die alte loop.py/backup/service.py schlagen 10 Tests fehl (de- und xx-Fälle bleiben grün, wie erwartet)
- Bestehende Tests unverändert gegen Basis: test_notify_texts.py, test_notify_review.py, test_talk_bot.py, test_notify_loop.py, test_bot_events.py, test_backup_service.py, conftest.py (`git diff --quiet <basis>`); keine Fake-Anpassung nötig, da `_deliver` nur intern aufgerufen wird
- `grep -c "Meldet Ereignisse" src/gameworld/talk/bot.py` = 0

## Deviations from Plan

### Auto-fixed Issues

None im Sinne von Rule 1-3. Kleine Präzisierungen:

1. **Englischer Schluss-Text** "Playtime is over for today." statt eines Satzes mit ASCII-Apostroph (Typografie-Konsistenz).
2. **FAILED_SUBJECTS entfernt** (keine Tests oder Aufrufer außer _finish_failed), ersetzt durch `failed_subject(kind, language)`; Verhalten für unbekannte kinds gleich (Sicherungs-Betreff).
3. **Bot-Textregel** (Zeichen < U+2000) für FR um den typografischen Apostroph U+2019 erweitert (in test_notify_language.py, nicht in test_bot_events.py, die nur die deutschen BOT_-Konstanten prüft).

## Threat Flags

Keine neue Angriffsfläche: Die Sprachabfrage nutzt die bestehende Selbstauskunft (RoleService, 30-s-Cache), keine neue Berechtigung, Empfänger weiterhin nur aus dem Verwalter-Schnappschuss (CR-01). T-06-89 (Zeichentest alle Sprachen), T-06-90 (Logtest ohne UID/Text bei Sprachausfall) und T-06-91 (@all je Sprache, FR-Welt im Loop) sind durch Tests abgedeckt.

## Known Stubs

Keine.

## TDD Gate Compliance

test-Commit vor feat-Commit je Task vorhanden (effb19d -> 23e7e6f, 214a556 -> 5e10e78). Hinweis Task 1: Implementierung entstand vor dem Test-Commit im Arbeitsbaum; der Test-Commit allein auf der Basis wäre rot (Importe NOTIFY_TEXTS, bot_text fehlen). Task 2 RED wurde explizit gegen die alte Implementierung nachgewiesen.

## Self-Check: PASSED

- Dateien vorhanden: tests/test_notify_language.py, src/gameworld/notify/texts.py, review.py, loop.py, backup/service.py, talk/bot.py
- Commits vorhanden: effb19d, 23e7e6f, 214a556, 5e10e78
