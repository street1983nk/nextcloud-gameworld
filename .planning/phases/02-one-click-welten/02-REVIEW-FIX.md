---
phase: 02-one-click-welten
fixed_at: 2026-10-19T20:58:31Z
review_path: .planning/phases/02-one-click-welten/02-REVIEW.md
iteration: 1
findings_in_scope: 6
fixed: 6
skipped: 0
status: all_fixed
---

# Phase 02: Code Review Fix Report

**Fixed at:** 2026-10-19T20:58:31Z
**Source review:** .planning/phases/02-one-click-welten/02-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 6 (CR-01, WR-01 bis WR-05; Info-Befunde IN-01 bis IN-05 bewusst außerhalb des Scopes, nur dokumentiert)
- Fixed: 6
- Skipped: 0

Jeder Fix ist ein eigener Commit mit Regressionstests im selben Commit. Für jeden neuen Test wurde eine Gegenprobe gemacht: Mit dem Code vor dem Fix scheitern die neuen Tests, mit dem Fix laufen sie durch.

## Fixed Issues

### CR-01: Starten/Neustarten ersetzt eine Welt mit verlorenen Daten still durch eine neue, leere Welt

**Files modified:** `src/gameworld/worlds/service.py`, `src/gameworld/api/worlds.py`, `src/gameworld/worlds/status.py`, `frontend/src/App.vue`, `tests/test_service_lifecycle.py`, `tests/test_reconciler.py`, `tests/test_status.py`
**Commit:** 611744e
**Status:** fixed: requires human verification (Logikänderung im Start-Pfad)
**Applied fix:** `_launch` prüft im Neuerzeugungszweig (Container fehlt) per `volume_exists`, ob die Weltdaten noch da sind. Fehlen sie, endet der Ablauf mit der neuen `DeleteOnlyError` (Unterklasse von `ProvisionerError`) und der Meldung "Die Weltdaten fehlen. Die Welt kann nur gelöscht werden."; damit greift die Prüfung für Start, Neustart und Boot-RECREATE gleichermaßen. `_start_world_sync` und `_restart_world_sync` weisen Zeilen im Zustand "nur löschen" vorab ab, ohne Docker oder die Zeile anzufassen. Die API bildet `DeleteOnlyError` auf 409 ab und liefert das neue Feld `delete_only` (bool) pro Welt, das Dashboard zeigt bei `delete_only` nur noch "Löschen" (kein Textvergleich im Frontend). `TEXT_MISSING` behauptet keine vorhandenen Weltdaten mehr: "Der Server der Welt fehlt. Starten stellt ihn wieder her, falls die Weltdaten noch da sind."
**Tests:** Start und Neustart bei fehlendem Volume (laufend und gestoppt, 4 Fälle) erzeugen nichts und markieren die Welt als "nur löschen"; Welt im Zustand "nur löschen" wird ohne Docker-Aufruf abgewiesen und lässt sich löschen; Gegenprobe: gewöhnlich fehlgeschlagene Welt bleibt startbar; API 409 für Start und Neustart plus `delete_only` in der Liste plus 204 beim Löschen; Boot-Abgleich, bei dem das Volume zwischen Prüfung und Neuerzeugung verschwindet. Bestehender Boot-RECREATE-Test erwartet jetzt die zweite Volume-Prüfung direkt vor der Neuerzeugung.

### WR-01: Nicht-ProvisionerError beim Erzeugen lässt eine "creating"-Zeile mit belegtem Port stehen

**Files modified:** `src/gameworld/worlds/service.py`, `tests/test_service_lifecycle.py`
**Commit:** 320136f
**Applied fix:** `_payload` bildet `OSError`, `tarfile.TarError` und `zipfile.BadZipFile` aus `build_world_payload` auf `ProvisionerError` ("Die Weltdaten konnten nicht vorbereitet werden. Bitte freien Speicherplatz auf dem Server prüfen und es erneut versuchen.") ab; das wirkt für Erzeugen, Start-Saga und Boot-Abgleich. `_create_world_sync` fängt zusätzlich jede andere Ausnahme, loggt sie mit Stacktrace und nimmt denselben Aufräumpfad `_discard_failed_create` wie beim Phase-1-Fix 12c49a3 (Meldung "Die Welt konnte nicht erstellt werden. Bitte es später erneut versuchen."). Keine Zeile bleibt mehr auf `creating`, der UDP-Port wird frei.
**Tests:** ENOSPC beim Payload-Bau hinterlässt keine Zeile und keinen belegten Port, Aufräumen samt Volume lief; unerwarteter `RuntimeError` wird aufgeräumt; scheitert dabei das Aufräumen, steht die Zeile auf `failed` statt `creating`; ENOSPC in der Start-Saga markiert die Welt als `failed`, sie bleibt startbar; API antwortet 500 mit deutscher Meldung statt rohem Fehler.

### WR-02: Ein einzelner Weltfehler außerhalb von ProvisionerError blockiert den Boot-Abgleich dauerhaft

**Files modified:** `src/gameworld/worlds/service.py`, `tests/test_reconciler.py`, `tests/test_service_lifecycle.py`
**Commit:** 4ae11c0
**Applied fix:** `_reconcile_row` fängt nach dem `DockerUnavailableError`-Zweig (der weiterhin den ganzen Abgleich wiederholt) jede weitere Ausnahme, loggt sie und markiert nur diese Welt als `failed` ("Die Welt konnte nach dem Neustart des Servers nicht wiederhergestellt werden."). `_view` holt das Preset per `PRESETS.get`: Bei unbekannter Spielart heißt der Titel "Unbekannte Spielart" und nur diese Welt steht auf Status `error` mit "Die Spielart dieser Welt kennt Gameworld nicht. Bitte Gameworld aktualisieren oder die Welt löschen." (Docker-unerreichbar behält Vorrang).
**Tests:** Boot-Abgleich mit unbekannter Spielart in Welt a startet Welt b trotzdem und meldet `True`; ein zweiter Abgleich fasst die kaputte Welt nicht erneut an; Liste zeigt die eine Welt als Fehler, die andere normal; `GET /api/worlds` antwortet 200 statt 500.

### WR-03: Lese-Retry wiederholt entgegen der Doku auch Verbindungs-Timeouts

**Files modified:** `src/gameworld/provisioner/client.py`, `tests/test_provisioner_errors.py`
**Commit:** 6f5c0a0
**Applied fix:** `_read` wiederholt nur noch, wenn die Ursache in `RETRYABLE_ERRORS` liegt und kein `requests.exceptions.Timeout` ist. Kommentar an `RETRYABLE_ERRORS` erklärt die MRO-Falle (`ConnectTimeout` erbt von `ConnectionError` und `Timeout`).
**Tests:** `ReadTimeout`, `ConnectTimeout` und `Timeout` führen zu genau einem Aufruf (vorher scheiterte der `ConnectTimeout`-Fall mit zwei Aufrufen); eigener Test hält die MRO-Annahme fest.

### WR-04: Status-Datei-Isolation fängt Tar-Fehler nicht ab

**Files modified:** `src/gameworld/provisioner/client.py`, `tests/test_provisioner_errors.py`
**Commit:** 36c7a34
**Applied fix:** `_read_status_file` kapselt die Tar-Auswertung und bildet `tarfile.TarError` und `EOFError` auf `ProvisionerError` ("Die Status-Datei der Welt ist nicht lesbar.") ab. `_status_file` im Dienst fängt ihn pro Welt, die Welt zeigt dann "Startet gerade", die Liste bleibt heil. Kein zweiter Leseversuch, da kein Verbindungsfehler.
**Tests:** Müll-Bytes, leerer Strom, abgeschnittenes Tar und ein auf 64 KiB gekappter großer PAX-Kopf ergeben jeweils `ProvisionerError` (nicht `DockerUnavailableError`); vor dem Fix scheiterten alle vier mit rohen Tar-Ausnahmen.

### WR-05: Unterbrochen erzeugte Welten lassen sich starten und gelten danach als "ready"

**Files modified:** `src/gameworld/worlds/service.py`, `src/gameworld/api/worlds.py`, `frontend/src/App.vue`, `tests/test_reconciler.py`, `tests/test_service_lifecycle.py`
**Commit:** e5772a6
**Status:** fixed: requires human verification (Logikänderung im Start-Pfad)
**Applied fix:** Teil des CR-01-Designs: `RECONCILE_INTERRUPTED` gehört zu `DELETE_ONLY_ERRORS`. Start und Neustart einer beim Erzeugen unterbrochenen Welt werden mit 409 abgewiesen, ohne den halb befüllten Container zu starten und ohne die Abbruchmeldung zu löschen; `delete_only` ist `true`, das Dashboard zeigt nur "Löschen". Der eigene Statuscode ist das API-Feld `delete_only`, kein Textvergleich im Frontend.
**Tests:** Nach Boot-Abgleich mit `creating`-Zeile weisen Start und Neustart ab, ohne `start`/`stop` am Container, Zeile bleibt `failed` mit Abbruchmeldung, Löschen entfernt Container und Volume; API 409 für Start und Neustart ohne Docker-Aufruf, `delete_only` in der Liste.

## Verification

- `GAMEWORLD_REQUIRE_DOCKER=1 uv run pytest -q -rs`: 363 passed (vorher 335; 28 neue Testfälle, nichts übersprungen)
- `uv run ruff check .`: All checks passed
- `uv run ruff format --check .`: 51 files already formatted
- `PYRIGHT_PYTHON_FORCE_VERSION=latest uv run pyright`: 0 errors, 0 warnings
- `uv run vulture`: keine Funde
- `cd frontend && npm run build`: Bundle neu erzeugt (gameworld-main.js, 434 kB)
- `sh scripts/dev/register-exapp.sh`: Backend auf Port 10040 mit neuem Code neu gestartet, ExApp registriert und aktiviert
- `sh scripts/dev/smoke.sh`: "Durchstich erfolgreich", alle Schritte ok (Erzeugen, gehärtete Container, Liste, Stop, Start, Löschen ohne Reste)

## Hinweise

- Der Boot-RECREATE-Pfad prüft das Volume jetzt zweimal (Abgleich und direkt vor der Neuerzeugung); das kostet einen zusätzlichen Lesezugriff nur bei fehlendem Container und schließt die Lücke zwischen beiden Zeitpunkten.
- Testisolation: Tests, die nach den Lifespan-Tests in `tests/test_reconciler.py` stehen, können `_LOCK` noch von einem abgebrochenen Abgleich-Thread belegt vorfinden (abandon_on_cancel). Die neuen Abgleichs-Tests stehen deshalb vor dem Abschnitt "Schleife". Vorbestehend, kein Befund dieses Fixlaufs.

---

_Fixed: 2026-10-19T20:58:31Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
