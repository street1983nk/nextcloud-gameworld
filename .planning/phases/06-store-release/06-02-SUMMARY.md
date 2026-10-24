---
phase: 06-store-release
plan: 02
subsystem: roles
tags: [roles, security, 404-trap, routes, admin-api, negative-tests]
requires: ["06-01"]
provides:
  - "access/service.py: Actor, actor_of, InviteScopeError, MSG_ACCOUNT_OUT_OF_SCOPE, MSG_GROUP_OUT_OF_SCOPE, _confirmed (frische NC-Admin-Bestätigung), _resolve_limited (Nicht-Admin-Pfad)"
  - "api/admin.py: /api/admin/verwalter-groups (GET, add, remove), /api/admin/groups?search= mit routerweitem require_nc_admin"
  - "Directory.search_groups (NcDirectory über users_groups.get_details, FakeDirectory)"
  - "/api/me: nc_admin, invite_groups (nur Verwalter)"
  - "info.xml ohne ADMIN-Stufe, tests/test_route_guards.py als Strukturtest aller /api/-Routen"
affects: [06-03, 06-04, 06-05, 06-06, 06-10]
tech-stack:
  added: []
  patterns:
    - "Actor statt acting_uid für alle Abläufe, die Einladungen auflösen und world_access abgleichen"
    - "404 heißt gelöscht nur für einen frisch an der Gruppe admin bestätigten NC-Admin"
    - "Strukturtest über den Abhängigkeitsbaum aller Routen mit Selbstprobe"
key_files:
  created:
    - src/gameworld/api/admin.py
    - tests/test_route_guards.py
  modified:
    - src/gameworld/access/service.py
    - src/gameworld/access/directory.py
    - src/gameworld/api/invites.py
    - src/gameworld/api/worlds.py
    - src/gameworld/api/me.py
    - src/gameworld/main.py
    - src/gameworld/lifecycle.py
    - appinfo/info.xml
    - tests/conftest.py
    - tests/test_access_service.py
    - tests/test_forget_account.py
    - tests/test_invites_api.py
    - tests/test_verwalter_groups.py
    - tests/test_roles.py
    - tests/test_info_xml.py
decisions:
  - "Ändernde Abläufe (invite_user, invite_group, revoke, sync_world, sync_all) bestätigen nc_admin vorher frisch per group_members(actor, admin); Ablehnung, 404 oder fehlendes Konto = Nicht-Admin-Pfad, Störung = Abbruch ohne Schreiben. Grund: Das Profil hinter dem Actor kommt aus dem 30-s-Rollen-Cache"
  - "revoke nimmt ebenfalls einen Actor (Plan nannte acting_uid): revoke löst die übrigen Einladungen auf und gleicht world_access ab, wäre also sonst ein zweiter 404-Pfad"
  - "Nicht-Admin: strict (Abgleich) bricht die Welt bei 403 oder 404 auf eine Gruppe ohne Änderung ab; nicht strict (Einladen, Widerrufen) lässt die unlesbare Gruppe unaufgelöst, die keep-Regel hält ihre Zugänge"
  - "Direkte Einladungen eines Nicht-Admins landen in _Resolution.kept: bestehender Zugang bleibt, ohne Zugang wird nicht ergänzt (ein vom NC-Admin entfernter deaktivierter Zugang kommt nicht zurück)"
  - "sync_all bei Störung der Admin-Bestätigung: Drossel bleibt verbraucht, kein Abgleich (keine Last während eines Ausfalls)"
  - "rotate_password und rename_player behalten acting_uid: sie ändern nur die Zeile des Kontos, _display_name ist reine Anzeige"
  - "/api/my/playtime nutzt jetzt role_of mit den konfigurierten Verwalter-Gruppen (Lehrer sind wie admin von der Spielzeit frei); offener Punkt aus 06-01"
metrics:
  duration: "ca. 75 min"
  completed: 2026-10-24
  tasks: 3
  files: 17
---

# Phase 6 Plan 02: Einladungs-Umfang, Admin-API und Routenstufe USER Summary

Gruppen-Verwalter ohne NC-Admin laden nur aus ihren eigenen Gruppen und Subadmin-Gruppen ein und können durch die 404-Falle keinen Zugang mehr entfernen; NC-Admins pflegen die Verwalter-Gruppen über /api/admin, und info.xml kennt keine ADMIN-Stufe mehr, abgesichert durch einen Strukturtest über alle Routen.

## Was gebaut wurde

**Task 1 (8e45dd4): Einladungs-Umfang und Abgleich ohne 404-Entfernen**
- `Actor(uid, nc_admin, groups)` und `actor_of(profile)` (groups = Gruppen plus Subadmin-Gruppen); `InviteScopeError` mit den UI-SPEC-Texten "Dieses Konto ist in keiner deiner Gruppen." und "Diese Gruppe gehört nicht zu deinen Gruppen." (API: 403).
- `invite_user` als Nicht-Admin: Ziel muss in `group_members(actor, gid)` einer eigenen Gruppe stehen (403 auf einer Gruppe überspringt nur diese, Störung = 503), kein `user()`-Lookup, Anzeigename = Konto-ID. `invite_group`: gid muss in `actor.groups` stehen. Beides vor jeder Store-Änderung.
- `_resolve` als Nicht-Admin (`_resolve_limited`): nie `user()` je Konto, Gruppenmitglieder gelten als aktiv, direkte Einladungen bleiben unverändert (`kept`), unlesbare Gruppe bricht den Abgleich dieser Welt ab. NC-Admin-Pfad unverändert.
- `_confirmed`: frische Bestätigung des NC-Admin-Rechts vor jeder Änderung (siehe Abweichungen).
- `purge_missing_accounts` lehnt jedes Konto ab, das nicht in meta `nc_admins` steht (Log, `[]`, kein Nextcloud-Aufruf).
- api/invites.py: `current_actor` (Profil über RolesDep, 503 bei Störung), alle Einladungs-, Widerrufs- und Listenrouten mit Actor; api/worlds.py: `sync_all(actor_of(profile))`.

**Task 2 (9ad987c): Admin-API, Gruppensuche, /api/me**
- `api/admin.py`: `APIRouter(prefix="/api/admin", dependencies=[Depends(require_nc_admin)])`; GET/add/remove der Verwalter-Gruppen (admin nie in der Liste, nie entfernbar, 422-Texte wie im Plan, unbekannte Gruppe 422 ohne meta-Änderung, `compare_and_set_meta` mit einem Wiederholversuch, sonst 409), nach jeder Änderung `roles.invalidate()` und `refresh_admins(uid, force=True)`; GET `/groups?search=` (max. 64 Zeichen, max. 20 Treffer, Störung 503 mit eigenem Text).
- `Directory.search_groups` (nc_py_api 0.30.3: `users_groups.get_details(mask, limit)` liefert ID und Anzeigenamen), FakeDirectory mit `group_names`, `search_calls`, `search_error`.
- `/api/me`: `nc_admin` und `invite_groups` (sortiert) nur für Verwalter, Kinder `false`/`[]`; Rolle mit konfigurierten Gruppen.
- D-03/D-04 per Test festgeschrieben: Lehrer sieht die von admin angelegte Welt und bedient Einstellungen, Pause, Ferien, Zeitzone (je 200), Kind der Klasse 403.

**Task 3 (02f66d0): info.xml USER, Strukturtest, Spike-404**
- `^/api/.*` auf USER, Kopfkommentar neu (F-03, require_verwalter/require_nc_admin als einzige Sperre, Verweis auf den Strukturtest, D-23 für die Spike-Routen); weder "public" noch "announce" in der Datei.
- `tests/test_info_xml.py`: `test_api_catch_all_is_last_and_no_admin_level`, Docstrings nachgezogen.
- `tests/test_route_guards.py` (228 Zeilen): Prüfer über den rekursiven Abhängigkeitsbaum jeder Route der echten App, Selbstprobe auf einer frischen FastAPI-App (ungesperrte /api/probe und eine nur mit require_verwalter gesperrte /api/admin/probe werden erkannt, verschachtelte Sperre und /api/my/ nicht), Leerlauf-Schutz (mindestens 40 gesperrte Anfragen, 4 Admin-Routen), Kind-403 je Route und Verb aus der App erzeugt (kein Weltdienst, keine Verzeichnisabfrage), Spike-Routen im Manifest und 404 ohne `GAMEWORLD_BROWSER_SPIKE` (auch für admin).
- lifecycle.py: nur der Kommentar.

## Gates und Tests

- Vor jedem Commit: `uv run ruff check .`, `uv run ruff format --check .`, pyright (PYRIGHT_PYTHON_FORCE_VERSION=latest, 0 Fehler), `uv run vulture`: ohne Befund.
- `uv run pytest -q -m "not docker"`: nach Task 1 2312 passed, nach Task 2 2344 passed, nach Task 3 2392 passed (je 44 deselected).
- Unabhängige Gegenproben: invites, world_access und players werden vorher und nachher roh per sqlite3 gelesen (Lehrer-Abgleich mit `user()` = None für jedes Konto: vorher == nachher; kontofremde Einladung: 403/InviteScopeError ohne DB-Änderung und ohne Schreiben einer Zugangsdatei); meta und verwalter_snapshot der Admin-API ebenfalls roh.
- Mutationsproben (danach zurückgesetzt): Nicht-Admin-Pfad in `_resolve` und `_confirmed` abgeschaltet: 6 Tests rot; Admin-Router auf require_verwalter geschwächt: 9 Tests rot; Sperre des Talk-Routers entfernt: Strukturtest und 3 Kind-Tests rot.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Sicherheit] Frische NC-Admin-Bestätigung (`_confirmed`)**
- **Gefunden in:** Task 1
- **Problem:** `actor_of` liest nc_admin aus dem Profil, das RoleService bis zu 30 s cacht. Ein gerade aus admin entferntes Konto wäre sonst noch auf dem Pfad "404 heißt gelöscht" gelaufen, also genau die 404-Falle.
- **Fix:** Jeder ändernde Ablauf fragt vorher `group_members(actor, admin)`; ohne Bestätigung gilt der Nicht-Admin-Pfad. Test `test_stale_admin_profile_takes_the_safe_path`.
- **Commit:** 8e45dd4

**2. [Rule 2 - Sicherheit] revoke mit Actor statt acting_uid**
- **Problem:** Der Plan erlaubte acting_uid für revoke, revoke löst aber alle Einladungen der Welt auf und gleicht world_access ab; als Lehrer wäre das ein zweiter 404-Pfad gewesen.
- **Fix:** revoke nimmt einen Actor und den nicht strikten Nicht-Admin-Pfad.
- **Commit:** 8e45dd4

**3. [Rule 2] 404 auf eine Gruppe zählt für Nicht-Admins als nicht lesbar**
- **Problem:** Für Nicht-Admins kann Nextcloud eine nicht sichtbare Gruppe als 404 melden; "fehlende Gruppe = leer" hätte ihre Mitglieder entfernt.
- **Fix:** Abgleich der Welt bricht ab (strict), Einladen/Widerrufen lässt sie unaufgelöst. Test `test_teacher_sync_treats_missing_group_as_unreadable`.

**4. [Rule 3] Bestehende Tests an Actor und nc_admins angepasst (nicht abgeschwächt)**
- test_access_service.py/test_forget_account.py: `"admin"` als handelndes Konto durch `ADMIN_ACTOR` ersetzt; die Wettlauf-Tests mit `admin-b` tragen admin-b in die Gruppe admin ein (sonst stufte `_confirmed` ihn korrekt herab).
- test_forget_account.py: Fixture setzt meta `nc_admins = ["admin"]` (Zustand nach verify_admins), weil purge sonst jetzt ablehnt.
- test_info_xml.py: `test_user_routes_are_anchored_or_static` nimmt das Auffangmuster (letzte Route, jetzt USER) aus; die Ankerpflicht der festen Routen bleibt.
- test_roles.py: exakte /api/me-Vergleiche um nc_admin und invite_groups ergänzt.

**5. [Rule 1] /api/my/playtime mit konfigurierten Verwalter-Gruppen**
- Offener Punkt aus 06-01: `role_of(profile)` ohne Gruppenmenge hätte Lehrer als Spieler mit Spielzeit-Grenzen gezählt.

**6. Strukturtest und FastAPI 0.143**
- `APP.routes` enthält seit FastAPI 0.14x eingebundene Router als `_IncludedRouter`, nicht mehr flache Routen. Der Test nutzt `fastapi.routing._iter_included_route_candidates` (Rückfall auf `app.routes`, falls es fehlt) und sichert per `test_route_listing_is_not_vacuous` ab, dass die Auflistung nicht still leer wird.

TDD-Hinweis: Die Tasks trugen tdd="true", wurden aber je Task als ein feat-Commit mit Tests geliefert (kein getrennter RED-Commit); die Wirksamkeit der Tests belegen die Mutationsproben oben.

## Known Stubs

Keine.

## Bekannte Grenzen

- Deaktivierte Konten erkennt nur der NC-Admin-Abgleich (RESEARCH 1.4): Ein deaktiviertes Mitglied einer Lehrer-Gruppe kann bei einem Lehrer-Abgleich wieder Zugang bekommen, bis der nächste NC-Admin-Abgleich ihn entfernt.
- Widerruft ein Lehrer eine Gruppe, die er nicht lesen kann, ist die Einladung weg, die Zugänge ihrer Mitglieder bleiben bis zum nächsten NC-Admin-Abgleich.
- Die SYNC-Drossel ist prozessweit: Ein Lehrer-Besuch verbraucht sie auch für einen folgenden Admin-Besuch (höchstens 60 s Verzögerung).

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag: new-endpoint | src/gameworld/api/admin.py | Vier neue Routen unter /api/admin (T-06-07/T-06-11 im Register, mitigiert durch routerweites require_nc_admin und Tests je Route und Verb) |
| threat_flag: auth-path | appinfo/info.xml | ^/api/.* auf USER: AppAPI lässt jedes angemeldete Konto durch (T-06-06, mitigiert durch Strukturtest und Kind-403 je Route) |

Keine Angriffsfläche außerhalb des Threat-Registers.

## Self-Check: PASSED

- FOUND: src/gameworld/api/admin.py
- FOUND: tests/test_route_guards.py (228 Zeilen)
- FOUND: class InviteScopeError, class Actor, def actor_of in src/gameworld/access/service.py
- FOUND: 0 x `<access_level>ADMIN</access_level>` in appinfo/info.xml, beide Spike-Routen vorhanden
- FOUND: Commit 8e45dd4
- FOUND: Commit 9ad987c
- FOUND: Commit 02f66d0
