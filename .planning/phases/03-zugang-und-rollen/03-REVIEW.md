---
phase: 03-zugang-und-rollen
reviewed: 2026-10-20T04:50:33Z
depth: standard
files_reviewed: 41
files_reviewed_list:
  - src/gameworld/access/__init__.py
  - src/gameworld/access/accounts.py
  - src/gameworld/access/directory.py
  - src/gameworld/access/roles.py
  - src/gameworld/access/secret.py
  - src/gameworld/access/service.py
  - src/gameworld/api/invites.py
  - src/gameworld/api/me.py
  - src/gameworld/api/setup_check.py
  - src/gameworld/api/worlds.py
  - src/gameworld/provisioner/access_mod.py
  - src/gameworld/provisioner/archive.py
  - src/gameworld/provisioner/client.py
  - src/gameworld/provisioner/luanti_auth.py
  - src/gameworld/worlds/service.py
  - src/gameworld/worlds/store.py
  - src/gameworld/lifecycle.py
  - src/gameworld/main.py
  - appinfo/info.xml
  - frontend/src/App.vue
  - frontend/src/api.js
  - frontend/src/views/ParentView.vue
  - frontend/src/views/PlayerView.vue
  - frontend/src/components/ConnectionCard.vue
  - frontend/src/components/InviteDialog.vue
  - frontend/src/components/JoinGuide.vue
  - frontend/src/components/JoinHostSettings.vue
  - frontend/src/components/PlayerManager.vue
  - tests/test_access_mod.py
  - tests/test_access_service.py
  - tests/test_accounts.py
  - tests/test_luanti_auth.py
  - tests/test_roles.py
  - tests/test_invites_api.py
  - tests/test_my_worlds.py
  - tests/test_settings_api.py
  - tests/test_store.py
  - tests/test_archive.py
  - tests/e2e/luanti_probe.py
  - scripts/dev/acceptance-phase3.sh
  - scripts/dev/smoke-phase3-access.sh
findings:
  critical: 0
  warning: 2
  info: 7
  total: 9
status: issues_found
---

# Phase 3: Code-Review-Bericht (Zugang und Rollen)

**Reviewed:** 2026-10-20T04:50:33Z
**Depth:** standard (per-file, plus Cross-File für Sperr-Regel, Rollen-Durchsetzung und Geheimnis-Fluss)
**Files Reviewed:** 41 (Tests nur auf Korrektheit der Prüfer gesichtet, keine Stil-Findings)
**Status:** issues_found

## Summary

Geprüft wurde der Phase-3-Code seit 49f0c69, rein statisch, mit Schwerpunkt auf den sieben Sicherheitspunkten des Threat-Models. Konkret nachvollzogen und in Ordnung:

1. **HMAC-Passwort-Ableitung:** `derive_password` entspricht exakt dem Testvektor (`nyd5-hh9q-u45t` ist in `tests/test_accounts.py:24,37` festgeschrieben). Das Geheimnis liegt nur in `appconfig_ex` (sensitive), wird nie geloggt (einziger Treffer von `LOG.*(…geheimnis…)` ist eine Meldung ohne Wert, `access/service.py:392`), erscheint in keiner Fehlermeldung (`secret.py:100` gibt nur den Ausnahmetyp weiter) und steht in keiner API-Antwort. Konstantzeitlichkeit: Es gibt serverseitig keinen Passwortvergleich (SRP prüft Luanti selbst); der Fingerabdruck-Vergleich (`stored == current`) ist kein Orakel, weil kein Angreifer Eingaben dafür liefert.
2. **Rollen-Durchsetzung:** `worlds.router`, `setup_check.router` und `invites.router` hängen routerweit an `require_verwalter` (zweite Schicht); `me.router` hat nur `/api/me` und `/api/my/worlds` und liefert ausschließlich Daten des signierten `scope["username"]`. Der 30-s-Cache in `RoleService` cacht nur Erfolge (`roles.py:70-75`, Test `test_lookup_error_gives_503_and_is_not_cached`). Jede Störung wird 503, nie Verwalter. `/api/my/worlds` filtert strikt auf eigene `world_access`-Zeilen; der Leck-Test (`test_my_worlds.py:131-152`) prüft fremde Namen, Passwörter und verbotene Felder in der Rohantwort. info.xml: 4 USER-Routen vor dem ADMIN-Auffangmuster, `^/api/me$` mit End-Anker; PUT/PATCH matchen keine Route (fail closed). Path-Tricks wie `/api/my/../worlds` landen selbst bei normalisierenden Zwischenschichten in der Python-403.
3. **SRP-Verifier:** `make_verifier` schreibt den Namen konsequent klein (`luanti_auth.py:46`), identisch zur Mod-Seite (x enthält `lower(name)`); Salz kommt aus `secrets.token_bytes(16)`, keine schwache Zufallsquelle im gesamten Phase-3-Code (`random` kommt nicht vor). Golden Vector wörtlich im Test.
4. **Welt-Mod:** `MOD_INIT_LUA` ist reines ASCII (Test `test_lua_source_is_ascii_without_dashes`), Kindertexte als Dezimal-Escapes. Spielernamen gelangen nur über `render_access_file` in die Zugangsdatei, und die wirft bei jedem Namen oder Verifier außerhalb der strikten Form `ValueError` statt still zu überspringen (`access_mod.py:171-185`): keine Injection über Spielernamen in Datei oder Lua. Das Lua-Parsing verlangt Kopf, Schlusszeile und die exakte Zeilenform, halbe Dateien lassen den alten Stand stehen.
5. **Keine Klartext-Passwörter in SQLite, Logs, Fehlern:** Schema 3 speichert nur `nc_user`, `player_name`, `rotation` (Test `test_players_have_no_password_column`); die Leck-Tests (`test_invites_api.py:178-235, 383-456`) prüfen Logs auf DEBUG und Fehler-Bodies über alle Fehlerpfade. Fehlerantworten nutzen feste deutsche Texte (`invites.py:_http_error`, Ausnahme siehe IN-02).
6. **Frontend:** Kein `v-html`; alle Nutzerwerte per Textinterpolation; das einzige `iconSvg` ist eine feste Konstante (`InviteDialog.vue:72`). Passwörter verdeckt bis "Anzeigen" (ConnectionCard, PlayerManager), `NcFormBoxCopyButton` fürs Passwort erst nach dem Aufdecken, Dialoge halten Passwörter nur im Komponenten-Speicher.
7. **Lock-Regel:** `_ensure_fingerprint` läuft in allen sechs Aufrufpfaden (invite_user/group, revoke, sync_world, rotate/rename, sync_all, my_worlds) vor bzw. außerhalb von `worlds.mutation()`; `reprovision_all` nimmt die Sperre selbst und ruft `_ensure_fingerprint` nie; `sync_all` und `my_worlds` nutzen durchgehend `try_mutation()`/`blocking=False` (Deadlock-Tests mit `anyio.fail_after` vorhanden). Kein reentranter Pfad gefunden.

Hauptbefunde: Eine Nebenläufigkeits-Lücke, in der die "keep"-Regel des Abgleichs einen soeben ausgesprochenen Widerruf still wiederherstellen kann (WR-01), und ein ignorierter Rückgabewert in `my_worlds`, durch den Kinder nach einem Geheimniswechsel vorübergehend ein noch nicht gültiges Passwort angezeigt bekommen und sich damit in die Fehlversuch-Sperre tippen können (WR-02). Dazu sieben Hinweise ohne akuten Handlungsdruck.

Bekannte, bewusst offene Punkte (Live-Join mit echtem Client, Kick A7, Neuinstallations-Randfall, npm audit, .gitattributes) wurden nicht als Findings gewertet.

## Warnings

### WR-01: "keep"-Regel kann einen gerade ausgesprochenen Widerruf bei paralleler Gruppen-Einladung still rückgängig machen

**File:** `src/gameworld/access/service.py:469-478` (Zusammenspiel mit `revoke`, Zeilen 177-187)
**Issue:** `_apply_sync` behandelt Einladungsschlüssel, die beim Auflösen außerhalb der Sperre noch nicht bekannt waren, konservativ: Bei einem unaufgelösten **Gruppen**-Schlüssel wird der komplette aktuelle `world_access` der Welt in `keep` übernommen (`keep |= set(self._store.world_access(world_id))`). Ablauf: Verwalter A ruft `revoke(W, user, U)` auf; während A noch bei Nextcloud auflöst, schließt Verwalter B (oder ein zweiter Tab) `invite_group(W, G)` ab. Unter der Sperre enthält `current_keys` jetzt `(group, G)`, das in A's `resolution.resolved` fehlt, also wandert der gesamte Bestand inklusive des soeben widerrufenen Kontos U in `keep`. Ergebnis: Der Widerruf wird mit `applied: true` beantwortet, U behält aber Zugang (Datei und DB), bis der nächste Abgleich läuft (Verwalter-Besuch, gedrosselt auf 60 s, oder die nächste Einladungsänderung). Für eine Sicherheitsaktion ist "still wiederhergestellt und als Erfolg gemeldet" das falsche Verhalten, auch wenn das Fenster klein ist und die Spielerliste im Dialog den Zustand sichtbar machen würde.
**Fix:** Nach `change()` prüfen, ob `current_keys - resolution.resolved` nicht leer ist, und dann nicht pauschal alles behalten, sondern den Abgleich erzwingen, zum Beispiel:
```python
unresolved = current_keys - resolution.resolved
if unresolved:
    SYNC_STATE.last = None  # Drossel aufheben: der naechste Verwalter-Besuch synct sofort
```
plus beim Widerruf das widerrufene Ziel hart ausschließen (`keep.discard(target)` für `kind == "user"` bzw. die Mitglieder der widerrufenen Gruppe nie über `keep` zurückholen, soweit sie nicht aus einer aufgelösten Quelle stammen). Alternativ: bei unaufgelösten Schlüsseln `applied: false` melden und einen sofortigen `sync_world` anstoßen. Einen Test mit dem Interleaving (revoke liest Einladungen, invite_group committet, revoke wendet an) ergänzen.

### WR-02: my_worlds ignoriert den Rückgabewert von _ensure_fingerprint und zeigt nach Geheimniswechsel ein noch nicht gültiges Passwort an

**File:** `src/gameworld/access/service.py:311-320` (zusammen mit `_ensure_fingerprint`, Zeilen 378-393)
**Issue:** `_ensure_fingerprint(secret, blocking=False)` liefert `False`, wenn das Geheimnis gewechselt hat, die Neuprovisionierung aber wegen belegter Welt-Sperre übersprungen wurde. `my_worlds` wertet das nicht aus und rechnet die Passwörter in `_my_worlds_sync` trotzdem aus dem **neuen** Geheimnis, während alle Welten noch die **alten** Verifier tragen. Das Kind sieht also ein Passwort, das (noch) nicht funktioniert. Hält eine Elternaktion die Sperre länger (VoxeLibre-Erzeugung, Image-Pull: Sekunden bis Minuten), gilt das für jede Poll-Antwort in diesem Zeitraum. Folgeproblem: Tippt das Kind das angezeigte Passwort mehrfach ein, zählt der Welt-Mod das als Fehlversuche und sperrt den Namen nach 5 Versuchen für 10 Minuten. Der Fall ist auf den Neuinstallations-Randfall beschränkt und heilt sich beim nächsten erfolgreichen Abruf, bleibt aber eine falsche Anzeige von Zugangsdaten.
**Fix:** Rückgabewert auswerten und die betroffene Antwort zurückhalten, zum Beispiel:
```python
if not await self._ensure_fingerprint(secret, blocking=False):
    # Verifier passen noch nicht zum neuen Geheimnis: lieber kurz leer/503
    # als ein nicht funktionierendes Passwort anzeigen.
    raise SecretUnavailableError(MSG_UNAVAILABLE)
```
(oder ein eigenes "gerade in Arbeit"-Signal, das `/api/my/worlds` als 503 mit dem bestehenden festen Text beantwortet; der 5-s-Poll versucht es ohnehin erneut). Test: Geheimnis tauschen, Sperre halten, `my_worlds` darf kein Passwort aus dem neuen Geheimnis liefern.

## Info

### IN-01: HMAC-Nachricht `nc_user:rotation` ohne eindeutige Trennung

**File:** `src/gameworld/access/accounts.py:69`
**Issue:** `f"{nc_user}:{rotation}"` ist nicht injektiv: `("a:1", 0)` und `("a", 10)` ergäben dieselbe Nachricht. Heute nicht ausnutzbar, weil Nextcloud-Konto-IDs keinen Doppelpunkt erlauben; die Sicherheit hängt damit aber an einer fremden Invariante. Auch `FINGERPRINT_MESSAGE = b"gameworld:fingerprint"` lebt nur davon, dass "fingerprint" keine Zahl ist.
**Fix:** Längenpräfix oder ein in Konto-IDs unmögliches Trennzeichen verwenden, etwa `hmac.new(secret, len(nc_user).to_bytes(2, "big") + nc_user.encode() + rotation.to_bytes(4, "big"), ...)`. Achtung: ändert alle Passwörter, also nur zusammen mit einem bewussten Rotations-/Migrationsschritt oder vor dem ersten Release.

### IN-02: Breiter ValueError-Fang kann nicht-feste Fehlertexte als 422-Detail ausliefern

**File:** `src/gameworld/api/invites.py:180-182,188`
**Issue:** `_http_error` gibt für jeden `ValueError` `str(exc)` als Detail zurück. Gedacht ist das für `validate_player_name` (fester deutscher Text), `_PLAYER_ERRORS` fängt aber jeden `ValueError` aus `rotate_password`/`rename_player`, zum Beispiel einen englischen `int()`-Fehler bei einer von Hand beschädigten DB-Zeile oder den `render_access_file`-Text. Das verletzt die eigene Regel "nur feste deutsche Texte" (kein Datenleck, nur Konsistenz).
**Fix:** Statt `ValueError` einen eigenen Fehlertyp (`InvalidPlayerNameError(ValueError)`) in `validate_player_name` werfen und nur diesen auf 422 mit `str(exc)` abbilden; restliche `ValueError` auf 500 mit fester Meldung.

### IN-03: `AccessService.sync_world` wird in der Produktion nicht aufgerufen

**File:** `src/gameworld/access/service.py:189-195`
**Issue:** `sync_world` hat in `src/` keinen Aufrufer (nur Tests nutzen es); die API läuft über `sync_all`. Entweder toter Produktionscode oder bewusst vorgehaltene Schnittstelle (etwa für einen "Jetzt abgleichen"-Knopf).
**Fix:** Entweder entfernen oder per Docstring als bewusst vorgehaltene API markieren, damit vulture-/Review-Läufe nicht erneut stolpern.

### IN-04: CASE_HINT verrät Unauthentifizierten die exakte Schreibweise eines eingeladenen Spielernamens

**File:** `src/gameworld/provisioner/access_mod.py:106-111,141-144`
**Issue:** Wer im LAN einen Join mit einer Groß-/Kleinschreibungs-Variante probiert ("mia"), bekommt vor jeder Anmeldung "Achte auf Groß- und Kleinschreibung: Mia" zurück und kann so eingeladene Namen bestätigen und deren kanonische Schreibweise lernen (Namens-Enumeration). Das ist der bewusste A5-UX-Kompromiss, und Luantis eingebaute Prüfung leakt Ähnliches auf Englisch; es bleibt aber eine kleine Informationspreisgabe an Unauthentifizierte.
**Fix:** Keine Codeänderung nötig; im Threat-Model/der Doku als akzeptiert festhalten. Härtere Variante: den Hinweis ohne den Namen formulieren ("Achte auf Groß- und Kleinschreibung deines Spielernamens.").

### IN-05: Fehlversuch-Sperre erlaubt gezieltes Aussperren eines eingeladenen Namens aus dem LAN

**File:** `src/gameworld/provisioner/access_mod.py:124-135`
**Issue:** Jeder im Heimnetz kann mit 5 falschen Passwörtern den Namen eines Kindes für 10 Minuten sperren und das beliebig wiederholen (Dauer-DoS auf den Login). Das ist der dokumentierte Trade-off gegen Online-Raten (Research Pattern 6) und im Heimnetz-Szenario vertretbar.
**Fix:** Keine Änderung nötig; für Phase 4 optional per Quell-IP statt (oder zusätzlich zu) per Name sperren, die IP dabei weiterhin nie persistieren.

### IN-06: Abnahmeskripte übergeben Spielpasswörter als Prozessargumente

**File:** `scripts/dev/acceptance-phase3.sh:229` (Funktion `probe`), `tests/e2e/luanti_probe.py:229`
**Issue:** `uv run python -m tests.e2e.luanti_probe HOST PORT NAME PASSWORT` macht das Passwort während des Laufs in der Prozessliste sichtbar (und je nach Shell in der History). Auf der Single-User-Dev-Maschine mit Wegwerfkonten unkritisch, die Skripte achten sonst konsequent auf Passwortfreiheit der Ausgaben.
**Fix:** Optional: Prober um `--password-stdin` ergänzen und die Skripte das Passwort über stdin reichen.

### IN-07: Heimnetz-Heuristik in JoinHostSettings mit Fehlklassifikationen

**File:** `frontend/src/components/JoinHostSettings.vue:47,72-85`
**Issue:** `classify()` stuft `fritz.box` (ohne Subdomain, `endsWith('.fritz.box')` greift nicht) als Internetadresse ein und zeigt die UDP-Warnung, obwohl es ein typischer Heimnetz-Name ist; umgekehrt bekommt eine öffentliche IPv6 (enthält keinen Punkt) gar keine Warnung. Rein kosmetisch, die Validierung im Backend ist davon unabhängig.
**Fix:** `host === 'fritz.box'` (und analog `home.arpa`) in die Heimnetz-Liste aufnehmen; für IPv6 optional `classify` um eine ULA-Prüfung (`fc00::/7` heißt Heimnetz, sonst Warnung) erweitern.

---

_Reviewed: 2026-10-20T04:50:33Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
