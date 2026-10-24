---
phase: 06-store-release
plan: 04
subsystem: playtime
tags: [playtime, adult-flag, security, negative-tests]
requires: ["06-01", "06-02"]
provides:
  - "WorldStore.set_adult, clear_adult, adults (Tabelle adults aus Schema 8, set_by/set_at)"
  - "TimeEngine: Frei-Menge = time_admins | adults in render und book, Frei-Menge im Cache-Schlüssel"
  - "TimeService.set_adult(acting_uid, nc_user, adult=...) -> applied; MSG_ADULT_IS_VERWALTER"
  - "POST /api/players/adult im require_verwalter-Router"
  - "PlayerOut.adult/verwalter/has_rules, ChildOut.adult, /api/my/playtime unbegrenzt für Erwachsene"
  - "collect_play (Tagesrückblick) ohne Erwachsene"
affects: [06-05, 06-12]
tech-stack:
  added: []
  patterns:
    - "Erwachsen wirkt nur über die vorhandene frei-Zeile des Zeit-Mods; Mod unverändert"
    - "Schalten unter mutation(), push_time je Welt des Kontos, Ergebnis applied (Muster _set_sync)"
    - "Negativtest mit rohem iterdump-Vergleich der ganzen DB plus Positivkontrolle im selben Test"
key_files:
  created:
    - tests/test_adult_flag.py
  modified:
    - src/gameworld/worlds/store.py
    - src/gameworld/playtime/engine.py
    - src/gameworld/playtime/service.py
    - src/gameworld/notify/loop.py
    - src/gameworld/api/invites.py
    - src/gameworld/api/playtime.py
    - tests/test_playtime_engine.py
    - tests/test_forget_account.py
    - tests/test_invites_api.py
decisions:
  - "Ein Konto mit adults-Zeile, das später Verwalter wird, verhält sich in book wie ein Verwalter (usage ja, play nein); Erwachsene ohne Verwaltung werden gar nicht verbucht"
  - "409 MSG_ADULT_IS_VERWALTER nur beim Einschalten; Ausschalten (adult false) ist immer erlaubt, auch für ein inzwischen verwaltendes Konto (räumt eine alte Markierung weg, ohne Rechte-Wirkung)"
  - "set_adult ruft vorher refresh_admins(force=True) außerhalb der Sperre, damit die Verwalter-Prüfung auf frischem Stand läuft"
  - "TimeService-Dependency in api/invites.py lokal gebaut (api.playtime importiert api.invites, Rückimport wäre zirkulär)"
metrics:
  duration: "ca. 21 min"
  completed: 2026-10-24
  tasks: 2
  files: 10
---

# Phase 6 Plan 04: Erwachsen-Schalter Backend (ROLLE-04) Summary

Erwachsen-Flag je Konto mit sofortiger Wirkung über die frei-Zeile des Zeit-Mods (frei = Verwalter-Vereinigung | adults), keine Verbuchung und kein Tagesrückblick für Erwachsene, Setzen nur per POST /api/players/adult im Verwalter-Router, Welt-Konfiguration nachweislich byte-identisch.

## Tasks

| Task | Name | Commits |
|------|------|---------|
| 1 | Store-Methoden und Engine-Schnitt frei = Verwalter \| Erwachsene | fd71bb4 (test), c4c2e88 (feat) |
| 2 | TimeService.set_adult, Route, erweiterte Ausgaben, Negativtests | e1faa24 (test), ec90fe1 (feat) |

## Was gebaut wurde

- Store: `set_adult` (INSERT OR REPLACE mit set_by/set_at), `clear_adult` (kein Fehler ohne Zeile), `adults()`. `forget_account` entfernt die Zeile über ACCOUNT_TABLES (eigener Test über die Store-API).
- Engine: `_frei()` = `parse_admins(time_admins) | adults`; render schreibt für jedes eingeladene Konto darin `-1 -1 -1 frei -`; book überspringt Erwachsene für usage und play (Stand wird trotzdem verankert, kein Nachverbuchen nach dem Zurückschalten). Die sortierte Frei-Menge ist Teil des Cache-Schlüssels (T-06-18).
- Service: `TimeService.set_adult` mit Worker `_adult_sync` unter `mutation()`: Spieler muss existieren (404), Verwalter beim Einschalten 409, dann set/clear und `push_time` je Welt aus `player_worlds`, Rückgabe `all(...)`. `ChildView.adult`, `_my_playtime_sync` behandelt Erwachsene als unbegrenzt. `set_child` bleibt für Erwachsene erlaubt (Plan ruht).
- API: `AdultIn(PlayerRef)` mit `adult: bool` (extra forbid), `AdultOut`, Route `POST /api/players/adult`. `PlayerOut` um `adult`, `verwalter`, `has_rules`; `ChildOut.adult`.
- Rückblick: `collect_play` schließt Erwachsene aus, auch mit Minuten von vor dem Umschalten am selben Tag.

## Tests und Gates

- `tests/test_adult_flag.py` (17 Tests): Store, Rückblick, Route positiv (beide Welten gepusht, frei-Zeile in beiden Regeldateien), Zurückschalten, 409, 404, 422 (Zusatzfeld, fehlendes Feld), Kind-Negativtest (sich selbst und anderes Kind) mit `iterdump`-Vergleich der ganzen DB, ohne push_time, plus Positivkontrolle; POST auf /api/my/adult, /api/my/players/adult, /api/my/playtime -> 404/405 ohne DB-Änderung; Strukturtest über OpenAPI (unter /api/my nur play-ticket schreibend, kein adult-Pfad); Spielerliste und Spielzeit-Liste; Byte-Vergleich minetest.conf, world.mt, Zugangsdatei, build_world_files und world_spec vor/nach dem Einschalten, in der Regeldatei ändern sich nur Kopf, Kind-Zeile (-> Literal `Kind -1 -1 -1 frei -`), dessen @start und @tage.
- Spy auf `push_time` prüft bei jedem Aufruf, dass die Welt-Sperre `_LOCK` gehalten ist.
- `tests/test_playtime_engine.py`: frei-Zeile, "Umschalten ändert die Bytes der Regeldatei" (beide Richtungen), Frei-Menge im Cache-Schlüssel (neue Generation ohne sichtbare Zeile), book ohne usage/play für Erwachsene mit Kind als Positivkontrolle.
- Unabhängige Gegenprobe (Mutation): routerweite Sperre und VerwalterDep der Route temporär entfernt -> Kind-Negativtests schlagen fehl (200 bzw. 404 statt 403); Datei danach aus Sicherung wiederhergestellt. Nur die routerweite Sperre zu entfernen reicht nicht, die Route ist doppelt gesichert.
- Gates: ruff check, ruff format, pyright basic (latest) 0 Fehler, vulture ohne Befund.
- `uv run pytest -m "not docker" -q`: 2414 passed, 44 deselected.
- `git diff -- src/gameworld/provisioner/` leer (Mod und Konfig-Erzeuger unverändert); `grep adult` in api/me.py und access/roles.py ohne Treffer.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Fehlende Funktion] Erwachsene aus dem Tagesrückblick (collect_play)**
- **Found during:** Task 1
- **Issue:** book verbucht Erwachsene ab dem Umschalten nicht mehr, aber play_daily-Zeilen von vor dem Umschalten am selben Tag wären im Rückblick erschienen (CONTEXT: Erwachsene nie im Tagesrückblick).
- **Fix:** `collect_play` schließt `store.adults()` aus; Test `test_adult_never_in_daily_review_even_with_minutes_before_switch`.
- **Files modified:** src/gameworld/notify/loop.py (nicht in files_modified des Plans)
- **Commit:** c4c2e88

**2. [Rule 3 - Blockierend] Zirkulärer Import für TimeDep**
- **Issue:** api/playtime.py importiert aus api/invites.py; TimeDep von dort zu holen wäre zirkulär.
- **Fix:** eigene `get_time_service`-Dependency in api/invites.py (gleicher Aufbau). `_players` bekommt den Store über ServiceDep (AccessService hat keinen öffentlichen Store).
- **Commit:** ec90fe1

**3. [Rule 1 - Testanpassung] test_invites_api erwartete PlayerOut exakt**
- Neue Felder adult/verwalter/has_rules im Soll nachgezogen. Commit e1faa24.

**4. Plan-Detail: "Plan 0 Minuten heute"** lässt WeekPlan nicht zu (Limit 1..1440); Test nutzt "Tag nicht erlaubt" als gesperrte Kind-Zeile.

tests/conftest.py brauchte keine Ergänzung (vorhandene FakeDirectory/give_rules reichen).

## Threat Flags

Keine neue Angriffsfläche außerhalb des Threat-Registers: die einzige neue Route liegt im require_verwalter-Router (T-06-16), die Markierung wirkt nur in engine.render/book und collect_play (T-06-17), set_by/set_at werden gespeichert (T-06-19). T-06-20 (versehentliches Markieren) bleibt accept bis zum Bestätigungsdialog in 06-05.

## Known Stubs

Keine.

## Für 06-05

- `POST /api/players/adult` Body `{"nc_user": str, "adult": bool}` (keine Zusatzfelder, sonst 422) -> 200 `{"nc_user", "adult", "applied"}`. `applied` false: Welt ohne Container, Wirkung beim nächsten Start (UI zeigt NOT_APPLIED_TEXT).
  - 403 für Nicht-Verwalter ("Nur Eltern können Welten verwalten."), 404 unbekanntes Konto, 409 detail "Dieses Konto verwaltet Gameworld und spielt ohnehin ohne Regeln." (nur beim Einschalten). Eine Nextcloud-Störung beim Auffrischen der Verwalter-Gruppen lässt den letzten Stand stehen (kein Fehler, refresh_admins schluckt sie).
  - Ausschalten braucht im Backend keinen Dialog (D-07: Bestätigung nur beim Einschalten, Frontend).
- `GET /api/worlds/{id}/players` (und Antworten von invites/remove): je Spieler zusätzlich `adult: bool`, `verwalter: bool`, `has_rules: bool`.
- `GET /api/playtime` und Einzel-Antworten der Kind-Routen: je Kind zusätzlich `adult: bool` (Plan ruht, `has_rules` kann trotzdem true sein; UI-Text "Erwachsen: Regel ruht").
- `GET /api/my/playtime`: für Erwachsene `limited: false`.

## Self-Check: PASSED

- FOUND: tests/test_adult_flag.py, .planning/phases/06-store-release/06-04-SUMMARY.md
- FOUND commits: fd71bb4, c4c2e88, e1faa24, ec90fe1
