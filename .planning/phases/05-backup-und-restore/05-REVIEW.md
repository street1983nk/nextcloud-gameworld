---
phase: 05-backup-und-restore
reviewed: 2026-10-24T04:15:39Z
depth: deep
files_reviewed: 51
files_reviewed_list:
  - docs/install.md
  - frontend/src/api.js
  - frontend/src/backup.js
  - frontend/src/components/BackupSection.vue
  - frontend/src/views/ParentView.vue
  - frontend/tests/backup.check.mjs
  - scripts/dev/acceptance-phase3.sh
  - scripts/dev/acceptance-phase4.sh
  - scripts/dev/acceptance-phase4_1.sh
  - scripts/dev/acceptance-phase5.sh
  - src/gameworld/api/backups.py
  - src/gameworld/api/me.py
  - src/gameworld/api/worlds.py
  - src/gameworld/backup/__init__.py
  - src/gameworld/backup/archive.py
  - src/gameworld/backup/files.py
  - src/gameworld/backup/naming.py
  - src/gameworld/backup/service.py
  - src/gameworld/main.py
  - src/gameworld/nc.py
  - src/gameworld/notify/links.py
  - src/gameworld/notify/texts.py
  - src/gameworld/playtime/engine.py
  - src/gameworld/provisioner/archive.py
  - src/gameworld/provisioner/client.py
  - src/gameworld/provisioner/status_mod.py
  - src/gameworld/provisioner/time_mod.py
  - src/gameworld/worlds/reconciler.py
  - src/gameworld/worlds/service.py
  - src/gameworld/worlds/status.py
  - src/gameworld/worlds/store.py
  - tests/conftest.py
  - tests/e2e/backup_helpers.py
  - tests/e2e/test_backup_restore_e2e.py
  - tests/e2e/test_halt_e2e.py
  - tests/test_backup_archive.py
  - tests/test_backup_files.py
  - tests/test_backup_naming.py
  - tests/test_backup_service.py
  - tests/test_backups_api.py
  - tests/test_forget_account.py
  - tests/test_my_worlds.py
  - tests/test_nc.py
  - tests/test_playtime_engine.py
  - tests/test_provisioner_errors.py
  - tests/test_reconciler.py
  - tests/test_restore_api.py
  - tests/test_restore_service.py
  - tests/test_service_lifecycle.py
  - tests/test_status.py
  - tests/test_store.py
  - tests/test_time_mod.py
findings:
  critical: 0
  warning: 3
  info: 7
  total: 10
status: issues_found
fixed_at: 2026-10-24
fixes:
  WR-01: fc9747e
  WR-02: 3f7305a
  WR-03: 7d154ba
open: [IN-01, IN-02, IN-03, IN-04, IN-05, IN-06, IN-07]
---

# Phase 5: Code Review Report

**Reviewed:** 2026-10-24T04:15:39Z
**Depth:** deep
**Files Reviewed:** 51
**Status:** issues_found

## Summary

Deep Review von Backup und Restore (Phase 5) mit Fokus auf die sicherheitskritischen Pfade: Tar-Entpacken und -Filtern, Verwalter-Scoping (D-13), Halt/Stopp/Upload-Abläufe mit ihren Races, Ressourcenbudgets und Fehlerpfade. Querbezüge wurden über Modulgrenzen verfolgt (api/backups.py -> backup/service.py -> worlds/service.py -> provisioner/client.py, Zeit-Mod-Rendering, Boot-Abgleich, Frontend-Polling).

Gesamturteil: Der Kern ist ungewöhnlich sorgfältig gebaut. Die Angriffsfläche des Archiv-Pfads ist sauber geschlossen (Pfad-Traversal, Links, Geräte, zweites Manifest, Tar-/gzip-Bomben mit Ratio-Floor, Code-Dateien werden verworfen statt eingespielt), D-13 greift auf jedem Endpunkt vor jedem Docker- oder Files-Aufruf (per Test und Abnahme belegt), Logs enthalten keine Pfade, Namen oder Konten, der Ein-Job-Schutz und die Offline-Tickets decken Abbruch, Cancel und Prozess-Neustart ab. Die Tests sind substanziell (echte Negativtests, kein Schein-Gruen; die Fakes erzwingen z. B. "Snapshot nur bei gestopptem Container").

Kein Blocker gefunden. Drei Warnungen betreffen Luecken in sonst vorhandenen Schutzmechanismen: ein ungedeckelter Restore-Download, der das geprüfte Platzbudget aushebelt; eine Inkonsistenz zwischen Listen- und Restore-Pfad bei in Files umbenannten Sicherungen; und ein TOCTOU-Fenster im Upload, in dem die App im Fehlerfall eine fremde Datei loeschen koennte (D-08-Randfall).

**Update 2026-10-24:** Alle drei Warnungen sind behoben (WR-01 fc9747e, WR-02 3f7305a, WR-03 7d154ba), jeweils mit Negativtest; offen bleiben nur die Info-Hinweise IN-01 bis IN-07.

## Warnings

### WR-01: Restore-Download ohne Groessen-Deckel hebelt das Platzbudget aus

**Status:** fixed, Commit `fc9747e` (_CappedWriter deckelt den Download auf proof.size, Ueberschreiten endet sofort als RestoreTampered; download_to reicht BackupError unveraendert durch; Negativtest: getauschte 64-fach groessere Datei bricht am Deckel ab, Spool aufgeraeumt, Welt bleibt ready)

**File:** `src/gameworld/backup/service.py:490-513`, `src/gameworld/backup/files.py:199-208`
**Issue:** `_check_restore_space` budgetiert `RESTORE_SPACE_FACTOR * proof.size` freien Platz (T-05-35), aber `_fetch_and_check` laedt die Datei aus Files per `download_to` VOLLSTAENDIG in den Spool, bevor `_check_integrity` die Groesse gegen den Nachweis prueft. Wird die Datei in Nextcloud Files gegen eine deutlich groessere getauscht (Verwalter-Files sind beschreibbar, genau das Szenario, gegen das T-05-29 den SHA-Check einfuehrt), schreibt der Download beliebig viele Bytes nach `storage_dir/tmp`, bis der Datentraeger voll ist. Das trifft denselben Datentraeger wie `gameworld.sqlite3` (Zeittakt, Zaehlbuch-Verbuchung, Job-Zeilen schlagen dann fehl). Die Groessenpruefung existiert, kommt aber erst nach dem Vollpuffern; genau der Fehlerklasse "Body-Limit erst nach dem Lesen" galt der CR-01-Fix aus Phase 04.2.
**Fix:** Download auf `proof.size` deckeln und bei Ueberschreitung sofort als `RestoreTampered` abbrechen, z. B. mit einem begrenzenden Writer:
```python
class _CappedWriter(io.RawIOBase):
    def __init__(self, sink: BinaryIO, limit: int) -> None:
        super().__init__()
        self._sink, self._left = sink, limit

    def writable(self) -> bool:
        return True

    def write(self, b: Buffer, /) -> int:
        data = memoryview(b).cast("B")
        if len(data) > self._left:
            raise RestoreTampered
        self._left -= len(data)
        return self._sink.write(data)

# in _fetch_and_check:
await self._files().download_to(uid, proof.path, cast(BinaryIO, _CappedWriter(download, proof.size)))
```
(`download_to` muss `RestoreTampered` dafuer unveraendert durchreichen; alternativ vor dem Download ein `stat` per file_id und Groessenvergleich, dann bleibt der Deckel als zweite Verteidigungslinie.)

### WR-02: In Files umbenannte Sicherung wird gelistet, ist aber nicht wiederherstellbar

**Status:** fixed, Commit `3f7305a` (_current_path loest den Download-Pfad vor dem Laden per listdir ueber die file_id auf; Tests: umbenannte Sicherung restaurierbar, geloeschte mit fremder Datei am alten Namen ergibt MSG_FILE_GONE statt RESTORE_TAMPERED)

**File:** `src/gameworld/backup/service.py:673-704` (list_backups), `src/gameworld/backup/service.py:496` (download ueber `proof.path`)
**Issue:** Die Liste matcht Dateien gegen Nachweise ueber `(file_id, size)` aus `listdir` und zeigt dabei `entry.name` (den AKTUELLEN Namen in Files). Wiederherstellen laedt dagegen ueber den gespeicherten `proof.path`. Benennt der Verwalter die Datei in Nextcloud Files um (im selben Ordner, file_id und Groesse bleiben gleich), erscheint sie weiter als gueltige Sicherung in der Liste, aber jeder Restore endet mit `MSG_FILE_GONE` ("Diese Sicherung liegt nicht mehr in deinen Nextcloud-Dateien."), obwohl sie sichtbar daneben liegt. Legt er zusaetzlich eine andere Datei unter dem alten Namen ab, laedt der Restore die falsche Datei und meldet irrefuehrend `RESTORE_TAMPERED`. Umbenennen ist in der UI ausdruecklich vorgesehen ("Aufraeumen kannst du dort"), das ist also ein realistischer Nutzerpfad, kein Exot.
**Fix:** Den Download ueber die file_id aufloesen statt ueber den gespeicherten Pfad: in `list_backups`/`_fetch_and_check` den aktuellen Pfad aus dem `listdir`-Treffer (`entry.path`) verwenden bzw. vor dem Download per `by_id`/`listdir` den Pfad zur `proof.file_id` aufloesen und bei Treffer den Nachweis-Pfad aktualisieren. SHA- und Groessenpruefung bleiben unveraendert die Autoritaet.

### WR-03: TOCTOU im Upload: WebDAV-PUT kann eine fremde gleichnamige Datei ueberschreiben und der Fehlerpfad loescht sie (D-08-Randfall)

**Status:** fixed, Commit `7d154ba` (Upload auf eindeutigen Temp-Namen `.{name}.{uuid}.gwtmp`, Zielname per nc_py_api files.move mit "Overwrite: F", 412 fuehrt zum naechsten Suffix; Aufraeumpfad loescht nur noch die eigene Temp- bzw. frisch verschobene Datei; Race-Negativtests fuer PUT- und MOVE-Fenster)

**File:** `src/gameworld/backup/files.py:149-177`
**Issue:** `_free_target` prueft per `by_path`, dass der Zielname frei ist, danach laeuft `upload_stream`. WebDAV-PUT ueberschreibt still: Entsteht zwischen Pruefung und PUT eine gleichnamige Datei (zweites Geraet des Verwalters, Sync-Client, Auto-Upload in denselben Ordner), wird sie ueberschrieben; schlaegt danach die Groessenpruefung fehl, loescht der Aufraeumpfad `nc.files.delete(target)` diese Datei endgueltig. Das verletzt im Race sowohl T-05-08 ("nie eine vorhandene Datei loeschen") als auch den Geist von D-08. Der globale Ein-Job-Schutz verhindert nur Kollisionen der App mit sich selbst, nicht mit externen Schreibern.
**Fix:** Kollisionssicher hochladen: auf einen eindeutigen Temp-Namen (z. B. `.{base_name}.{uuid4().hex}.part`) hochladen und per WebDAV-MOVE mit `Overwrite: F` auf den Zielnamen verschieben (409 -> naechsten Suffix probieren); mindestens aber vor dem Aufraeum-DELETE per `by_path` pruefen, dass die file_id am Ziel NICHT schon vor dem eigenen PUT existierte (file_id vor dem Upload war 404, nach dem Upload gehoert sie der App), und sonst nicht loeschen.

## Info

### IN-01: Toter Code: `BackupFiles.stat` und `delete_own` werden produktiv nie aufgerufen

**File:** `src/gameworld/backup/files.py:79-90,191-197,210-215`
**Issue:** `stat` und `delete_own` existieren im Protocol, in `NcBackupFiles` und in beiden Fakes, haben aber keinen Aufrufer in `src/` (der Upload-Aufraeumpfad nutzt `nc.files.delete` direkt). Nur Tests rufen sie.
**Fix:** Entfernen oder mit Verweis auf den geplanten Verwender (z. B. WR-01-Fix: `stat` vor dem Download) kommentieren; `stat` wuerde der WR-01-Fix sinnvoll beleben.

### IN-02: Doku-Code-Abweichung beim Platzbedarf des Sicherns

**File:** `docs/install.md:261`, `src/gameworld/backup/service.py:122-123,336-341`
**Issue:** Die Doku sagt "Beim Sichern reicht etwa die einfache Groesse", der Code verlangt `SPACE_FACTOR = 2` mal die Groesse der letzten Sicherung als freien Platz. Ein Verwalter mit 1,5-facher Groesse frei bekommt entgegen der Doku "Nicht genug freier Speicherplatz auf dem Server."
**Fix:** Doku auf "etwa das Doppelte der letzten Sicherung" anpassen (oder den Faktor begruendet auf 1 senken; die Doku-Anpassung ist der sichere Weg).

### IN-03: D-09-Race: Spielerpruefung liegt vor und ausserhalb der Sperre

**File:** `src/gameworld/backup/service.py:253-257,447-449`
**Issue:** `players_online` wird vor `begin_offline` ohne Sperre geprueft. Tritt ein Kind zwischen Pruefung (0 Spieler, keine Bestaetigung noetig) und Halt bei, wird es ohne die D-09-Bestaetigung getrennt. Das Fenster ist Sekunden breit und das Kind bekommt weiterhin Chat-Hinweis plus Gnadenfrist; es bleibt eine bewusste Abschwaechung, keine Sicherheitsluecke.
**Fix:** Akzeptabel; wer es schliessen will, prueft die Spieler ein zweites Mal direkt nach `begin_offline` und bricht ohne Bestaetigung mit `abort_offline` plus `PlayersOnline` ab.

### IN-04: Nachweis-Zeilen (`backups`) geloeschter Konten werden nie aufgeraeumt

**File:** `src/gameworld/worlds/store.py:246-260` (ACCOUNT_TABLES), `src/gameworld/worlds/store.py:1259-1285`
**Issue:** `forget_account` laesst `backups.owner_uid` bewusst stehen (dokumentiert, D-08/v2-Import). Es gibt aber auch sonst keinen Pfad, der Nachweise eines in Nextcloud geloeschten Verwalters je entfernt: uid und Files-Pfade bleiben unbegrenzt in der DB, obwohl die Dateien mit dem Konto verschwunden sind (Datensparsamkeit). Ein Test fuer das dokumentierte Verhalten fehlt ebenfalls.
**Fix:** Mindestens einen Test fuer "forget_account laesst backups stehen" ergaenzen; fuer v1.x einen Aufraeumpunkt notieren (z. B. Nachweise eines Kontos loeschen, wenn das Konto endgueltig vergessen wird und die Zeilen keiner existierenden Welt mehr dienen).

### IN-05: Scheitert `recover_jobs` beim Start, blockiert der Ein-Job-Schutz bis zum naechsten Neustart

**File:** `src/gameworld/main.py:75-78`, `src/gameworld/worlds/service.py:665-667`
**Issue:** Wirft `recover_jobs` im Lifespan (z. B. DB kurz gesperrt), wird nur gewarnt. Die `running`-Zeilen bleiben stehen und `begin_offline` lehnt dann JEDEN neuen Auftrag im Haushalt mit `JOB_RUNNING` ab, bis ein weiterer Prozess-Neustart die Zeilen beendet. Selbstheilend nur per Neustart.
**Fix:** `recover_jobs` zusaetzlich periodisch nachholen (z. B. im Notify-/Reconcile-Takt einmalig wiederholen, bis es gelang) oder beim `JOB_RUNNING`-Befund pruefen, ob der Job aus einem frueheren Prozesslauf stammt (started_at vor Prozessstart) und ihn dann als unterbrochen beenden.

### IN-06: Abnahmeskript pinnt exakte Pruefzahlen der Regressionen

**File:** `scripts/dev/acceptance-phase5.sh:680-685`
**Issue:** Die Regression verlangt woertlich "84 von 84", "104 von 104", "75 von 75", "109 von 109 Pruefungen bestanden". Jede ergaenzte Pruefung in einer aelteren Phase laesst die Phase-5-Abnahme fehlschlagen, obwohl alles gruen ist. Gewolltes Pinning, aber ein Wartungsstolperstein.
**Fix:** Alternativ auf das Muster "(\d+) von \1 Pruefungen bestanden" je Log pruefen (alle bestanden, Zahl egal); wenn das Pinning bewusst bleibt, einen Kommentar mit der Update-Pflicht an jede Zahl haengen (ist teilweise vorhanden).

### IN-07: `jobNote` rendert bei fehlendem Fehlertext einen haengenden Doppelpunkt

**File:** `frontend/src/backup.js:34-38`
**Issue:** Bei `state === 'failed'` und `message === null` (theoretisch moeglich, die Spalte ist nullable) ergibt `jobNote` "Sicherung fehlgeschlagen: " mit leerem Grund.
**Fix:** `const reason = job.message ?? ''` und ohne Grund nur "Sicherung fehlgeschlagen." bzw. "Wiederherstellen fehlgeschlagen." ausgeben.

---

_Reviewed: 2026-10-24T04:15:39Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
