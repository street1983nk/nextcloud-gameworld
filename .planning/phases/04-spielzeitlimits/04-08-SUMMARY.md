---
phase: 04-spielzeitlimits
plan: 08
subsystem: abnahme
tags: [acceptance, phase-gate, playwright, session-prober, docs]
requires:
  - phase: 04-spielzeitlimits
    provides: Welt-Mod gameworld_time, Wiederbeitritts-Sperre, Zeittakt, Verwalter-API, Eltern-UI, Kind-Ansicht (04-01 bis 04-07)
provides:
  - scripts/dev/acceptance-phase4.sh (K1 bis K6 plus Regression Phase 1 bis 3)
  - docs/install.md Abschnitt 9 "Spielzeit" (Ausfallverhalten, Datensparsamkeit, bekanntes Verhalten)
  - docs/dev-setup.md "Phasenabnahme Phase 4", CLAUDE.md-Zeilen gameworld_time und tzdata
  - Owner-Freigabe der Phase 4
affects: [04.1, 05]
tech-stack:
  added: []
  patterns:
    - "Zeit-Eingaben im Abnahmeskript per zoneinfo-Helfer berlin_now, nie TZ=... date (Git-Bash ohne zoneinfo)"
    - "Messwert unabhängig vom Takt: Vorlauf-Sitzung und Warten auf die Verankerung in time_ledger_seen vor der Limitmessung"
key-files:
  created:
    - scripts/dev/acceptance-phase4.sh
  modified:
    - docs/install.md
    - docs/dev-setup.md
    - CLAUDE.md
key-decisions:
  - "K5 mit Vorlauf: gw-kind betritt die Welt einmal 3 s ohne Regeln, das Skript wartet auf die Verankerung; so misst K5 das Limit und nicht die Erstkontakt-Verankerung (bis etwa 20 s einmalig je Kind und Welt ungezählt, in install.md dokumentiert)"
  - "Gemeinsame Abnahme ohne Playwright-MCP: sichtbarer Chromium (headed, slowMo 600) per Skript, Owner schaut zu"
  - "Owner-Textentscheide (Schritt 8) als Quick-Task 261021-481 umgesetzt: keine '0 Uhr', 'Mitternacht' oder Kurzform, Tagesbezug heute/morgen/am X/nächsten X, Uhrzeit nur bei echter Startzeit, Voreinstellung 'Jeden Tag 1 Stunde' 9 bis 19 Uhr, Vorwarnung 10 min ohne 'Speichern'"
  - "'Bonuszeit heute' als v2 (REQUIREMENTS, 5971530); ebenso v2: Mehr-Zeit-Anfrage, Talk-Bot, Discord-Webhook; außerhalb des Umfangs: Zwei-Wege-Chatbrücke"
requirements-completed: [ZEIT-01, ZEIT-02, ZEIT-03, ZEIT-04, ZEIT-05]
metrics:
  duration: 2 Sitzungen (20.10. abends, 21.10.)
  completed: 2026-10-21
  tasks: 2
  files: 4
---

# Phase 4 Plan 08: Phasenabnahme Spielzeitlimits Summary

Ein Skript belegt alle sechs Erfolgskriterien der Phase 4 gegen den echten Dev-Stack (echte Nextcloud, ExApp mit Lifespan-Zeittakt, Session-Prober gegen eine echte Luanti-Welt) samt Regression der Phasen 1 bis 3. Es lief zweimal hintereinander mit 107 von 107 Prüfungen und Exit 0. Danach hat der Owner Eltern- und Kind-Sicht gemeinsam im sichtbaren Browser abgenommen ("ok abgenommen", 21.10.2026).

## Ergebnis

- **acceptance-phase4.sh:** Vorbereitung (Welt "Abnahme Spielzeit", gw-kind, gw-abnahme4 und admin eingeladen), dann K1 bis K6 und Aufräumen. Am Ende kommt die Regression über acceptance-phase3.sh, die Phase 1 und 2 selbst aufruft.
  - Werkzeuge: docker-CLI, curl, jq, tar, grep und SQLite nur lesend (sqlite3 oder stdlib). Einziges Projekt-Python ist der Prober über seine CLI.
  - Der trap räumt Welt, Regeln, Ferien, Zeitzone und gw-abnahme4 auf.
- **K1** Limit und Fenster pro Kind: Regeldatei-Zeile (Deckel 7200, Epoch-Grenzen, ok), frei-Zeile für den Verwalter, Datei root und 0444, vier Negativkontrollen mit 422 bzw. nicht 200.
- **K2** Wochenplan:
  - Nur morgen erlaubt: denied mit "Heute ist kein Spieltag. Morgen kannst du wieder spielen.", ohne "0 Uhr" oder "00:00".
  - Heute erlaubt: auth_accept ohne Neustart.
  - Alle vier Voreinstellungen stehen im ausgelieferten Bundle.
- **K3** Ferien: ohne Zeitraum denied, Ferientag heute ergibt auth_accept und active true, nach dem Entfernen wieder denied. "Mars/Base" ergibt 422.
- **K4** Welt-Zeitfenster:
  - gw-kind wird mit dem Text "Diese Welt ist gerade zu ..." abgewiesen.
  - admin bekommt auth_accept.
  - "Fremder" bekommt den Zugangstext, nicht den Zeittext.
  - Container läuft weiter, desired_state running.
- **K5** Trennen:
  - Trennen nach 119,8 s bzw. 123,5 s, vorher Chat "Noch 1 Minute".
  - Rejoin nach 2,5 s denied.
  - time_usage 109 s bzw. 118 s, keine Zeile für gw-abnahme4.
  - /my/playtime: gw-kind "aufgebraucht", gw-abnahme4 limited false.
  - gw-abnahme4 ohne Regeln blieb 170 s verbunden.
- **K6** Neustart- und Rejoin-Festigkeit:
  - Nach Welt-Neustart, bei gestoppter ExApp und nach ExApp-Neustart jeweils denied mit dem Limittext.
  - Zählbuch nur "Name Sekunden", keine IP-Muster (mit Positivkontrolle).
  - Wiederbeitritts-Sperre 5 von 5, kein Absturz.
  - time_usage hat genau nc_user, day, seconds; kein Passwort in der SQLite-Datei.
- **Regression:** acceptance-phase3.sh Exit 0; im Log stehen 84 von 84, 104 von 104 und 75 von 75. Keine Prüfung der Phasen 1 bis 3 wurde angepasst.
- **Doku:** install.md Abschnitt 9 "Spielzeit" mit:
  - Grundregeln, Ferien, Zeitzone, Welt-Zeitfenster und Verhalten im Spiel
  - bekanntem Verhalten (Trennung um 00:00, Erstkontakt-Verankerung)
  - Ausfallverhalten nach Research Pattern 7, inklusive Restrisiko zwei Welten bei ExApp-Ausfall
  - Datensparsamkeit
  - T-04-28: Ein entfernter Verwalter bleibt frei, bis ein Verwalter das Dashboard öffnet, danach höchstens etwa 60 s.
- dev-setup.md "Phasenabnahme Phase 4"; CLAUDE.md je eine Zeile gameworld_time und tzdata 2026.5.

### Nachweise

- Zwei volle Läufe mit je **107 von 107 Prüfungen bestanden, Exit 0**:
  - `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\a8f4f483-22df-4541-8cb7-650b29ce088b\scratchpad\p4-full1.log`
  - `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\a8f4f483-22df-4541-8cb7-650b29ce088b\scratchpad\p4-full2.log`
- Die neuen Kindertexte kamen live aus dem Lua-Mod, die Umlaute korrekt auf Protokollebene. Beispiele:
  - "Deine Spielzeit für heute ist vorbei. Nächsten Mittwoch kannst du wieder spielen."
  - "Heute ist kein Spieltag. Morgen kannst du wieder spielen."
  - "Diese Welt ist gerade zu. Morgen ab 10 Uhr ist sie wieder offen."
- Ein früherer Lauf am 20.10. wurde von Claude Code wegen Speichermangels beendet: Der Vite-Build in register-exapp.sh brach ab. Das war kein Produktfehler. Die Reste habe ich aufgeräumt.
- `grep -c '^# K[1-6]'` = 6; kein `TZ=Europe/Berlin`; Gedankenstrich-Suche leer.

### Gemeinsame Owner-Abnahme (Task 2)

- Die Playwright-MCP war getrennt. Die zehn Schritte liefen deshalb per Skript in einem **sichtbaren** Chromium (headed, slowMo 600), während der Owner zusah: `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\a8f4f483-22df-4541-8cb7-650b29ce088b\scratchpad\abnahme-04-08-headed.cjs`.
- Alle Schritte verliefen wie erwartet, 0 Konsolenfehler. Danach wurde aufgeräumt: Klassenwelt gelöscht, keine Container mit `gameworld.managed=true`, gw-kind ohne Regeln.
- Owner-Antwort: **"ok abgenommen"** (21.10.2026, "approved").
- **Owner-Antwort zu Schritt 8:**
  - Die Kindertexte wurden nach Owner-Entscheid geändert und vor der Abnahme als Quick-Task 261021-481 umgesetzt (7cef5a9, efbf99d, d328457, Doku a446cfc).
  - Inhalt: keine "0 Uhr", keine "Mitternacht", keine Kurzform; Tagesbezug heute, morgen, am X oder nächsten X; Uhrzeit nur bei echter Startzeit; Voreinstellung "Jeden Tag 1 Stunde" jetzt 9 bis 19 Uhr; neue 10-Minuten-Vorwarnung ohne "Speichern".
  - "Bonuszeit heute" kommt nach v2 (REQUIREMENTS, 5971530). Ebenfalls v2: Mehr-Zeit-Anfrage, Talk-Bot, Discord-Webhook. Außerhalb des Umfangs: Zwei-Wege-Chatbrücke.
  - Damit ist auch die offene Frage aus 04-07 ("Nächste Spielzeit: Mittwoch 0 Uhr") erledigt.
- Screenshots:
  - `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\a8f4f483-22df-4541-8cb7-650b29ce088b\scratchpad\04-08-ui-1-uebersicht.png`
  - `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\a8f4f483-22df-4541-8cb7-650b29ce088b\scratchpad\04-08-ui-2a-dialog-hand.png`
  - `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\a8f4f483-22df-4541-8cb7-650b29ce088b\scratchpad\04-08-ui-2b-dialog-ferienblock.png`
  - `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\a8f4f483-22df-4541-8cb7-650b29ce088b\scratchpad\04-08-ui-2c-chip.png`
  - `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\a8f4f483-22df-4541-8cb7-650b29ce088b\scratchpad\04-08-ui-3-ferien.png`
  - `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\a8f4f483-22df-4541-8cb7-650b29ce088b\scratchpad\04-08-ui-4a-zeitfenster-dialog.png`
  - `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\a8f4f483-22df-4541-8cb7-650b29ce088b\scratchpad\04-08-ui-4b-welt-chip.png`
  - `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\a8f4f483-22df-4541-8cb7-650b29ce088b\scratchpad\04-08-ui-5-zeitzone.png`
  - `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\a8f4f483-22df-4541-8cb7-650b29ce088b\scratchpad\04-08-ui-6-kind.png`
  - `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\a8f4f483-22df-4541-8cb7-650b29ce088b\scratchpad\04-08-ui-7-kind-ohne-block.png`

## Offen für das Phasen-Audit (ausdrücklich nicht erledigt)

- **Umlaute und Reconnect im echten Client:** Darstellung der Umlaute in Chat-Vorwarnung und Trenntext im echten Luanti-Client sowie das Verhalten des Clients nach disconnect_player (Reconnect-Knopf). Auf Protokollebene kommen die Umlaute korrekt an, im echten Client ist das nicht geprüft.
- **Live-Join mit echtem Client:** Auf dieser Maschine gibt es keinen Luanti-Client.
- **Restrisiko zwei Welten bei ExApp-Ausfall:** Bei länger ausgefallener ExApp am selben Tag ruht der Abgleich zwischen den Welten. Wer in zwei Welten spielt, kann bis zur Rückkehr der ExApp doppelt so lange spielen. Das steht in install.md.
- Die Upstream-Meldung des Rejoin-Absturzes an luanti-org läuft separat (O-12) und ist nicht Teil dieser Abnahme.

## Commits

| Task | Commit | Beschreibung |
|------|--------|--------------|
| 1 | 6c680e8 | acceptance-phase4.sh, install.md Spielzeit, dev-setup.md, CLAUDE.md |
| (Quick 261021-481) | 7cef5a9, efbf99d, d328457, a446cfc | Owner-Textentscheide aus Schritt 8, Skript und Doku an die neuen Texte angepasst |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Messfehler] Trennzeitpunkt hing von der Lage im Zeittakt ab**
- **Found during:** Task 1, erster Lauf (Trennen bei 136 s, knapp unter der Grenze 140)
- **Issue:** Die Erstkontakt-Verankerung in playtime/ledger.py lässt die Sekunden bis zum ersten Takt einmalig je Kind und Welt ungezählt, bis etwa 20 s. Das ist bewusst so, als Schutz gegen Doppelzählung. Die Prüfung "100 bis 140 s" konnte dadurch zufällig scheitern.
- **Fix:** K5-Vorlauf: Sitzung 3 s ohne Regeln, danach Warten auf die Zeile in time_ledger_seen. Die Plangrenze bleibt, gemessen wurden danach 119,8 bis 124,3 s. Das Verhalten steht in install.md unter "Bekanntes Verhalten".
- **Files modified:** scripts/dev/acceptance-phase4.sh, docs/install.md
- **Commit:** 6c680e8

### Hinweise

- Die Wegwerfkonten gw-abnahme2 (Phase 3) und gw-abnahme4 (Phase 4) legen die Abnahmeskripte bei jedem Lauf an und löschen sie im trap wieder. Am 21.10. waren beide in der Dev-Nextcloud nicht vorhanden (`occ user:info`: user not found), es war nichts zu löschen.
- Der Knopf "Zeitzone dieses Browsers übernehmen" erscheint nur, wenn die Browser-Zone von der Haushalts-Zone abweicht. Für die Abnahme lief der Browser deshalb mit Europe/Vienna.
- Owner hat zusätzlich Phase 4.1 "Eltern-Handy" eingefügt (e14c39c); ein Browser-Spiel-Spike folgt separat.

## Known Stubs

Keine.

## Threat Flags

Keine neue Fläche. T-04-41: Das Skript gibt nur Muster und Längen aus. T-04-42: Der trap entfernt Regeln, Ferien und Fenster, die Abschlussprüfung bestätigt gw-kind ohne Regeln und nicht in admin. T-04-43: Neustart nur über die PID-Datei bzw. Port 10040. T-04-45: Die Owner-Antwort steht wörtlich oben.

## Self-Check: PASSED

- Dateien vorhanden: scripts/dev/acceptance-phase4.sh, docs/install.md (Spielzeit), docs/dev-setup.md, CLAUDE.md (tzdata)
- Commits vorhanden: 6c680e8, 7cef5a9, efbf99d, d328457, a446cfc
- Logs p4-full1.log und p4-full2.log mit je 107 von 107 vorhanden
