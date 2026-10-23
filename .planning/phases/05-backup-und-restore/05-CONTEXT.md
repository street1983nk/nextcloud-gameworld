# Phase 5: Backup und Restore - Context

**Gathered:** 2026-10-23
**Status:** Ready for planning

<domain>
## Phase Boundary

Eltern sichern pro Welt manuell einen konsistenten Weltstand nach Nextcloud Files (Cold-Backup: Welt sauber stoppen, sichern, wieder starten) und stellen eine Welt nachweislich aus einer Sicherung wieder her. Ein automatisierter Backup-Restore-Roundtrip-Test ist Abschlusskriterium. Requirements: BACKUP-01, BACKUP-02. Mode: mvp (vertikaler Schnitt UI -> API -> Provisioner -> Files).

Gesetzt durch ROADMAP/Research (nicht verhandelbar): Cold-Backup mit Stopp/Neustart, SQLite-Backend erzwungen (kein Kopieren laufender map.sqlite), Ablage in Nextcloud Files, ExApp kann keine Volumes mounten (Zugriff nur über Docker-API, get_archive/put_archive über den gescopten Socket-Proxy).

</domain>

<decisions>
## Implementation Decisions

### Ablageort und Dateiname
- **D-01:** Backups landen in den Files des auslösenden Verwalters unter `Gameworld/Sicherungen/<Weltname>/` (Standard-Files-Features wie Teilen/Versionen bleiben nutzbar).
- **D-02:** Dateiname `<weltname>-JJJJ-MM-TT-HHMM.tar.gz` (sortiert sich selbst, Welt und Zeitpunkt sofort erkennbar). Format tar.gz.
- **D-03:** Inhalt: NUR Weltdaten (Weltordner mit map.sqlite, world.mt, Spielstand). Zugangsdatei (gameworld_access.txt) und Spielzeit-Zählbuch (gameworld_time*.txt) werden NICHT mitgesichert, sondern nach dem Restore frisch aus der ExApp provisioniert.

### Restore-Verhalten
- **D-04:** Restore überschreibt die bestehende Welt an Ort und Stelle (nach Sicherheitsabfrage). Keine Restore-als-neue-Welt-Variante in v1.
- **D-05:** Vor jedem Restore legt die App automatisch ein Sicherheits-Backup des aktuellen Stands an (gleicher Ordner, Namenszusatz `vor-restore`). Restore ist damit immer umkehrbar.
- **D-06:** Nach dem Restore gilt der AKTUELLE Stand für Zugänge und Spielzeit: Zugangsdatei und Zeitregeln werden frisch provisioniert; Einladungen/Widerrufe/Limits von heute gelten, nur der Spielstand kommt aus dem Backup. Bereits genutzte Spielzeit von heute bleibt angerechnet (Zählbuch wird nicht zurückgesetzt; konsistent zu D-03).

### Backup-Liste und Aufbewahrung
- **D-07:** Die Weltenansicht zeigt die vorhandenen Sicherungen (Datum, Größe) direkt aus dem Files-Ordner gelesen, mit Wiederherstellen-Knopf je Eintrag.
- **D-08:** Die App löscht NIE selbst Backups (alle behalten). Eltern räumen bei Bedarf in Nextcloud Files auf; die Liste zeigt die Gesamtgröße.

### Ablauf-UX während Backup/Restore
- **D-09:** Sind beim Auslösen Spieler online: Verwalter sieht Warnung "In der Welt spielen gerade N Kinder, sie werden kurz getrennt" und muss bestätigen; die Spieler bekommen vorher einen kurzen Chat-Hinweis ("Die Welt macht gleich eine kurze Pause"), dann Stopp, Backup, Neustart.
- **D-10:** Eigene Phasen-Status: Weltkarte zeigt "Wird gesichert..." bzw. "Wird wiederhergestellt..." als eigenen Weltstatus (Muster wie "Startet gerade" aus Phase 2); Kinder-Ansicht kindgerecht "Die Welt macht kurz Pause"; Aktions-Knöpfe währenddessen gesperrt.
- **D-11:** Fehlerfall: Die Welt startet nach einem Backup-/Upload-Fehler IMMER wieder (Spielbetrieb geht vor); Verwalter sieht eine klare Fehlermeldung mit Grund; unvollständige Backup-Dateien werden aufgeräumt und nie als gültige Sicherung gelistet.

### Nachentscheide aus dem Research (Owner 23.10., auf Researcher-Fragen)
- **D-12:** Backup-Dateien ohne DB-Eintrag (Neuinstallation, von Hand kopiert) werden NICHT als Sicherung gelistet; nur Einträge mit file_id, Größe und SHA-256. Ein Manifest im Archiv hält v2 (Import fremder Sicherungen) offen.
- **D-13:** Bei mehreren Verwaltern sieht und nutzt jeder nur die Sicherungen in seinen eigenen Files.
- **D-14:** Die Welt startet direkt nach dem Snapshot wieder; der Upload nach Nextcloud Files läuft danach im Hintergrund (minimale Pause, bewusste Auslegung von D-09).
- **D-15:** Restore ist auch für kaputte Welten mit "Weltdaten fehlen" erlaubt, dann ohne vorheriges Sicherheits-Backup.
- **D-16:** Abschlussmeldung über den Notify-Weg: höchstens Fehler werden gemeldet (Auslegung der Discretion-Zeile unten).

### Claude's Discretion
- Technischer Weg des Archiv-Streams (get_archive über Hilfs-/Kurzzeitcontainer vs. direkter Volume-Zugriff), Upload per nc_py_api `files.upload_stream`, Timeouts, maximale Größenbehandlung, tar-Normalisierung.
- Exakte API-Routen- und Statusmodell-Gestaltung (konsistent zu bestehenden Mustern aus Phase 2).
- Ob der Chat-Hinweis über den bestehenden Welt-Mod-Weg oder einen vorhandenen Mechanismus läuft (einfachster belastbarer Weg; wenn unverhältnismäßig teuer, Befund an Owner statt Eigenbau).
- Benachrichtigung nach Abschluss (z.B. über den bestehenden Notify-Weg aus Phase 4.1) optional, wenn billig zu haben.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Projekt und Phase
- `.planning/ROADMAP.md` §Phase 5 , Goal, Success Criteria (Cold-Backup, SQLite erzwungen, Roundtrip-Test), Mode: mvp
- `.planning/REQUIREMENTS.md` , BACKUP-01, BACKUP-02
- `CLAUDE.md` , Stack-Vorgaben: tarfile (stdlib) + nc_py_api `files.upload_stream`, Welt vor dem Tar stoppen, Shared-Volume-/Hilfscontainer-Muster, Qualitätsgates

### Bestehende Muster (Phase 1/2)
- `src/gameworld/provisioner/archive.py` , vorhandene put_archive-Mechanik (Phase-1-Lehre: put_archive schreibt auch in Volumes nie gestarteter Container)
- `src/gameworld/lifecycle.py` , sauberes Stoppen/Starten, Saga-Muster
- `src/gameworld/nc.py` , Nextcloud-Session-Handling (Phase-4.1-Lehre: Session-Leak-Fix beachten)
- `.planning/phases/02-one-click-welten/` , Status-Modell derive_status, "Startet gerade"-Muster für D-10

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `provisioner/archive.py`: Archiv-Transfer über die Docker-API existiert bereits (put_archive); get_archive-Gegenstück für Backups ergänzen.
- `lifecycle.py`: Stop/Start mit Saga-Muster für den Cold-Backup-Ablauf wiederverwenden.
- Status-Mechanik aus Phase 2 (derive_status + Polling 5 s) für die neuen Zustände "Wird gesichert/wiederhergestellt".
- Welt-Mod-Kanal (gameworld_status/gameworld_time) als möglicher Weg für den Chat-Hinweis (D-09).
- Notify-Weg aus Phase 4.1 für optionale Abschluss-Benachrichtigung.

### Established Patterns
- Proxy-Scope: CONTAINERS+IMAGES+VOLUMES+POST (kein exec); lesende docker-py-Aufrufe einmal wiederholen (HAProxy-Keep-Alive-Lehre Phase 2).
- Einheitliche 403/404-Fehlerbilder, require_verwalter für Verwaltungsrouten (Backup/Restore sind Verwalter-Aktionen).
- Kindgerechte Status-Texte (fester Text statt Docker-Fehler, Lehre AR-24).

### Integration Points
- Welt-Detail/Weltkarte im Vue-Frontend (Backup-Knopf, Sicherungsliste, Status).
- Worlds-API (`src/gameworld/api/`, `src/gameworld/worlds/`) für neue Routen.
- nc_py_api Files (upload_stream/download) gegen die Files des Verwalters.

</code_context>

<specifics>
## Specific Ideas

- Sicherheits-Backup vor Restore mit Namenszusatz `vor-restore` im selben Ordner (D-05).
- Warntext-Muster: "In der Welt spielen gerade N Kinder, sie werden kurz getrennt" (D-09); Chat-Hinweis "Die Welt macht gleich eine kurze Pause".
- Roundtrip-Test (Erfolgskriterium 3): Welt erstellen -> spielstandwirksame Änderung -> Backup -> Änderung/Zerstörung -> Restore -> Zustand nachweislich wie beim Backup (automatisiert, Teil der Phasenabnahme).

</specifics>

<deferred>
## Deferred Ideas

- Automatische/geplante Backups (Zeitplan) , v2, BACKUP-01 ist bewusst manuell.
- Aufbewahrungsregeln (nur letzte N, Alterslöschung) , v2, App löscht in v1 nie selbst (D-08).
- Restore als neue Welt / Welt-Duplikation , v2 (D-04).

</deferred>

---

*Phase: 05-backup-und-restore*
*Context gathered: 2026-10-23*
