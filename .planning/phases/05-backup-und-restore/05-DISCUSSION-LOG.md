# Phase 5: Backup und Restore - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md , this log preserves the alternatives considered.

**Date:** 2026-10-23
**Phase:** 5-Backup und Restore
**Areas discussed:** Ablageort und Dateiname, Restore-Verhalten, Backup-Liste und Aufbewahrung, Ablauf-UX während Backup/Restore

---

## Ablageort und Dateiname

| Option | Description | Selected |
|--------|-------------|----------|
| Beim Verwalter (Empfohlen) | Ordner Gameworld/Sicherungen/<Weltname>/ in den Files des auslösenden Verwalters | ✓ |
| Fester App-Ordner | App-eigener Ordner via System-Konto | |
| Du entscheidest | Claude wählt | |

| Option | Description | Selected |
|--------|-------------|----------|
| Welt+Zeit (Empfohlen) | <weltname>-2026-10-23-1845.tar.gz | ✓ |
| Mit Welt-ID | <weltname>-<welt-id>-<zeit>.tar.gz | |

| Option | Description | Selected |
|--------|-------------|----------|
| Nur Weltdaten (Empfohlen) | Zugangsdatei und Zählbuch werden nach Restore frisch provisioniert | ✓ |
| Alles im Welt-Volume | Inklusive Zugangs- und Zeitdateien | |

**User's choice:** Durchweg die Empfehlungen.

---

## Restore-Verhalten

| Option | Description | Selected |
|--------|-------------|----------|
| Welt überschreiben (Empfohlen) | Restore ersetzt den Stand der bestehenden Welt nach Sicherheitsabfrage | ✓ |
| Als neue Welt | Alte Welt bleibt, neue entsteht | |
| Beides anbieten | Standard überschreiben, optional Kopie | |

| Option | Description | Selected |
|--------|-------------|----------|
| Ja (Empfohlen) | Automatisches Sicherheits-Backup vor jedem Restore (Namenszusatz vor-restore) | ✓ |
| Nein, nur Warntext | Sicherheitsabfrage reicht | |

| Option | Description | Selected |
|--------|-------------|----------|
| Aktueller Stand (Empfohlen) | Zugänge/Spielzeit von heute gelten, nur der Spielstand kommt aus dem Backup | ✓ |
| Stand aus dem Backup | Auch Zugänge/Zeitstände vom Backup-Zeitpunkt | |

**User's choice:** Durchweg die Empfehlungen.

---

## Backup-Liste und Aufbewahrung

| Option | Description | Selected |
|--------|-------------|----------|
| Liste in der App (Empfohlen) | Sicherungen mit Datum/Größe direkt in der Weltenansicht, Restore-Knopf je Eintrag | ✓ |
| Nur Files-Verweis | Link zum Ordner, Restore via Dateiauswahl | |

| Option | Description | Selected |
|--------|-------------|----------|
| Alle behalten (Empfohlen) | App löscht nie selbst, Eltern räumen in Files auf, Liste zeigt Gesamtgröße | ✓ |
| Nur letzte N | App löscht ältere automatisch (Voreinstellung 5) | |

**User's choice:** Durchweg die Empfehlungen.

---

## Ablauf-UX während Backup/Restore

| Option | Description | Selected |
|--------|-------------|----------|
| Warnung + Chat-Hinweis (Empfohlen) | Verwalter bestätigt Warnung, Spieler bekommen Chat-Hinweis, dann Stopp/Backup/Neustart | ✓ |
| Nur Warnung | Kein Chat-Hinweis | |
| Blockieren bis leer | Backup nur bei leerer Welt | |

| Option | Description | Selected |
|--------|-------------|----------|
| Eigene Phasen-Texte (Empfohlen) | "Wird gesichert..."/"Wird wiederhergestellt..." als Weltstatus, kindgerechte Kinder-Ansicht | ✓ |
| Einfacher Spinner | Nur Ladeindikator am Knopf | |

| Option | Description | Selected |
|--------|-------------|----------|
| Welt immer neu starten (Empfohlen) | Spielbetrieb geht vor, klare Fehlermeldung, unvollständige Dateien aufgeräumt | ✓ |
| Gestoppt lassen | Welt bleibt bis zur Reaktion des Verwalters gestoppt | |

**User's choice:** Durchweg die Empfehlungen.

---

## Claude's Discretion

- Technischer Archiv-Stream-Weg (get_archive/Hilfscontainer), upload_stream, Timeouts, Größenbehandlung
- API-Routen- und Statusmodell-Gestaltung (konsistent zu Phase 2)
- Mechanik des Chat-Hinweises (einfachster belastbarer Weg, sonst Befund an Owner)
- Optionale Abschluss-Benachrichtigung über den Notify-Weg aus Phase 4.1

## Deferred Ideas

- Automatische/geplante Backups (v2)
- Aufbewahrungsregeln nur letzte N / Alterslöschung (v2)
- Restore als neue Welt / Welt-Duplikation (v2)
