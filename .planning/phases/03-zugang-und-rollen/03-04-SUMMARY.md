---
phase: 03-zugang-und-rollen
plan: 04
subsystem: access
tags: [groups, sync, password-rotation, rename, secret-fingerprint, e2e]
requires:
  - phase: 03-zugang-und-rollen
    provides: 03-03 Schema 3, AccessService, derive_password, PlayerSecret, NcDirectory, Invites-API; 03-01 Welt-Mod gameworld_access; 03-02 require_verwalter
provides:
  - AccessService.invite_group, sync_world, sync_all (Drossel SYNC_INTERVAL_SECONDS = 60), rotate_password, rename_player, reprovision_all
  - Directory.group_members und group_exists (NcDirectory über users_groups.get_members, ID per quote kodiert)
  - accounts.validate_player_name, secret.fingerprint
  - WorldStore.get_meta/set_meta, player_name_owner, player_worlds, update_player_access (eine Transaktion)
  - WorldService.try_mutation (Sperre ohne Warten)
  - API kind group, POST /api/players/password, POST /api/players/name, Abgleich in GET /api/worlds
affects: [03-05, 03-06, 03-07]
tech-stack:
  added: []
  patterns:
    - "Effektive Spieler = direkte Konten plus Mitglieder eingeladener Gruppen, aufgelöst als Verwalter vor der Sperre; jede Einladung merkt sich, über welche Quelle ein Konto kommt"
    - "_ensure_fingerprint als eigener async-Schritt nach dem Laden des Geheimnisses; reprovision_all nimmt die Sperre selbst und gibt sie vor dem Schritt des Aufrufers frei"
    - "Abgleich beim Auflisten wartet nie auf die Welt-Sperre (try_mutation); belegte Sperre verbraucht die Drossel nicht"
key-files:
  created: []
  modified:
    - src/gameworld/access/service.py
    - src/gameworld/access/directory.py
    - src/gameworld/access/accounts.py
    - src/gameworld/access/secret.py
    - src/gameworld/worlds/store.py
    - src/gameworld/worlds/service.py
    - src/gameworld/api/invites.py
    - src/gameworld/api/worlds.py
    - tests/conftest.py
    - tests/test_accounts.py
    - tests/test_access_service.py
    - tests/test_invites_api.py
    - tests/e2e/test_invite_join_e2e.py
key-decisions:
  - "sync_all wartet nie auf worlds._LOCK (neu: WorldService.try_mutation). Ist die Sperre belegt, etwa durch ein Erzeugen, wird die Welt übersprungen und die Drossel zurückgesetzt, damit der nächste Poll es erneut versucht. Sonst hinge GET /api/worlds hinter jedem Erzeugen (Phase-2-Pitfall 6)"
  - "Ein 403 oder Netzfehler bei der Gruppenauflösung ist eine Störung (503 bzw. Warnung), nie eine leere Gruppe: Kein Abgleich entfernt Zugänge, weil Nextcloud nicht antwortet. Nur eine nicht vorhandene Gruppe (404/998) zählt als leer"
  - "Passwort neu und Umbenennen antworten mit PlayerChangeOut (nc_user, display_name, player_name, password, applied) statt PlayerOut, weil via für ein weltübergreifendes Konto keinen Sinn hat"
  - "Fingerabdruck = HMAC-SHA256(Geheimnis, 'gameworld:fingerprint'), 16 Hex-Zeichen, in meta secret_fingerprint; fehlt er, wird er nur gespeichert (vorhandene Verifier stammen aus dem aktuellen Geheimnis)"
  - "Umbenennen auf den eigenen Namen in anderer Schreibweise ist erlaubt; derselbe Name exakt ist ein No-op ohne neue Generation"
requirements-completed: []
metrics:
  duration: 20 min
  completed: 2026-10-20
  tasks: 2
  files: 13
---

# Phase 3 Plan 04: Gruppen, Passwort neu, Umbenennen, Geheimniswechsel Summary

Ein Verwalter lädt jetzt ganze Nextcloud-Gruppen ein. Die Mitgliedschaft wird bei jeder Einladungsänderung und beim Verwalter-Besuch (höchstens einmal pro Minute) frisch aus Nextcloud gelesen. Passwort neu und Umbenennen wirken sofort in allen Welten des Kontos, ohne Neustart. Ein neues Geheimnis in Nextcloud erkennt Gameworld am Fingerabdruck und rechnet alle Verifier neu. Alles ist per API nutzbar und gegen eine echte MTG-Welt belegt.

## Ergebnis

- **Gruppen** (`access/service.py`, `access/directory.py`):
  - `invite_group` prüft die Gruppe als Verwalter (`group_exists`), unbekannte Gruppe: `InviteTargetError` (422).
  - Effektiv sind nur vorhandene, aktive Mitglieder. `familie` mit gw-kind (aktiv) und gw-aus (deaktiviert) ergibt nur gw-kind, `via` = `group:familie`.
  - Direkt und über eine Gruppe eingeladen: ein Eintrag. Entfernen der Gruppe lässt den direkten Zugang stehen.
  - `revoke` kann `kind` "group".
- **Abgleich**:
  - `sync_world`: Ausgetretene und deaktivierte Konten verlieren den Zugang (Generation +1, Push), neue Mitglieder kommen dazu, ohne Änderung kein Push.
  - `sync_all` mit `SYNC_INTERVAL_SECONDS = 60` (monotonic, pro Prozess); der Fehler einer Welt bricht die anderen nicht ab.
  - `GET /api/worlds` ruft `sync_all(uid)` im try/except; Fehler nur als Warnung mit Typname, die Liste kommt immer (T-03-33).
- **Passwort neu** (`rotate_password`, `POST /api/players/password`): rotation +1, alle Verifier des Kontos in derselben Transaktion neu (neues Salz), Generation jeder betroffenen Welt +1, Push je Welt. Unbekanntes Konto: 404.
- **Umbenennen** (`rename_player`, `POST /api/players/name`): `validate_player_name` (1 bis 20 Zeichen `[A-Za-z0-9_-]`, nie `singleplayer`, deutsche Meldung, 422), NOCASE-Kollision 409, unbekannt 404. Danach gilt der neue Name in allen Welten.
- **Geheimniswechsel**: `_ensure_fingerprint` läuft direkt nach dem Laden des Geheimnisses außerhalb der Sperre. Bei Abweichung nimmt `reprovision_all` die Sperre einmal für alle Welten, rechnet alle Verifier neu, speichert den Fingerabdruck in derselben Sperrphase und pusht je Welt. `_apply_effective`, `_rewrite_player` und `reprovision_all` rufen `_ensure_fingerprint` nie auf (Docstrings).
- **Deadlock-Tests**: Geheimnis vor `invite_user`, `rotate_password` und `sync_all` getauscht, je mit `anyio.fail_after(5)` gegen das echte `worlds._LOCK`. Danach Einladung vorhanden, alle Verifier passen zum neuen Geheimnis, und `_LOCK.acquire(blocking=False)` gelingt.
- **Leck-Test** (`test_invites_api.py`), caplog auf DEBUG über:
  - Gruppe einladen, Passwort neu zweimal, Umbenennen, Abgleich
  - 409, 422 (singleplayer, unbekannte Gruppe), 404 (zweimal), 503 (Geheimnis bei Rotation und Gruppe, Nextcloud bei Gruppe), Docker weg bei Rotation
  - Geprüft wird: Weder Passwörter der Rotationen 0 bis 3 (nachgerechnet) noch Geheimnis (Hex, bytes-repr) noch Verifier oder deren Teile stehen in Logs oder Fehler-Bodies.
- **e2e** (`test_group_rotation_rename_and_sync_in_running_world`, echte MTG-Welt):
  - Gruppe familie einladen: gw-kind `auth_accept`
  - Passwort neu: altes `WRONG_PASSWORD`, neues `auth_accept`
  - Umbenennen in "KindNeu": `auth_accept`, alter Name denied "nicht eingeladen"
  - Austritt aus der Fake-Gruppe plus `GET /api/worlds` (Drossel 0): denied
  - Container-ID und `StartedAt` am Ende gleich wie am Anfang: kein Neustart
- **Live gegen die Dev-Nextcloud** (echtes `NcDirectory.group_members`, `users_groups.get_members` als admin):
  - Gruppe `gw-familie` mit gw-kind per occ angelegt, Welt über den AppAPI-Proxy erzeugt
  - Gruppe einladen: 200, `via` `group:gw-familie`, applied true
  - Unbekannte Gruppe: 422; Passwort neu: 200; Weltliste: 200
  - gw-kind per occ aus der Gruppe genommen, 62 s gewartet, Weltliste geladen: Spielerliste leer, Einladung der Gruppe bleibt
  - Welt gelöscht (204), Gruppe gelöscht, 0 Welt-Container, Heartbeat ok
- **Gates**:
  - `GAMEWORLD_REQUIRE_DOCKER=1 uv run pytest -q`: 540 passed, nichts übersprungen
  - ruff, ruff format, pyright (latest) und vulture grün
  - grep `LOG\.[a-z]+\(.*(password|secret|verifier)` in src: leer
  - Dev-Backend per `register-exapp.sh` mit dem neuen Code neu gestartet

## nc_py_api-Signaturen (in .venv geprüft)

- `_AsyncUsersGroupsAPI.get_members(group_id)` setzt die ID roh in `/ocs/v1.php/cloud/groups/{id}`. NcDirectory kodiert sie mit `quote(gid, safe="")`.
- Bei leerer Antwort liefert `get_members` `{}` statt `[]`; NcDirectory macht daraus eine leere Liste.
- `get_list(mask=...)` mappt intern auf den OCS-Parameter `search`; dieser Plan braucht es nicht.
- OCS 404/998 werden zu `NextcloudExceptionNotFound`; 403 bleibt `NextcloudException(403)` und gilt als Störung.

## Commits

| Task | Commit | Beschreibung |
|------|--------|--------------|
| 1 | 13d4aae | Gruppen, Abgleich, Rotation, Umbenennen, Fingerabdruck im AccessService, Store- und Sperr-Erweiterungen, Tests |
| 2 | 0ee89b2 | API für Gruppen, Passwort neu, Umbenennen, Abgleich in GET /api/worlds, API-Tests, e2e |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Abgleich beim Auflisten hätte hinter jedem Erzeugen gewartet**
- **Found during:** Task 1
- **Issue:** `sync_all` läuft in `GET /api/worlds`. Mit dem blockierenden `mutation()` hätte die Weltenliste so lange gehangen, wie ein Erzeugen die Sperre hält (VoxeLibre mehrere Sekunden, Image-Pull länger). Das bricht die Phase-2-Regel "Statuslesen wartet nie hinter einem Erzeugen".
- **Fix:** `WorldService.try_mutation()` (nicht blockierend, gleicher Cache-Verwurf). `sync_all` und dessen Fingerabdruck-Schritt nutzen sie; bei belegter Sperre wird die Welt übersprungen und die Drossel zurückgesetzt (Test `test_sync_all_skips_busy_lock_and_retries`).
- **Files modified:** src/gameworld/worlds/service.py, src/gameworld/access/service.py
- **Commit:** 13d4aae

**2. [Rule 3 - Blocking] Store-Methoden ergänzt**
- `worlds/store.py` stand nicht in `files_modified`. Für Fingerabdruck, NOCASE-Prüfung und die geforderte eine Transaktion bei Rotation und Umbenennen braucht es `get_meta`/`set_meta`, `player_name_owner`, `player_worlds` und `update_player_access`.
- **Commit:** 13d4aae

**3. [Rule 2 - Sicherheit] Gruppen-ID im OCS-Pfad kodiert, 403 nie als leere Gruppe**
- Gleiche Pfadinjektions-Lage wie bei der Konto-ID in 03-03. Außerdem würde ein als leer gedeutetes 403 bei einem späteren Nicht-Admin-Verwalter alle Gruppenmitglieder aussperren.
- **Commit:** 13d4aae

**4. [Hinweis] Antwortmodell PlayerChangeOut statt PlayerOut**
- Der Plan nannte "PlayerOut mit neuem Passwort plus applied". `via` gehört aber zu einer Welt, Passwort und Name gelten für alle Welten. Darum ein eigenes Modell ohne `via`, mit `applied`.

**5. [Hinweis] Validierungstest im bestehenden API-Test angepasst**
- `{"kind": "group", ...}` war in 03-03 ein 422-Fall. Er ist jetzt gültig; der Ungültig-Fall heißt `{"kind": "team", ...}`. `MSG_INVALID_TARGET` lautet jetzt "Ungültige Konto- oder Gruppen-ID."

## TDD Gate Compliance

- Task 1 ist `tdd="true"`, aber Implementierung und Tests landeten im selben Commit 13d4aae; es gibt keinen eigenen RED-Commit. Die Tests decken jede Behavior-Zeile ab und liefen nach der Implementierung grün. Ein Fehlschlag vor der Implementierung ist damit nicht belegt (wie in 03-03 Task 2).

## Known Limitations

- Austritt aus einer Gruppe oder Deaktivierung wirkt erst bei der nächsten Einladungsänderung oder beim nächsten Verwalter-Besuch (T-03-27, accept, Open Question 4 DEFERRED).
- `sync_all` fragt pro Welt jedes Konto und jede Gruppe einzeln bei Nextcloud ab, ohne Cache über Welten hinweg. Für Familiengrößen reicht das bei einem Lauf pro Minute.
- Umbenennen erzeugt in Luanti ein neues Konto; Inventar und Fortschritt des alten Namens bleiben verwaist in der Welt (Pattern 6). Die Oberfläche in 03-05 sollte das vor dem Umbenennen sagen.

## Self-Check: PASSED

- Dateien vorhanden: alle 13 geänderten Dateien unter src/ und tests/
- Commits vorhanden: 13d4aae, 0ee89b2
- Keine Welt-Container übrig (`docker ps -a --filter label=gameworld.managed=true`: 0)
