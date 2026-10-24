---
phase: 05-backup-und-restore
plan: 09
subsystem: backup
tags: [acceptance, phase-gate, playwright, webdav, regression]
requires:
  - "05-05: POST/GET /api/worlds/{id}/backups, Hintergrund-Job, Cold-Snapshot"
  - "05-06: POST /api/worlds/{id}/restore, vor-restore-Sicherung, Tausch"
  - "05-07: Sicherungsbereich der Verwaltungsansicht (Dialoge, Chips, Fehlerkarte)"
  - "05-08: e2e-Roundtrip-Muster (Mia/Leo, unabhängige Gegenprobe)"
provides:
  - "scripts/dev/acceptance-phase5.sh: Phasenabnahme K1 bis K3 gegen echte Nextcloud 34.0.3, echte ExApp und echtes Docker, mit Regression Phase 4.1 bis 1"
  - "docs/install.md Abschnitt 11 Sicherungen (Elterndoku)"
  - "Owner-Freigabe (approved) der Sicherungs-Oberfläche per gemeinsamer Playwright-Abnahme"
affects:
  - "Phase 6 (Store-Release): Deep Review und /gsd-secure-phase 05 folgen laut Owner-Regel"
tech-stack:
  added: []
  patterns:
    - "Grundlinien-Muster gegen fremde Umgebungsreste: Container- und /my/worlds-Stand vor dem Lauf, gezählt wird nur, was der Lauf selbst anlegt"
    - "Regressionsprüfungen zitieren Produkttexte als Literale; bei Owner-Textentscheiden werden die Prüfungen nachgezogen, nie das Produkt rückgebaut"
key-files:
  created:
    - scripts/dev/acceptance-phase5.sh
  modified:
    - docs/install.md
    - src/gameworld/backup/files.py
    - src/gameworld/backup/service.py
    - scripts/dev/acceptance-phase3.sh
    - scripts/dev/acceptance-phase4.sh
    - scripts/dev/acceptance-phase4_1.sh
decisions:
  - "Owner-Entscheid 'Prüfungen anpassen': Die drei veralteten Regressionsprüfungen (4.1 K2 Uhrzeit-Text, Phase 3 K5 players-Spalten, Phase 3 K3 genau-die-Abnahme-Welt) wurden auf den heutigen Produktstand gezogen (da2ad56, dabe0c0) statt die Produkte zurückzubauen"
  - "Phase 3 K5 prüft tolerant: Pflichtspalten nc_user, player_name, rotation vorhanden, keine Spalte enthält 'pass'; die Absicht (keine Passwortspalte) bleibt"
  - "Phase 3 K3 zählt nur Welten, die nach der Grundlinie des Laufs neu in /my/worlds auftauchen; alle worlds[0]-Zugriffe filtern auf die Abnahme-Welt (Owner-Spike-Welten stören nicht mehr)"
  - "Die Phase-4-Stabilitätsprüfung (AppAPI-Verbindungsfehler seit Laufbeginn) bleibt unverändert, obwohl sie in Lauf 1 an einer offenen Browser-Sitzung scheiterte: sie ist der Wächter gegen echte ungeplante Backend-Ausfälle"
metrics:
  duration: "2 Sitzungen"
  completed: 2026-10-24
  tasks: 2
  files: 8
---

# Phase 5 Plan 09: Phasenabnahme Backup und Restore Summary

Automatisierte Phasenabnahme acceptance-phase5.sh (96 Prüfungen: Cold-Backup mit 409-Negativkontrolle, Datei per WebDAV in Files mit D-13-Härtetest, Restore-Roundtrip Mia/Leo mit sqlite3-Gegenprobe) plus Regression Phase 4.1 bis 1, Eltern-Doku Abschnitt 11, und die gemeinsame Playwright-Abnahme mit dem Owner: approved, alle 7 Schritte bestanden.

## Tasks

| Task | Name | Commits |
| ---- | ---- | ------- |
| 1 | acceptance-phase5.sh und Eltern-Doku | 19ffbc4 (Skript), 772ff0f (docs/install.md 11), 7cf5972 + 82871f5 (Fixes), 79c52a6 (Regressions-Anpassungen) |
| 2 | Gemeinsame Playwright-Abnahme mit dem Owner | keine (Checkpoint, Owner "approved") |

## Owner-Abnahme (Task 2): approved

Abnahme-Welt war "Browser Minetest" (ff2295234c42), alle 7 Schritte bestanden:

1. Dialog "In der Welt spielt gerade 1 Kind, es wird kurz getrennt." beim Sichern mit Spieler online
2. "Wird gesichert ...", Knöpfe gesperrt; danach Welt wieder "Läuft", Liste mit Datum und Größe
3. Archiv in Files unter Gameworld/Sicherungen/Browser Minetest/
4. Restore mit Sicherheitsabfrage; vor-restore-Eintrag "vor dem Wiederherstellen" in der Liste
5. Kinder-Ansicht zeigte während der Sicherung "Die Welt macht kurz Pause"; Prober-Kick mit Chat-Vorwarnung und Pausentext
6. Kontingent 1 MB: Fehlerkarte "Sicherung fehlgeschlagen: Nicht genug Speicherplatz in deinen Nextcloud-Dateien.", Welt lief weiter, Glocken-Benachrichtigung; Kontingent zurückgesetzt
7. 390 px: Sicherungsdialog voll bedienbar

Zwei Beobachtungen (keine Produktfehler):

- Der erste Halt in Schritt 5 lief noch mit dem alten Zeit-Mod des 16 Stunden alten Containers und kickte mit "Server shutting down."; nach dem Container-Neuaufbau kamen Chat-Vorwarnung und Pausentext wie vorgesehen. Alt-Container, kein Produktfehler.
- In "Browser Minetest" liegen jetzt 3 Sicherungen des Owners (0440, 0442-vor-restore, 0445; gesamt 3 MB). Sie gehören dem Owner und wurden nicht angetastet.

## Gesamtläufe 24.10.2026 (nach den Regressions-Anpassungen)

- **Lauf 1 (04:53 bis 05:34): 100 von 103, Exit 1.** Phase-5-Teil 96 von 96 grün. Regression: Phase 1 84/84, Phase 2 104/104, Phase 3 75/75 (inklusive der neuen K3-Grundlinie und K5-Spaltenprüfung), die 4.1-eigenen Prüfungen inklusive des angepassten K2-Texts liefen durch. Einzige Ursache der 3 Fehlschläge: Die Phase-4-Stabilitätsprüfung zählte 17 AppAPI-Verbindungsfehler; alle 17 fallen zeitlich exakt in die geplanten Backend-Neustarts, Quelle war das 5-s-Polling der noch offenen Browser-Sitzung der Owner-Abnahme (cURL error 7 in den Neustart-Lücken). Umgebung, kein Produktfehler.
- **Lauf 2 (Bestätigungslauf nach Ende der Browser-Sitzung): Phase-5-Teil erneut 96 von 96 grün** inklusive Aufräumen; die Regression wurde von der Claude-Code-Speicherüberwachung beim Start abgebrochen (Systemspeicher knapp, kein Fehler des Laufs) und gemäß Hinweis nicht neu gestartet.

Belegt sind damit: alle 96 Phase-5-Prüfungen zweimal grün, alle Regressionsphasen 1 bis 4.1 funktional grün (einzige offene Prüfung ist der Stabilitätswächter der Phase 4, dessen Fehlerquelle beseitigt ist). Der volle 103/103-Bestätigungslauf steht in deferred-items.md als offener Punkt.

## Deviations from Plan

**1. [Rule 1 - Bug, Task 1] Backup-Ordner mit Slash-Pfaden angelegt** (7cf5972): nc_py_api makedirs scheiterte am Proxy; files.py legt die Ordnerkette jetzt selbst mit Slash-Pfaden an. Mit Testausbau.

**2. [Rule 1 - Bug, Task 1] Halt-Gnadenfrist deckt einen vollen Zeit-Mod-Takt** (82871f5): Der Stopp konnte vor dem Kick-Takt des Mods greifen; die Frist umfasst jetzt einen vollen Takt. Mit Testausbau.

**3. [Owner-Entscheid] Drei veraltete Regressionsprüfungen angepasst** (79c52a6) statt als bekannt-rot stehen zu lassen: 4.1 K2 erwartet den Text seit da2ad56 ("wollte um H:MM beitreten"), Phase 3 K5 toleriert die salt-Spalte (dabe0c0) bei bleibender Absicht keine Passwortspalte, Phase 3 K3 arbeitet mit einer /my/worlds-Grundlinie (gleiches Muster wie die Container-Grundlinie aus 19ffbc4).

**4. [Umgebung, dokumentiert] Lauf 1 nicht 103/103**: Ursache (offene Abnahme-Browser-Sitzung) geklärt und beseitigt; Bestätigungslauf extern abgebrochen, nicht eigenmächtig neu gestartet (Speicher-Regel). Offener Punkt in deferred-items.md.

## Deferred Issues

- **Voller Bestätigungslauf 103/103** bei genug freiem RAM und ohne offene Gameworld-Browser-Sitzung (deferred-items.md).
- **Reste des abgebrochenen Laufs 2**: Welt "Abnahme Talk" (34cc17ad808d) und Wegwerfkonto gw-abnahme41; der nächste Abnahmelauf räumt beides selbst weg (API-Löschung wurde vom Berechtigungs-Klassifizierer blockiert).

## Known Stubs

Keine.

## Threat Flags

Keine neuen Oberflächen; das Abnahmeskript nutzt nur Dev-Zugangsdaten einer Loopback-Instanz (T-05-42 accept), DELETE nur auf eigene Abnahme-Namen (T-05-43 mitigiert), D-13 hart geprüft (T-05-53), Gegenproben über unabhängige Muster (T-05-44).

## Self-Check: PASSED

- scripts/dev/acceptance-phase5.sh und docs/install.md Abschnitt 11 vorhanden; Commits 19ffbc4, 772ff0f, 7cf5972, 82871f5, 79c52a6 stehen im Log; keine unbeabsichtigten Dateilöschungen.
