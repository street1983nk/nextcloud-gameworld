---
phase: 06-store-release
plan: 01
subsystem: roles
tags: [roles, security, schema-8, snapshot, negative-tests]
requires: []
provides:
  - "Schema 8: adults, verwalter_seen, verwalter_snapshot (ROLE_TABLES), talk_rooms.orphaned_token/former_owner"
  - "roles.py: META_VERWALTER_GROUPS, parse_verwalter_groups, role_of(profile, verwalter_groups), Profile.subadmin, RoleService(lookup, groups), RoleService.verwalter_groups/invalidate/nc_admin, require_nc_admin, NcAdminDep, MSG_NC_ADMIN_ONLY"
  - "store.py: group_snapshot, replace_group_snapshot, drop_group_snapshots, sync_verwalter_seen, verwalter_seniority"
  - "playtime/service.py: META_NC_ADMINS, Verwalter-Stand je Gruppe in refresh_admins/verify_admins"
  - "notify/loop.py: MaintenanceStep (hook, needs_nc_admin), purge nur als bestätigter NC-Admin"
affects: [06-02, 06-03, 06-04, 06-05, 06-06]
tech-stack:
  added: []
  patterns:
    - "Stand je Gruppe mit Fail-safe-Leerregel (Antwort ersetzt, ohne Antwort bleibt der Stand minus abgelehnte Mitglieder)"
    - "Admin-Schritte der Wartung tragen ein Flag und bekommen ihr handelndes Konto aus meta nc_admins"
key-files:
  created:
    - tests/test_verwalter_groups.py
  modified:
    - src/gameworld/worlds/store.py
    - src/gameworld/access/roles.py
    - src/gameworld/playtime/service.py
    - src/gameworld/notify/loop.py
    - tests/conftest.py
    - tests/test_store.py
    - tests/test_forget_account.py
    - tests/test_admin_snapshot.py
    - tests/test_notify_loop.py
decisions:
  - "Gruppenquelle des RoleService liest meta verwalter_groups über get_service().store im Worker-Thread (später Import wegen Zyklus api.worlds -> roles); jede Ausnahme = nur admin"
  - "require_nc_admin fragt über RoleService.nc_admin bei jedem Aufruf frisch (kein Cache), 403 MSG_NC_ADMIN_ONLY, 503 bei Störung"
  - "Stand je Gruppe: erfolgreiche Antwort ersetzt; ohne Antwort bleibt der Stand, nur Konten, die darin standen und abgelehnt wurden, fallen heraus; jede Abfrage abgelehnt (ohne Störung) = alles leer (fail closed wie bisher)"
  - "Vor dem ersten Lauf mit Schema 8 gilt der alte time_admins-Schnappschuss als Stand der Gruppe admin (Übergang ohne Rechteverlust)"
  - "META_NC_ADMINS: in verify_admins nur aus einer frischen Antwort der Gruppe admin, sonst []; in refresh_admins aus der Antwort, bei 403 ohne die Abgelehnten, bei Störung unverändert"
  - "purge_accounts prüft vor dem Abgleich zusätzlich frisch group_members(acting, admin) (Tiefenverteidigung gegen veraltetes nc_admins)"
  - "verwalter_seen wird mit der geschriebenen Vereinigung gepflegt (nicht nur frisch gelesene Gruppen), damit Dienstalter bei kurzer Störung nicht verloren geht"
metrics:
  duration: "ca. 25 min"
  completed: 2026-10-24
  tasks: 2
  files: 10
---

# Phase 6 Plan 01: Rollen-Kern ROLLE-03 Summary

Konfigurierbare Verwalter-Gruppen mit Fail-closed-Rückfall auf admin, NC-Admin-Sperre ohne Cache, Verwalter-Schnappschuss je Gruppe und ein Kontenabgleich, der nur noch im Namen eines frisch bestätigten Nextcloud-Admins läuft; dazu Schema 8 für alle neuen Tabellen der Phase.

## Was gebaut wurde

**Task 1 (d35b8aa): Schema 8 und Verwalter-Gruppen in roles.py**
- `SCHEMA_VERSION = "8"`, Tabellen `adults`, `verwalter_seen`, `verwalter_snapshot` (Konstante `ROLE_TABLES`), Spalten `talk_rooms.orphaned_token` und `former_owner` idempotent per `PRAGMA table_info` (Konstanten `ADD_TALK_ORPHANED`, `ADD_TALK_FORMER_OWNER`); `TalkRoomRow` trägt beide Felder, Leser liefern sie mit.
- `adults` in `ACCOUNT_TABLES` (P-08), Kommentar nachgeführt; `verwalter_seen`/`verwalter_snapshot` bewusst nicht.
- Store-Methoden `group_snapshot`, `replace_group_snapshot` (atomar je Gruppe), `drop_group_snapshots(keep)`, `sync_verwalter_seen(uids, now_iso)`, `verwalter_seniority()`.
- `roles.py`: `META_VERWALTER_GROUPS`, `parse_verwalter_groups` (JSON-Liste, nur str 1..64 Zeichen, admin immer dabei, kaputt = nur admin), `role_of(profile, verwalter_groups)`, `Profile.subadmin` (aus `info.subadmin`), `RoleService(lookup, groups)` mit `verwalter_groups()`, `invalidate()`, `nc_admin(uid)`; `require_nc_admin` + `NcAdminDep`; Modul-Docstring auf Phase 6 umgeschrieben.
- conftest: FakeDirectory mit `answers[(acting, gid)]` (Liste oder Ausnahme) und Profilen gw-lehrer, gw-kind-k, gw-kind-out.

**Task 2 (032e1de): Stand je Gruppe, NC-Admin-Menge, purge nur als NC-Admin**
- `refresh_admins`/`verify_admins` fragen jede Verwalter-Gruppe einzeln (admin zuerst); 403 oder Störung lassen nur den Stand dieser Gruppe stehen (P-03). Bestätigt ist ein Konto nur, wenn es die Gruppe selbst lesen kann und darin steht (CR-01), die Gegenprobe `app_accepted` bleibt vorn. Alle Nextcloud-Aufrufe außerhalb der Sperre, Schreiben im Worker-Thread unter `mutation()`/`try_mutation()`.
- `time_admins` bleibt die Vereinigung aller Gruppenstände: engine.py, talk/service.py, api/alerts.py und die Leser in notify/loop.py blieben unverändert.
- `META_NC_ADMINS = "nc_admins"` in playtime/service.py; `sync_verwalter_seen` nach jeder bestätigten Prüfung.
- `MAINTENANCE: list[MaintenanceStep]` = `[(purge_accounts, True), (talk_reconcile, False)]`; `run_hooks` gibt Admin-Schritten ein Konto aus nc_admins (bevorzugt acting), sonst `LOG.info("Kontenabgleich übersprungen: kein bestätigter Nextcloud-Admin")`; Fehlerisolierung je Schritt bleibt. `purge_accounts` prüft vorher frisch, ob acting in der Gruppe admin steht.

## Gates und Tests

- `uv run ruff check .`, `uv run ruff format --check .`, `pyright` (PYRIGHT_PYTHON_FORCE_VERSION=latest, 0 Fehler), `uv run vulture`: alle ohne Befund.
- `uv run pytest -q -m "not docker"`: 2291 passed, 43 deselected (Lauf nach Task 1: 2276 passed; Task 2 brachte 15 weitere).
- Unabhängige Gegenproben: Stand, meta und Dienstalter per rohem SQLite gelesen; Rollenwirkung über die echte Route `/api/worlds` mit roh geschriebener Konfiguration; Negativtest mit dem echten `purge_accounts` belegt 0 Verzeichnisaufrufe und den Erhalt des scheinbar gelöschten Kontos.
- Mutationsproben (danach zurückgesetzt): Admin-Flag in `run_hooks` ignoriert -> 4 Tests rot; frische admin-Prüfung in `purge_accounts` entfernt -> Stale-Test rot; Bestätigungsregel "steht in der eigenen Antwort" entfernt -> 2 Tests rot.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Sicherheit] Frische admin-Gegenprobe in purge_accounts**
- **Gefunden in:** Task 2
- **Problem:** `run_hooks` liest nc_admins zum Zeitpunkt der Wartung; zwischen Prüfung und Wartung (bis MAINTENANCE_SECONDS) könnte ein Eintrag veraltet sein, und die Positivkontrolle in `purge_missing_accounts` (`user(acting, acting)`) besteht auch ein Nicht-Admin.
- **Fix:** `purge_accounts` fragt vor dem Abgleich `group_members(acting, admin)`; Ablehnung, Störung oder fehlendes Konto = kein Abgleich. Test `test_stale_nc_admin_entry_is_checked_fresh_before_purge`.
- **Commit:** 032e1de

**2. [Rule 1 - Bug] Bestehende Tests an Schema 8 und MAINTENANCE-Format angepasst**
- `tests/test_store.py`: zwei Prüfungen auf das wörtliche `"7"` nach `migrate()` auf `SCHEMA_VERSION` umgestellt (Migration hebt auf den aktuellen Stand; nicht abgeschwächt, eigener 8-Test daneben).
- `tests/test_forget_account.py`: Vorbedingung "jede Kontentabelle hat Zeilen" verlangte durch `adults` in ACCOUNT_TABLES eine Erwachsen-Zeile; per rohem SQLite gesetzt (für GONE und das unbeteiligte Kind). Reihenfolge-Test liest jetzt die Paare und prüft zusätzlich das Admin-Flag.
- `tests/test_admin_snapshot.py`, `tests/test_notify_loop.py`: `MAINTENANCE`-Monkeypatches auf `(hook, False)` umgestellt.
- **Commits:** d35b8aa, 032e1de

**3. [Rule 3] refresh_admins fängt jetzt DirectoryRejectedError**
- Vorher lief eine 403 auf der Gruppe admin als Ausnahme aus `refresh_admins` heraus (mit nur admin als Verwalter-Gruppe nie erreichbar); mit Zusatzgruppen ist sie der Normalfall für Lehrer und wird je Gruppe behandelt.

Keine CLAUDE.md-bedingten Abweichungen. `api/me.py` nutzt weiter `role_of(profile)` ohne Gruppenmenge; das zieht laut Plan 06-02 nach (bis dahin ist keine Zusatzgruppe konfigurierbar, also kein Unterschied).

## Known Stubs

Keine. Die Tabelle `adults` und die Spalten `orphaned_token`/`former_owner` haben in diesem Plan noch keine Schreiber; das ist gewollt (Schema-Vorlauf für 06-04/06-05/06-06).

## Threat Flags

Keine neue Angriffsfläche außerhalb des Threat-Registers: kein neuer Endpunkt (require_nc_admin hängt noch an keiner Route, das folgt in 06-02), keine neuen Dateizugriffe. T-06-01 bis T-06-05 sind mit Tests mitigiert.

## Self-Check: PASSED

- FOUND: tests/test_verwalter_groups.py (514 Zeilen)
- FOUND: src/gameworld/access/roles.py mit require_nc_admin, parse_verwalter_groups, META_VERWALTER_GROUPS
- FOUND: src/gameworld/worlds/store.py mit SCHEMA_VERSION = "8"
- FOUND: Commit d35b8aa
- FOUND: Commit 032e1de
