---
phase: 02-one-click-welten
reviewed: 2026-10-19T20:37:55Z
depth: standard
files_reviewed: 22
files_reviewed_list:
  - src/gameworld/provisioner/presets.py
  - src/gameworld/provisioner/status_mod.py
  - src/gameworld/provisioner/spec.py
  - src/gameworld/provisioner/client.py
  - src/gameworld/provisioner/archive.py
  - src/gameworld/provisioner/luanti_conf.py
  - src/gameworld/worlds/store.py
  - src/gameworld/worlds/service.py
  - src/gameworld/worlds/status.py
  - src/gameworld/worlds/reconciler.py
  - src/gameworld/worlds/ports.py
  - src/gameworld/api/worlds.py
  - src/gameworld/main.py
  - frontend/src/App.vue
  - frontend/src/api.js
  - frontend/src/components/SetupCheck.vue
  - scripts/fetch-games.sh
  - scripts/dev/register-exapp.sh
  - scripts/dev/acceptance-phase2.sh
  - scripts/dev/acceptance-phase1.sh
  - scripts/dev/compose.yaml
  - vendor/games/SHA256SUMS
findings:
  critical: 1
  warning: 5
  info: 5
  total: 11
status: issues_found
---

# Phase 02: Code-Review-Bericht

**Reviewed:** 2026-10-19T20:37:55Z
**Depth:** standard
**Files Reviewed:** 22 (Tests unter tests/ nur auf Zuverlässigkeit gesichtet, ohne Befund)
**Status:** issues_found

## Summary

Geprüft wurde der Phase-2-Bereich 6adcc27..HEAD. In Ordnung und konkret nachvollzogen:

- Preset-Validierung nur gegen die feste Registry (Pydantic-AfterValidator plus `get_preset` im Dienst), kein Nutzerwert erreicht conf oder Spec.
- `parse_players`: `fullmatch` auf `[A-Za-z0-9_-]{1,20}`, Ersatzzeichen bei kaputtem UTF-8, Obergrenze 64 Namen; Status-Datei auf 4096 Bytes Inhalt und 64 KiB Tar-Strom gekappt.
- Tar wird nur gebaut, nie extrahiert; `_safe_relative` gegen Traversal, conf root-eigen 0444, Rest uid 30000.
- `fetch-games.sh`: TLS erzwungen, Hash vor `mv`, `.part` wird bei Abweichung gelöscht, `fail` im Pipe-Subshell beendet dank `set -e` das Skript.
- `_owned`-Filter plus Nachprüfung in allen neuen Lesewegen (Status-Datei, Stats), Lese-Retry nur in `_read`, nie für Mutationen.
- Cache-Generationszähler: Ein vor einer Mutation begonnener Listenabruf landet nie im Cache; `_copy` schützt die Spielerlisten.
- Reconciler-Task: `CancelledError` ist `BaseException` und beendet die Schleife sauber, alle anderen Fehler werden geloggt.
- Frontend: Polling mit `unmounted`-Sperre und einem einzigen Timer, Sequenzzähler gegen überholende Listenantworten, 422-Detaillisten lesbar, Spielernamen und Dialogtext nur per Textinterpolation (kein `v-html`).

Hauptbefund: Der Start-/Neustart-Pfad erzeugt bei fehlendem Container stillschweigend ein neues, leeres Volume, auch wenn die Weltdaten verloren sind. Das unterläuft die eigene Regel "Weltdaten fehlen, kann nur gelöscht werden". Daneben gibt es mehrere Fehlerpfade, in denen Nicht-`ProvisionerError`-Ausnahmen die Aufräum- bzw. Isolationslogik umgehen.

## Critical Issues

### CR-01: Starten/Neustarten ersetzt eine Welt mit verlorenen Daten still durch eine neue, leere Welt

**File:** `src/gameworld/worlds/service.py:309-320` (zusammen mit `src/gameworld/provisioner/client.py:279-307`, `src/gameworld/worlds/status.py:189,261-262`, `frontend/src/App.vue:112-117`)
**Issue:** Fehlt der Container, erzeugt `_launch` ihn mit `create_world_container(..., reuse_volume=True)` neu, ohne zu prüfen, ob das Volume noch existiert. Docker legt ein fehlendes benanntes Volume beim Mount automatisch leer an, `put_archive` spielt conf, world.mt und Spiel ein, Luanti generiert eine frische Karte, und `op_state` wird `ready`. Die Eltern sehen "Läuft" und halten es für ihre alte Welt; alles Gebaute ist weg, ohne jeden Hinweis.

Realistischer Weg dorthin auf einem Heimserver: `docker container prune` entfernt gestoppte Welt-Container, ein späteres `docker volume prune` (oder `docker system prune --volumes`) löscht die nun unreferenzierten Volumes. Konkret betroffen:
1. Welten, die der Boot-Abgleich korrekt als `MARK_DATA_MISSING` (op_state failed, "kann nur gelöscht werden") markiert hat: Das Dashboard zeigt bei Status `error` den Button "Starten" (`App.vue:112-117`), `_start_world_sync` lässt failed-Zeilen ungeprüft durch, und die Neuerzeugung läuft.
2. Gestoppte Welten (desired `stopped`): Der Boot-Abgleich prüft das Volume nur bei desired `running` (`needs_volume_check`), der periodische Abgleich nie. `derive_status` behauptet bei fehlendem Container pauschal `TEXT_MISSING` "Weltdaten vorhanden, Server fehlt. Starten stellt ihn wieder her.", ohne dass das Volume geprüft wurde.

Das widerspricht der Regeltabelle in `reconciler.py` und dem Elterntext `RECONCILE_DATA_MISSING`.
**Fix:** Die Volume-Prüfung in den Neuerzeugungspfad selbst legen, damit jeder Aufrufer (Start, Neustart, Boot-RECREATE) sie bekommt:
```python
except WorldNotFoundError:
    if recreated:
        raise
    if not self._provisioner.volume_exists(row.id):
        # Nie eine leere Welt unter altem Namen anlegen.
        raise ProvisionerError(RECONCILE_DATA_MISSING)
    recreated = True
    ...
```
Zusätzlich in `_start_world_sync`/`_restart_world_sync` Zeilen mit `last_error in {RECONCILE_DATA_MISSING, RECONCILE_INTERRUPTED}` mit 409 abweisen und im Frontend für diese Zustände nur "Löschen" anbieten. `TEXT_MISSING` erst nach erfolgter Volume-Prüfung verwenden oder neutral formulieren ("Server fehlt").

## Warnings

### WR-01: Nicht-ProvisionerError beim Erzeugen lässt eine "creating"-Zeile mit belegtem Port stehen

**File:** `src/gameworld/worlds/service.py:390-398` (Auslöser in `src/gameworld/provisioner/archive.py:201-233`)
**Issue:** Der Aufräumpfad `_discard_failed_create` greift nur bei `ProvisionerError`. `build_world_payload` kann aber `OSError` werfen (VoxeLibre spoolt rund 110 MB über `SpooledTemporaryFile` ins `/tmp` des ExApp-Containers; ENOSPC auf einem kleinen Heimserver ist realistisch), ebenso `tarfile`/`zipfile`-Fehler. Dann bleibt die Zeile bis zum nächsten Prozessneustart auf `op_state = creating`: Das Dashboard zeigt dauerhaft "Wird erstellt" samt Stopp/Neustart-Buttons, der UDP-Port bleibt reserviert, und `touched_docker` ist schon `True`, ein evtl. halb erzeugter Container bleibt liegen. Die API antwortet mit rohem 500. Gleiches Muster wie CR-01 aus Phase 1, nur über einen anderen Ausnahmetyp.
**Fix:** In `_create_world_sync` zusätzlich `except Exception as exc:` mit derselben Aufräumlogik (und einer neutralen deutschen Meldung im `ProvisionerError`) oder `build_world_payload` so kapseln, dass `OSError`, `tarfile.TarError` und `zipfile.BadZipFile` als `ProvisionerError("Die Weltdaten konnten nicht vorbereitet werden.")` ankommen.

### WR-02: Ein einzelner Weltfehler außerhalb von ProvisionerError blockiert den Boot-Abgleich dauerhaft

**File:** `src/gameworld/worlds/service.py:480-502`, `src/gameworld/worlds/reconciler.py:391-403`, `src/gameworld/worlds/service.py:109,129`
**Issue:** `_reconcile_row` fängt nur `ProvisionerError`. Ein `ValueError` aus `get_preset` (Zeile mit unbekannter Preset-ID, etwa nach Umbenennen/Entfernen eines Presets in einer späteren Version oder per Hand-Edit) oder ein `OSError` beim Payload-Bau bricht `_boot_reconcile_sync` komplett ab. `reconcile_forever` loggt und versucht alle 5 s erneut, `booted` wird nie `True`: Welten hinter der kaputten Zeile werden nie gestartet, der periodische Abgleich startet nie, und eine RECREATE-Zeile mit OSError baut alle 5 s erneut Payload und Container. Derselbe `ValueError` in `_view` (`get_preset(row.preset).title`) lässt außerdem `GET /api/worlds` für alle Welten mit 500 scheitern.
**Fix:** In `_reconcile_row` nach dem `DockerUnavailableError`-Zweig ein `except Exception` ergänzen, das loggt und die Zeile per `_fail` markiert. In `_view` für unbekannte Presets einen Fallback-Titel verwenden (`PRESETS.get(row.preset)` mit Titel "Unbekannte Spielart") statt zu werfen.

### WR-03: Lese-Retry wiederholt entgegen der Doku auch Verbindungs-Timeouts

**File:** `src/gameworld/provisioner/client.py:40-42,231-236`
**Issue:** `requests.exceptions.ConnectTimeout` erbt von `ConnectionError` und `Timeout` (geprüft: MRO `ConnectTimeout, ConnectionError, Timeout, ...`). `isinstance(exc.__cause__, RETRYABLE_ERRORS)` ist damit für Connect-Timeouts wahr, der Kommentar "Timeouts werden nicht wiederholt" stimmt nicht. Bei einem schwarzen-Loch-Proxy (Paketfilter, falscher Host) verdoppelt sich die Wartezeit auf bis zu 2 x 60 s, und zwar pro Leseaufruf: `GET /api/worlds` macht `list_managed` plus je Welt `read_status_file` und `memory_bytes`, ohne Lock und ohne Gesamtbudget. Der UI-Poll hängt dann minutenlang und belegt Threads aus dem anyio-Pool.
**Fix:**
```python
cause = exc.__cause__
if not isinstance(cause, RETRYABLE_ERRORS) or isinstance(cause, requests.exceptions.Timeout):
    raise
```
und einen Test mit `ConnectTimeout` ergänzen.

### WR-04: Status-Datei-Isolation fängt Tar-Fehler nicht ab

**File:** `src/gameworld/provisioner/client.py:140-152,415-422`, `src/gameworld/worlds/service.py:259-264`
**Issue:** `_first_member_content` kann `tarfile.ReadError`/`EOFError` werfen (gekappter Strom bei großen PAX-Köpfen, abgebrochener Transfer, Datei wird während `get_archive` per `safe_file_write` umbenannt). Diese Ausnahmen sind weder in `_guarded` gemappt noch in `_status_file` gefangen (nur `ProvisionerError`). Ein einzelner kaputter Lesevorgang einer Welt macht dann die gesamte Weltenliste zum 500er, entgegen der zugesagten Isolation pro Welt. Der Inhalt stammt aus einer von Lua-Code beschreibbaren Datei, ist also nicht vertrauenswürdig.
**Fix:** In `_read_status_file` die Tar-Auswertung kapseln:
```python
try:
    content = _first_member_content(_read_capped(stream))
except (tarfile.TarError, EOFError) as exc:
    raise ProvisionerError("Status-Datei der Welt ist nicht lesbar.") from exc
```

### WR-05: Unterbrochen erzeugte Welten lassen sich starten und gelten danach als "ready"

**File:** `src/gameworld/worlds/service.py:419-429,514-515`, `frontend/src/App.vue:112-117`
**Issue:** `MARK_INTERRUPTED` setzt "Bitte die Welt löschen und neu erstellen", der Container kann aber existieren und ein nur teilweise eingespieltes Tar enthalten (Abbruch mitten in `put_archive`). Das Dashboard bietet bei Status `error` "Starten" an; `_launch` startet den Container (er existiert, also keine Neuerzeugung mit vollständigem Payload), und `op_state` wird `ready` mit gelöschtem `last_error`. Ergebnis: Luanti mit unvollständigem Spiel stürzt ab oder läuft mit fehlenden Mods, die Fehlermeldung zum Abbruch ist weg.
**Fix:** Wie in CR-01: Start/Neustart für Zeilen mit `RECONCILE_INTERRUPTED` serverseitig ablehnen (409, deutsche Meldung) oder für diesen Zustand gezielt Container entfernen und mit vollständigem Payload neu erzeugen (`remove_world(keep_volume=True)` vor `_launch`). Im Frontend für diesen Zustand nur "Löschen" zeigen; dafür einen eigenen Statuscode statt Textvergleich in die API aufnehmen.

## Info

### IN-01: Keine Obergrenze für "Startet gerade"

**File:** `src/gameworld/worlds/status.py:234-243`
**Issue:** Schreibt der Status-Mod nie (Mod-Konflikt im Spiel, Lua-Fehler, Volume voll), bleibt eine laufende Schema-2-Welt für immer auf `starting`, obwohl gespielt werden kann; Eltern bekommen keinen Fehlerhinweis.
**Fix:** Nach z. B. 120 s seit `StartedAt` ohne frische Status-Datei einen eigenen Text ("Läuft, Spielerliste nicht verfügbar") liefern.

### IN-02: Stopp/Neustart werden während des Erzeugens angeboten

**File:** `frontend/src/App.vue:274-276`, `src/gameworld/worlds/status.py:257-258`
**Issue:** `op_state creating` ergibt Status `starting`, `isActive` zeigt dafür Stoppen/Neustarten. Ein Klick blockiert bis zum Ende des Erzeugens auf `_LOCK` (VoxeLibre: rund 110 MB `put_archive`) und kann am AppAPI-Proxy in einen Timeout laufen.
**Fix:** Aktionen sperren, solange `world.op_state === 'creating'`.

### IN-03: Abgebrochene Status-Datei-Antwort wird nicht explizit geschlossen

**File:** `src/gameworld/provisioner/client.py:125-137`
**Issue:** Bei einer Datei über 64 KiB schließt `_read_capped` nur den docker-py-Generator, nicht die darunterliegende `requests`-Response; die nicht ausgelesene Verbindung wird erst per GC freigegeben (vgl. Lehre "Transport-Response ohne Schließen = Leak").
**Fix:** Den Strom über `client.api.get_archive` mit eigenem Response-Handling lesen oder nach dem Kappen die Response explizit schließen; mindestens mit einem Test für eine übergroße Datei absichern.

### IN-04: `MARK_OOM` schreibt `last_error`, das nirgends angezeigt wird

**File:** `src/gameworld/worlds/service.py:510-511`, `src/gameworld/worlds/status.py:257-280`
**Issue:** Für `op_state ready` ignoriert `derive_status` `last_error`; der OOM-Text kommt ohnehin aus `container.oom_killed`. Der Schreibzugriff ist toter Zustand und kann nach einem späteren Neustart veraltet in der API stehen (bis zum nächsten erfolgreichen Start).
**Fix:** Aktion entfernen oder `last_error` in der Ansicht nur bei `op_state failed` ausliefern.

### IN-05: `fetch-games.sh` ohne Zeit- und Größenlimit

**File:** `scripts/fetch-games.sh:68`
**Issue:** `curl` ohne `--max-time`/`--max-filesize`: Ein hängender oder übergroßer Download blockiert Registrierung bzw. Image-Bau unbegrenzt; der Hash schützt nur die Integrität.
**Fix:** `--max-time 600 --max-filesize 200000000 --retry 2` ergänzen.

---

_Reviewed: 2026-10-19T20:37:55Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
