---
phase: 03-zugang-und-rollen
plan: 03
subsystem: access
tags: [invites, schema-3, hmac, srp, appconfig_ex, e2e]
requires:
  - phase: 03-zugang-und-rollen
    provides: 03-01 Welt-Mod gameworld_access, make_verifier, write_world_files, build_access_tar; 03-02 require_verwalter, Rollen-Fakes
provides:
  - Schema 3 (players nc_user/player_name/rotation, invites, world_access, worlds.access_generation), ohne Passwortfeld
  - access/accounts.py (derive_password, suggest_player_name, PASSWORD_ALPHABET)
  - access/secret.py (PlayerSecret, get_player_secret, SecretUnavailableError; Geheimnis nur in appconfig_ex, sensitive)
  - access/directory.py (DirectoryUser, NcDirectory, get_directory, DirectoryUnavailableError)
  - access/service.py (AccessService.invite_user/revoke/list_players/list_invites, InviteTargetError, AccessResult, PlayerInfo)
  - api/invites.py (GET /api/worlds/{id}/players, POST /api/worlds/{id}/invites, POST /api/worlds/{id}/invites/remove)
  - WorldService.store, mutation(), push_access(); _access_file aus Schema 3; Löschen räumt Einladungen und Zugang mit ab
  - tests/conftest.py FakeDirectory, StaticSecret, TEST_SECRET, Fixtures fake_directory und fake_secret
  - scripts/dev/smoke-phase3-access.sh (Echtstack-Smoketest gegen die Dev-Nextcloud)
affects: [03-04, 03-05, 03-06, 03-07]
tech-stack:
  added: []
  patterns:
    - "Änderung am Zugang: async außerhalb der Sperre prüfen (Welt, Nextcloud, Geheimnis), dann im Worker-Thread unter WorldService.mutation() schreiben und push_access"
    - "Verifier nur für neue Einträge rechnen, vorhandene samt Salz behalten: gleicher Soll-Zustand ergibt dieselbe Zugangsdatei"
    - "Fehlerantworten der Zugangs-API nur mit festen deutschen Texten, nie mit Ausnahmetexten aus Nextcloud"
key-files:
  created:
    - src/gameworld/access/accounts.py
    - src/gameworld/access/secret.py
    - src/gameworld/access/directory.py
    - src/gameworld/access/service.py
    - src/gameworld/api/invites.py
    - tests/test_accounts.py
    - tests/test_access_service.py
    - tests/test_invites_api.py
    - tests/e2e/test_invite_join_e2e.py
    - scripts/dev/smoke-phase3-access.sh
  modified:
    - src/gameworld/worlds/store.py
    - src/gameworld/worlds/service.py
    - src/gameworld/main.py
    - tests/conftest.py
    - tests/test_store.py
    - tests/e2e/test_access_e2e.py
key-decisions:
  - "Passwort = zwölf Zeichen aus HMAC-SHA256(Geheimnis, 'nc_user:rotation'), per divmod über 31 Zeichen, erste Stelle = erster Rest; Testvektor gw-kind/0 = nyd5-hh9q-u45t"
  - "PlayerSecret läuft im App-Kontext ohne set_user: live belegt, kein uid-Fallback nötig; Nextcloud speichert den Wert sensitive=1 und verschlüsselt"
  - "applied bedeutet: Die Zugangsdatei der Welt entspricht der Datenbank. Ohne Soll-Änderung ist applied true (nichts offen), bei fehlendem Container oder Docker-Störung false"
  - "AccessService wird je Anfrage gebaut (zustandslos); Singletons sind nur Directory und PlayerSecret"
  - "NcDirectory kodiert die Konto-ID per quote(uid, safe='') für den OCS-Pfad und übernimmt die kanonische ID aus der Nextcloud-Antwort"
requirements-completed: []
metrics:
  duration: 17 min
  completed: 2026-10-20
  tasks: 3
  files: 16
---

# Phase 3 Plan 03: Nextcloud-Konten einladen Summary

Ein Verwalter lädt ein Nextcloud-Konto per API in eine Welt ein. Gameworld vergibt den Spielernamen, leitet das Passwort per HMAC aus einem Geheimnis in Nextcloud ab und schreibt den Verifier sofort in die laufende Welt. Das Konto kommt mit genau diesen Daten rein, ohne Neustart. Nach dem Widerruf ist es beim nächsten Join wieder draußen. In SQLite steht kein Passwort.

## Ergebnis

- **Schema 3** (`worlds/store.py`):
  - Neue Tabellen `players` (genau `nc_user`, `player_name` UNIQUE NOCASE, `rotation`), `invites` (CHECK kind) und `world_access`
  - Neue Spalte `worlds.access_generation`
  - Die Migration 2 auf 3 ist idempotent und lässt bestehende Welten unverändert.
  - `apply_world_access` ersetzt den Zugang und zählt die Generation in einer Transaktion hoch.
  - Keine Tabelle hat eine Spalte mit "pass" im Namen (Test).
- **Passwörter** (`access/accounts.py`):
  - Format `xxxx-xxxx-xxxx` aus `abcdefghjkmnpqrstuvwxyz23456789`, 59,4 Bit
  - Der Vektor ist unabhängig per `python -c` berechnet und im Test festgeschrieben.
  - `suggest_player_name`: Umschreibung der Umlaute über Escapes, NFKD, erstes Wort, Ziffer bei NOCASE-Kollision, nie `singleplayer`, höchstens 20 Zeichen
- **Geheimnis** (`access/secret.py`):
  - 32 Byte in `appconfig_ex` unter `player_password_secret`, `set_value(..., sensitive=True)`, danach Rücklesen
  - asyncio.Lock: 5 parallele erste Aufrufe erzeugen genau einmal (Test).
  - Ein unlesbarer Wert wird nie überschrieben (`SecretUnavailableError`).
  - Live in der Dev-Nextcloud geprüft: `oc_appconfig_ex` hat `sensitive=1`, und der Wert liegt verschlüsselt vor (324 Zeichen statt 64 Hex).
- **AccessService und API**:
  - Einladen prüft das Konto als Verwalter bei Nextcloud.
  - Zweite Welt: gleicher Name, gleiches Passwort, anderer Verifier (eigenes Salz).
  - Erneutes Einladen und ein Abgleich ohne Soll-Änderung schreiben nichts.
  - Widerruf: Generation +1, Push, die `players`-Zeile bleibt.
  - Unbekannte oder deaktivierte Konten: 422, nichts geschrieben.
  - Nextcloud oder Geheimnis nicht erreichbar: 503, nichts geschrieben.
  - Ohne Container oder bei Docker-Störung bleibt die DB geändert, `applied` ist false, die Warnung im Log nennt kein Passwort.
- **Leck-Test** (`test_invites_api.py`), caplog auf DEBUG über:
  - Einladen, Auflisten, Entfernen
  - unbekanntes Konto, deaktiviertes Konto, Docker weg, Geheimnis-Fehler, Nextcloud-Fehler
  - Geprüft wird: Weder Passwort (nachgerechnet) noch Geheimnis (Hex und bytes-repr) noch Verifier oder deren Teile stehen in Logs oder Fehler-Bodies.
- **Live-Nachweis** (`tests/e2e/test_invite_join_e2e.py`, echte MTG-Welt):
  - Vorher `denied` "nicht eingeladen"
  - Nach POST invites `auth_accept` mit Name und Passwort aus der Antwort
  - Falsches Passwort: `WRONG_PASSWORD`; Fremder: denied
  - State-Datei zeigt Generation 1 aus der DB
  - Nach Neustart weiter `auth_accept` (Datei aus Schema 3), Fremder weiter draußen
  - Nach Entfernen: denied
  - Zweite Welt mit identischem Namen und Passwort
  - SQLite-Bytes ohne Passwort, mit Spielername
- **Echtstack-Smoketest** `sh scripts/dev/smoke-phase3-access.sh`: **14 von 14 bestanden**, Exit 0
  - Einladen über den AppAPI-Proxy: 200
  - Unbekanntes Konto: 422
  - Passwort "Muster ok"
  - ExApp-Prozess gezielt beendet (PID-Datei, sonst nur der Prozess am Port 10040) und per register-exapp.sh neu gestartet
  - sha256 des Passworts vor und nach dem Neustart gleich
  - Passwort 0 Treffer in `.dev/storage/gameworld.sqlite3`, Spielername 2 Treffer
  - Welt gelöscht, kein Container übrig
  - Die Ausgabe enthält kein Passwort (grep auf das Muster: 0).
- **Gates**:
  - `GAMEWORLD_REQUIRE_DOCKER=1 uv run pytest -q`: 499 passed
  - ruff, ruff format, pyright (latest) und vulture grün
  - grep `LOG\.[a-z]+\(.*(password|secret|verifier)` in src: leer
  - Danach 0 Container mit `gameworld.managed=true`; das Dev-Backend läuft mit dem neuen Code (Heartbeat ok).

## nc_py_api-Signaturen (in .venv geprüft)

- `AsyncAppConfigExAPI.get_value(key, default=None) -> str | None` und `set_value(key, value, sensitive: bool | None = None)`: wie im Plan
- `AsyncUsersAPI.get_user(user_id="")` setzt die ID ungeprüft in den Pfad `/ocs/v1.php/cloud/users/{id}`. Deshalb kodiert NcDirectory sie mit `quote(uid, safe="")`.
- OCS 404 und 998 werden zu `NextcloudExceptionNotFound` (status_code 404). `UserInfo.enabled` ist standardmäßig True, `user_id` kommt aus dem Feld `id`.
- `users_groups.get_list(mask=...)` und `get_members` braucht dieser Plan nicht; sie sind für 03-04 vorgemerkt.

## Commits

| Task | Commit | Beschreibung |
|------|--------|--------------|
| 1 RED | 19b020c | failing tests Schema 3, Passwort-Vektor, Geheimnis |
| 1 GREEN | f0ac9bc | store.py Schema 3, accounts.py, secret.py |
| 2 | fd5754f | directory.py, AccessService, Invites-API, push_access, Fakes in conftest |
| 3 | 6cf84e0 | Join-e2e mit echter Einladung, 03-01-Erwartung, Echtstack-Smoketest |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `INSERT OR IGNORE` hebelte den CHECK auf `invites.kind` aus**
- **Found during:** Task 1
- **Issue:** SQLite ignoriert mit OR IGNORE auch CHECK-Verletzungen. Ein ungültiges `kind` wäre still verworfen worden.
- **Fix:** `INSERT ... ON CONFLICT (world_id, kind, target) DO NOTHING`. Damit wird nur die Dublette ignoriert, und der CHECK greift weiter (Test).
- **Commit:** f0ac9bc

**2. [Rule 2 - Sicherheit] Konto-ID im OCS-Pfad kodiert**
- **Found during:** Task 2 (Signaturprüfung)
- **Issue:** nc_py_api setzt `user_id` roh in den Pfad. Ein `target` mit `/` oder `..` hätte die Kontoprüfung auf einen anderen Endpunkt lenken können (T-03-18).
- **Fix:** `quote(uid, safe="")`. Zusätzlich wird die kanonische ID aus der Antwort übernommen. Die Pydantic-Prüfung lehnt außerdem Steuer- und Formatzeichen (Cc, Cf, etwa U+200B) ab.
- **Commit:** fd5754f

**3. [Rule 2] Zugangsdaten auch beim Abgleich-Löschen entfernt**
- Der Reconciler-Pfad `RETRY_DELETE` löscht die Weltzeile und ruft jetzt ebenfalls `delete_access_data`. Sonst blieben Einladungen einer im Abgleich gelöschten Welt verwaist.
- **Commit:** fd5754f

**4. [Hinweis] AccessService ohne eigenes Singleton**
- Der Dienst wird je Anfrage aus `get_service()`, `get_directory()` und `get_player_secret()` gebaut (`get_access_service` in api/invites.py). Er hält keinen Zustand. So greift `dependency_overrides` auf `get_service` in Tests ohne Rücksetzen.

**5. [Hinweis] Hilfsfunktionen in test_access_e2e.py öffentlich**
- `read_state`, `wait_for_state` und `assert_denied` haben keinen Unterstrich mehr, damit `test_invite_join_e2e.py` sie ohne Import privater Namen nutzt. Erwartung und Kommentar von Test (5) verweisen auf 03-03.

**6. [Hinweis] Ruff S105 bei Konstanten**
- `PASSWORD_ALPHABET` und `SECRET_KEY` sind keine Passwörter. Beide bekommen `# noqa: S105` mit Begründung.

## TDD Gate Compliance

- Task 1: RED-Commit 19b020c vor GREEN f0ac9bc, wie vorgesehen.
- Task 2: Implementierung und Tests landeten im selben Commit fd5754f, es gibt also keinen eigenen RED-Commit. Die Tests decken jede Behavior-Zeile ab und liefen beim ersten Lauf grün. Ein Fehlschlag vor der Implementierung ist damit nicht belegt.

## Known Limitations

- Die Anzeigenamen in `list_players` kommen live aus Nextcloud, ein Aufruf pro Spieler und ohne Cache. Bei Störung fällt die Anzeige auf die Konto-ID zurück. Für Familiengrößen reicht das; 03-04 kann bei Gruppen bündeln.
- Wird ein eingeladenes Konto in Nextcloud deaktiviert, fliegt es erst bei der nächsten Zugangsänderung der Welt aus dem Zugang (Abgleich nur bei Änderung). Der regelmäßige oder vom Verwalter ausgelöste Abgleich folgt in 03-04.
- `.dev/exapp.log` enthält beim Neustart eine Zeile "Invalid App secret: x != y" aus nc_py_api: Die AppAPI-Secrets alter und neuer Lauf. Das betrifft nicht das Spielgeheimnis und war schon vorher so. Es ist ein reines Dev-Log, nicht im Scope.

## Self-Check: PASSED

- Dateien vorhanden: accounts.py, secret.py, directory.py, service.py (access), invites.py, test_accounts.py, test_access_service.py, test_invites_api.py, test_invite_join_e2e.py, smoke-phase3-access.sh
- Commits vorhanden: 19b020c, f0ac9bc, fd5754f, 6cf84e0
- Keine Welt-Container übrig (`docker ps -a --filter label=gameworld.managed=true`: 0)
