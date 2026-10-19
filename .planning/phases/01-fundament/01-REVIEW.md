---
phase: 01-fundament
reviewed: 2026-10-19T14:30:38Z
depth: standard
files_reviewed: 25
files_reviewed_list:
  - src/gameworld/config.py
  - src/gameworld/main.py
  - src/gameworld/lifecycle.py
  - src/gameworld/api/worlds.py
  - src/gameworld/api/setup_check.py
  - src/gameworld/provisioner/client.py
  - src/gameworld/provisioner/spec.py
  - src/gameworld/provisioner/luanti_conf.py
  - src/gameworld/provisioner/archive.py
  - src/gameworld/provisioner/setup_check.py
  - src/gameworld/worlds/store.py
  - src/gameworld/worlds/ports.py
  - src/gameworld/worlds/service.py
  - src/gameworld/__init__.py
  - src/gameworld/api/__init__.py
  - src/gameworld/provisioner/__init__.py
  - src/gameworld/worlds/__init__.py
  - frontend/src/main.js
  - frontend/src/api.js
  - frontend/src/App.vue
  - frontend/src/components/SetupCheck.vue
  - frontend/vite.config.js
  - appinfo/info.xml
  - scripts/dev/compose.yaml
  - scripts/dev/register-exapp.sh
findings:
  critical: 1
  warning: 4
  info: 5
  total: 10
status: fixed
fixed_at: 2026-10-19
fixed:
  critical: 1
  warning: 4
  info: 0
fix_commits:
  CR-01: 12c49a3
  WR-01: 3e95c87
  WR-02: 201e67a
  WR-03: 70cb094
  WR-04: e5c560a
---

# Phase 01: Code-Review-Bericht

**Reviewed:** 2026-10-19T14:30:38Z
**Depth:** standard
**Files Reviewed:** 25 (zusätzlich gesichtet: scripts/dev/smoke.sh, scripts/dev/acceptance-phase1.sh)
**Status:** findings

## Summary

Gesamteindruck: Die sicherheitskritischen Kernpfade sind solide gebaut. Konkret geprüft und in Ordnung: docker-py nur unter provisioner/, jede Mutation über `_owned()` mit Label-Filter plus Nachprüfung am Ergebnis, gehärtete Container-Spec ohne Nutzereingaben, Weltname per `normalize_world_name` gegen conf-Key-Injection abgesichert (Steuerzeichen vor Whitespace-Normalisierung geprüft), Tar wird nur gebaut (nie extrahiert), Zip-Quelle SHA256-gepinnt mit `_safe_relative`-Pfadprüfung, Weltschlüssel taucht in keiner Logzeile und nie in der Liste auf, XSS im Frontend durch durchgängige Vue-Text-Interpolation ausgeschlossen, Shell-Skripte mit `set -eu`, sauberem Quoting und EXIT-Traps.

Trotzdem gibt es Defekte. Der schwerste: Die Port-Kollisions-Saga kann eine Welt in einen Zustand bringen (Volume vorhanden, Container weg), aus dem es keinen Weg zurück gibt; Start und Stop antworten dann mit 404 "Diese Welt gibt es nicht (mehr)", obwohl die Welt in der Liste steht, und der einzige Ausweg im Produkt ist das Löschen samt Weltdaten.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: Welt ohne Container ist unrettbar; eigener Fehlerpfad der Saga erzeugt genau diesen Zustand

**Status:** fixed (12c49a3). `_launch` erzeugt einen fehlenden Container aus dem Volume neu (einmal pro Start, weiter in der Port-Saga); `_stop_world_sync` behandelt einen fehlenden Container als bereits gestoppt. Fünf neue Tests decken Volume-ohne-Container (Start erzeugt neu, Stop ist No-op, API antwortet 200) und den Saga-Fehlerpfad ab.

**File:** `src/gameworld/worlds/service.py:125-151` (`_launch`), `src/gameworld/worlds/service.py:225-235` (`_stop_world_sync`), `src/gameworld/provisioner/client.py:136-156` (`_owned`)
**Issue:** `_launch` entfernt bei einer Port-Kollision zuerst den Container (`remove_world(..., keep_volume=True)`, Zeile 141) und erzeugt ihn danach neu. Scheitert zwischen diesen Schritten `allocate_port` (NoFreePortError, Zeile 143-145), `ensure_image` oder `create_world_container` (z. B. Proxy kurz weg, DockerUnavailableError), bleibt die Welt mit Volume, aber ohne Container zurück. Ab dann:
- POST `/worlds/{id}/start` läuft über `start_world` in `_owned`, das `WorldNotFoundError` wirft; die Ausnahme ist kein `PortInUseError`, verlässt `_launch` ungefangen und wird in der API zu **404 "Diese Welt gibt es nicht (mehr)"**, obwohl die Welt in der Liste mit Status "Container fehlt" steht und die UI einen Starten-Button anbietet.
- POST `/worlds/{id}/stop` endet aus demselben Grund mit 404 und setzt die Zeile zusätzlich auf `op_state=failed`.
- Der einzige funktionierende Weg im Produkt ist DELETE, und der entfernt das Volume mit der gebauten Welt der Kinder. Der Fehlerpfad der App erzwingt also im Ergebnis Datenvernichtung als "Reparatur".

Derselbe Endzustand entsteht auch ohne Saga, wenn der Container außerhalb der App verschwindet (docker rm, Prune durch den Admin). `remove_world` toleriert den fehlenden Container beim Löschen bewusst (01-03 Deviation 2), Start und Stop tun das nicht.
**Fix:**
```python
# service.py, _launch: fehlenden Container aus dem Volume neu erzeugen
try:
    self._provisioner.start_world(row.id)
    return
except WorldNotFoundError:
    LOG.warning("Welt %s: Container fehlt, erzeuge ihn aus dem Volume neu", row.id)
    self._provisioner.ensure_image()
    self._provisioner.create_world_container(row.id, row.port, _payload(row), reuse_volume=True)
    self._provisioner.start_world(row.id)
    return
except PortInUseError as exc:
    ...
```
(In die bestehende Versuchsschleife integrieren, damit auch die Neuerzeugung die Port-Saga durchläuft.) Zusätzlich in `_stop_world_sync` ein `WorldNotFoundError` des Provisioners als Erfolg behandeln, wenn die DB-Zeile existiert: ein fehlender Container ist bereits gestoppt. Unit-Test für den Zustand "Volume ohne Container" ergänzen (Start erzeugt neu, Stop ist no-op, Löschen räumt auf).

## Warnings

### WR-01: Ungültige Umgebung verhindert den App-Start; der Setup-Check-Befund "config" ist in der Praxis unerreichbar

**Status:** fixed (3e95c87). Der Lifespan toleriert Konfigurationsfehler; `get_service` bildet sie auf 503 mit deutscher Meldung ab; ein nicht anlegbares `APP_PERSISTENT_STORAGE` wird in `load_settings` zum ValueError (gleiches Muster). Neue Tests in tests/test_startup_config.py, inklusive Lifespan mit ungültigem `GAMEWORLD_PORT_RANGE`.

**File:** `src/gameworld/main.py:29`, `src/gameworld/api/setup_check.py:35-39`
**Issue:** `lifespan` ruft `worlds.get_service()` beim Start auf. Bei ungültigem `GAMEWORLD_PORT_RANGE` wirft `load_settings()` dort ValueError, der Lifespan bricht ab und uvicorn startet die App nicht. Der in 01-04 ausdrücklich eingebaute Pfad "GET /api/setup-check antwortet immer 200, bei ungültiger Umgebung mit Item `config`" kann so nie greifen: Der Prozess, der die Meldung liefern soll, kommt gar nicht hoch. Der Admin sieht statt der deutschen Handlungsanweisung nur eine nicht antwortende ExApp (Heartbeat tot). Die Tests prüfen die Route isoliert (ohne Lifespan) und verdecken den Widerspruch. Gleiches Muster bei nicht beschreibbarem `APP_PERSISTENT_STORAGE` (`storage.mkdir` in `load_settings`, config.py:42).
**Fix:** Im Lifespan Konfigurationsfehler tolerieren statt abzubrechen, z. B.:
```python
try:
    await anyio.to_thread.run_sync(worlds.get_service)
except ValueError:
    LOG.exception("Ungültige Konfiguration; /api/setup-check zeigt den Befund")
```
`get_service()` liefert dann pro Request weiterhin den Fehler; die Welt-Routen sollten ValueError dabei auf 503 mit der config.py-Meldung abbilden, damit kein 500 entsteht.

### WR-02: start_world verschluckt NotFound und macht daraus 500 statt 404

**Status:** fixed (201e67a). Eigener `except docker.errors.NotFound: raise`-Zweig vor dem APIError-Zweig; `_guarded` bildet NotFound wieder auf WorldNotFoundError ab (404, und seit CR-01 greift die Neuerzeugung). Test test_vanished_container_on_start_is_not_found ergänzt.

**File:** `src/gameworld/provisioner/client.py:199-203`
**Issue:** `docker.errors.NotFound` erbt von `APIError`. Verschwindet der Container zwischen `_owned()` und `container.start()` (Race mit Löschen oder Prune), fängt der innere `except docker.errors.APIError`-Zweig das NotFound, erkennt kein Port-Konflikt-Muster und wirft `ProvisionerError` ("Docker hat den Start der Welt abgelehnt: ..."). `_http_error` macht daraus 500 statt des korrekten 404; der dafür gebaute Zweig in `_guarded` (Zeile 111-112) wird nie erreicht, weil die Ausnahme vorher umverpackt wurde.
**Fix:**
```python
except docker.errors.NotFound:
    raise  # _guarded bildet das auf WorldNotFoundError ab
except docker.errors.APIError as exc:
    ...
```

### WR-03: Frontend verliert die deutsche Validierungsmeldung bei ungültigem Weltnamen

**Status:** fixed (70cb094). `errorText` wertet 422-Detail-Listen aus und zeigt `detail[0].msg` ohne Pydantic-Präfix; der tote `except ValueError`-Zweig in create_world ist entfernt; Bundle neu gebaut. Backend-Test sichert zu, dass die Detail-Liste die deutsche Namensmeldung trägt.

**File:** `frontend/src/App.vue:148-154` (`errorText`), `src/gameworld/api/worlds.py:50-54, 86-87`
**Issue:** Die Namensprüfung läuft über `AfterValidator(normalize_world_name)` im Pydantic-Modell. Ein ungültiger Name (z. B. "Mias & Leos Welt", `&` ist nicht erlaubt) erzeugt dadurch einen FastAPI-RequestValidationError: 422 mit `detail` als **Liste** von Fehlerobjekten. `errorText` akzeptiert nur String-Details und zeigt dann den generischen Text "Die Anfrage an Gameworld ist fehlgeschlagen." Die sorgfältig formulierte Meldung NAME_ERROR ("Der Weltname darf 1 bis 40 Zeichen ...") erreicht Eltern nie. Der `except ValueError`-Zweig in `create_world` (worlds.py:86-87), der die Meldung als String liefern würde, ist toter Code, weil der Service nur noch bereits normalisierte Namen sieht (normalize ist idempotent).
**Fix:** Entweder im Frontend Listen-Details auswerten:
```js
if (Array.isArray(detail) && typeof detail[0]?.msg === 'string') {
    return detail[0].msg.replace(/^Value error, /, '')
}
```
oder die Validierung aus dem Pydantic-Modell in den Handler verlegen (nur `max_length` im Modell lassen), damit der bestehende 422-Zweig mit String-Detail wieder greift.

### WR-04: Dev-Nextcloud mit festem Admin-Passwort auf allen Interfaces erreichbar

**Status:** fixed (e5c560a). Port-Bindung auf `127.0.0.1:${GAMEWORLD_NC_PORT:-8091}:80` geändert, Stack neu gestartet (Bindung live geprüft: `127.0.0.1:8091->80/tcp`), Registrierung und Smoke-Test danach grün.

**File:** `scripts/dev/compose.yaml:9-14`
**Issue:** Der Proxy-Port ist vorbildlich auf 127.0.0.1 gebunden (Zeile 50), die Dev-Nextcloud aber nicht: `"${GAMEWORLD_NC_PORT:-8091}:80"` bindet 0.0.0.0, und das Admin-Passwort `gameworld-dev-admin` steht im Repository. Jeder im selben LAN (Entwickler-Laptop im Fremdnetz) kann sich als Admin anmelden und über die registrierte ExApp signierte Aufrufe auslösen, also Container auf dem Entwicklungsrechner erzeugen, starten und löschen. Für ein Projekt, dessen Kern Kindersicherheit ist, sollte auch der Dev-Stack dem eigenen Maßstab folgen.
**Fix:**
```yaml
ports:
  - "127.0.0.1:${GAMEWORLD_NC_PORT:-8091}:80"
```
(Playwright, curl und register-exapp.sh nutzen ohnehin localhost.)

## Info

Die Info-Befunde IN-01 bis IN-05 sind bewusst offen gelassen und für das Phasen-Audit dokumentiert (Fix-Scope: Critical und Warning).

### IN-01: Volume-Aufräumen beim Löschen ohne force, Race mit gerade entferntem Container

**File:** `src/gameworld/provisioner/client.py:223-225`
**Issue:** `remove_world` entfernt den Container mit `force=True` und direkt danach das Volume ohne `force`. Unmittelbar nach dem Force-Remove eines laufenden Containers kann der Daemon das Volume noch kurz als "in use" melden (409); daraus wird ProvisionerError und ein 500 beim Löschen, obwohl ein Wiederholen sofort klappt. Im Fehlerpfad von `create_world_container` (Zeile 190) wird dagegen `remove(force=True)` benutzt.
**Fix:** `remove(force=True)` auch in `remove_world` oder ein kurzer Retry auf 409.

### IN-02: Weltschlüssel liegt im Klartext in der SQLite

**File:** `src/gameworld/worlds/store.py:27`, `src/gameworld/worlds/service.py:73`
**Issue:** `world_key` wird unverschlüsselt gespeichert. Das ist für die Saga notwendig (minetest.conf muss bei Neuerzeugung identisch gerendert werden) und das Bedrohungsmodell deckt lokale Dateizugriffe ab, aber ein Backup von `APP_PERSISTENT_STORAGE` enthält damit alle Beitrittsschlüssel.
**Fix:** Im Threat Model bzw. Phasen-Audit als bewusste Entscheidung festhalten; für spätere Phasen prüfen, ob der Schlüssel aus der conf im Volume statt aus der DB gelesen werden kann.

### IN-03: Setup-Check meldet Programmfehler als "Proxy nicht erreichbar", ohne zu loggen

**File:** `src/gameworld/provisioner/setup_check.py:249-258`
**Issue:** Der Catch-all in `run_setup_check` bildet jeden unerwarteten Fehler auf das Item `reachable` mit der Meldung "Gameworld erreicht den Docker-Proxy ... nicht" ab und protokolliert nichts. Ein Bug im Checker würde Admins dauerhaft auf eine falsche Fährte (Proxy prüfen) schicken und wäre auch im Log unsichtbar.
**Fix:** `LOG.exception("Setup-Check abgebrochen")` im Except-Zweig ergänzen und eine neutrale Meldung ("Der Setup-Check ist unerwartet fehlgeschlagen, Details im Log") statt der Unreachable-Meldung liefern.

### IN-04: APP-Secret steht während der Registrierung auf der Kommandozeile

**File:** `scripts/dev/register-exapp.sh:310-312`
**Issue:** Das pro Lauf erzeugte Secret wird als Teil von `--json-info` an `occ app_api:app:register` übergeben und ist damit für die Dauer des Aufrufs in der Prozessliste des Hosts und des Containers sichtbar. Nur Dev-Umgebung, Secret-Datei selbst ist korrekt mit umask 077 geschrieben.
**Fix:** Hinnehmbar für den Dev-Stack; alternativ JSON über stdin bzw. eine temporäre Datei mit 0600 übergeben, falls occ das erlaubt.

### IN-05: Unerwartete Ausnahmen beim Erzeugen lassen Zeile in op_state "creating" und Container stehen

**File:** `src/gameworld/worlds/service.py:183-198`
**Issue:** Der Aufräum-Zweig in `_create_world_sync` fängt nur `ProvisionerError`. Eine andere Ausnahme (z. B. sqlite3.OperationalError bei `update_world`, Zeile 149 in `_launch`) ließe einen laufenden Container plus eine Zeile in `op_state="creating"` zurück und erreicht die API als generischer 500. Sehr unwahrscheinlich, aber der Zustand "creating" ist danach weder in der UI noch im Statusmodell vorgesehen.
**Fix:** Aufräumen und `_fail` in einem `except Exception`-Zweig ausführen und die Ausnahme weiterwerfen; nur die HTTP-Abbildung bleibt auf ProvisionerError beschränkt.

---

_Reviewed: 2026-10-19T14:30:38Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
