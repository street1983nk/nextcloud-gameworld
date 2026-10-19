---
phase: 02-one-click-welten
plan: 07
subsystem: acceptance
tags: [acceptance, phase-gate, playwright, luanti-client]
requires:
  - phase: 02-06
    provides: Reconciler (Boot- und periodischer Abgleich), Status aus Docker, Spieler und RAM, Presets
provides:
  - scripts/dev/acceptance-phase2.sh (K1 bis K4 plus Phase-1-Regression, 104 Prüfungen)
  - Owner-Freigabe der Phase-2-UI per gemeinsamer Playwright-Abnahme
  - Owner-Entscheide A1, A2, A8 und failed-Zeilen-Regel
affects: [phase-2-verifier, phase-3]
tech-stack:
  added: []
  patterns:
    - Abnahme nur mit docker-CLI, curl, jq, tar, grep (unabhängig von den Python-Codepfaden)
    - Fremd-Container-Schnappschuss (State, StartedAt) vor und nach K4 mit Positivkontrolle am eigenen Neustart
key-files:
  created:
    - scripts/dev/acceptance-phase2.sh
  modified:
    - scripts/dev/acceptance-phase1.sh
    - docs/dev-setup.md
    - docs/install.md
key-decisions:
  - "02-07: Owner bestätigt A1 (Kreativ-Preset behält fly und fast), A2 (Sanft-Schalter bleiben), A8 (Hunger bleibt an) und die failed-Zeilen-Regel aus 02-01"
  - "02-07: Live-Join mit echtem Luanti-Client vom Owner als offen entschieden (kein Client auf der Maschine), Nachholung bei nächster Gelegenheit"
  - "02-07: Phase-1-Abnahme ignoriert im statischen visibility-grep nur die Page Visibility API (document.visibilityState, visibilitychange), mit Positivkontrolle"
requirements-completed: [WELT-01, WELT-02, WELT-03, PLATT-02]
duration: 60min
completed: 2026-10-19
---

# Phase 2 Plan 07: Phasenabnahme One-Click-Welten Summary

**Ein unabhängiges Abnahmeskript belegt alle vier Erfolgskriterien von Phase 2 mit 104 von 104 Prüfungen (inklusive Phase-1-Regression 81/81), und der Owner hat die Dashboard-UI am 19.10.2026 gemeinsam per Playwright abgenommen; nur der Live-Join mit einem echten Luanti-Client ist offen.**

## Performance

- **Duration:** ca. 60 min (Skript, drei grüne Läufe, Owner-Abnahme)
- **Completed:** 2026-10-19
- **Tasks:** 2 (1 auto, 1 checkpoint:human-verify)
- **Files modified:** 4

## Accomplishments

- `scripts/dev/acceptance-phase2.sh` (POSIX sh, nur docker-CLI, curl, jq, tar, grep, awk, date):
  - **K1** Presets: genau mtg_kreativ und voxelibre_sanft mit Titel; One-Click ohne preset ergibt mtg_kreativ; Memory = MemorySwap 536870912 bzw. 1073741824, RestartPolicy no, Labels preset und schema 2; conf und world.mt per docker cp (creative_mode, enable_damage, only_peaceful_mobs, mcl_keepInventory, enable_pvp, gameid minetest/mineclone2, server_announce false, genau eine default_privs-Zeile ohne Admin-Rechte, keine doppelten Keys mit Positivkontrolle); Negativkontrollen survival_hart und mem_limit je 422; VoxeLibre-Welt sofort wieder gelöscht.
  - **K2** Lebenszyklus: running, stop, start, restart (StartedAt neuer); docker stop von außen ergibt stopped bei desired_state running; docker kill ergibt error mit "unerwartet"; Proxy gestoppt ergibt alle Welten unknown, POST 503 ohne Zeile; nach Proxy-Start wieder running.
  - **K3** Spieler und RAM: API 18,7 MB gegen docker stats 18,1 MiB, players [], Status-Datei nicht älter als StartedAt, gestoppte Welt RAM null; statisch kein `logs(` und kein content.luanti.org in src/gameworld.
  - **K4** Update und Reboot: echter Neustart des ExApp-Prozesses über register-exapp.sh ohne --rm-data; beide IDs, Presets, Status und Container-IDs bleiben; Reboot-Simulation bringt R1 mit gleicher Container-ID zurück, R2 bleibt exited; kein Nicht-Gameworld-Container verändert (Positivkontrolle: derselbe Vergleich erkennt den Neustart von R1).
  - Regression: `acceptance-phase1.sh` muss Exit 0 liefern.
- Läufe: 104 von 104 dreimal grün (zweimal direkt nacheinander, einmal nach der Owner-Abnahme), Laufzeit etwa 3,5 Minuten.
- Doku: `docs/dev-setup.md` Abschnitt "Phasenabnahme Phase 2"; `docs/install.md` Abschnitt "7. Speicherbedarf und Neustarts".

## Owner-Abnahme (19.10.2026, gemeinsam per Playwright, Ergebnis "Abgenommen")

1. **ok:** Spielart-Auswahl, "Bauen (kreativ)" vorausgewählt, keine Konfigfragen, keine Öffentlich-Option.
2. **ok:** "Mias Welt" (kreativ): Erfolgskarte mit Weltschlüssel, Chip "Läuft", "Arbeitsspeicher: 18 MB von 512 MB", "Niemand online", Port 30000.
3. **ok:** "Leos Abenteuer" (sanft): sichtbar "Startet gerade" mit 134 MB, dann "Läuft" mit "246 MB von 1 GB", Port 30001.
4. **ok:** Stoppen ("Gestoppt", RAM "nicht aktiv", Buttons wechseln), Starten, Neustarten (docker ps: Kreativ-Container danach "Up 21 seconds", VoxeLibre unverändert).
5. **ok:** Proxy gestoppt: Status beider Welten per Polling "Docker nicht erreichbar", Starten-Buttons gesperrt; Erstellen von "Abnahme Tot" ergab nur die Fehlerkarte (Proxy-Meldung mit tcp://127.0.0.1:23750), KEINE neue Zeile, keine Geisterzeile. Besonderheit: Nach dem Proxy-Start hat sich die Tabelle über das 5-s-Polling von selbst erholt (Tab war sichtbar), "Erneut prüfen" war nicht nötig; die Setup-Check-Karte erscheint nur bei einem Fehler beim Seitenladen.
6. **Live-Join offen:** Vom Owner als offen entschieden, auf der Maschine ist kein Luanti-Client installiert. Nachholung bei nächster Gelegenheit mit Client ("Gerade online: <Name>" binnen 10 s, Kreativinventar, Fliegen, Verlassen). Befund für das Phasen-Audit.
7. **ok:** Backend-Prozess beendet (PID-Datei war stale, Prozess auf Port 10040 per Stop-Process beendet), "Mias Welt" per docker stop extern gestoppt, register-exapp.sh: Welt lief sofort nach der Registrierung wieder (Boot-Abgleich vor Handshake-Ende, wie in K4b), "Leos Abenteuer" blieb unangetastet (gleiche Container-ID).
8. **Owner-Entscheide (wörtlich):**
   - A1 BESTÄTIGT: Kreativ-Preset behält fly und fast.
   - A2 BESTÄTIGT: Sanft-Schalter bleiben (friedliche Mobs, Inventar behalten, kein Feuer-/Explosionsschaden, Kommandoblöcke aus).
   - A8 BESTÄTIGT: Hunger bleibt an.
   - Zusatz-Entscheid BESTÄTIGT: failed-Zeile wird auch nach erfolgreichem Aufräumen gelöscht.
9. **ok:** Beide Welten per UI gelöscht (Bestätigungsdialog "Endgültig löschen" je Welt), docker ps -a und docker volume ls mit Label gameworld.managed=true: 0 und 0.

Keine Preset-Änderungen verlangt, K1 bleibt unverändert grün.

### Screenshots

- C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\26f83d85-f123-49b7-b92a-20e75304acd7\scratchpad\abnahme2-01-startseite.png (Schritt 1)
- C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\26f83d85-f123-49b7-b92a-20e75304acd7\scratchpad\abnahme2-02-mias-welt.png (Schritt 2)
- C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\26f83d85-f123-49b7-b92a-20e75304acd7\scratchpad\abnahme2-03-leos-startet.png (Schritt 3)
- C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\26f83d85-f123-49b7-b92a-20e75304acd7\scratchpad\abnahme2-04-zwei-welten.png (Schritt 4)
- C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\26f83d85-f123-49b7-b92a-20e75304acd7\scratchpad\abnahme2-05-proxy-weg.png (Schritt 5)
- C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\26f83d85-f123-49b7-b92a-20e75304acd7\scratchpad\abnahme2-06-nach-neustart.png (Schritt 7)

Schritt 6 hat keinen Screenshot (Live-Join offen).

## Task Commits

1. **Task 1: Abnahmeskript für die vier Erfolgskriterien plus Doku** - `adadb36` (test)
2. **Task 2: Gemeinsame UI-Abnahme mit dem Owner** - keine Codeänderung, Ergebnis in dieser Summary

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Phase-1-Regression war seit 02-04 rot**
- **Found during:** Task 1 (erster Lauf, 103 von 104)
- **Issue:** Die statische Prüfung "kein announce/serverlist/visibility in frontend/src" in acceptance-phase1.sh schlug auf `document.visibilityState` und `visibilitychange` des Pollings an (Browser-API, keine Weltoption).
- **Fix:** Nur diese beiden Namen werden vor dem grep entfernt, jedes andere Vorkommen in derselben Zeile zählt weiter; neue Positivkontrolle belegt, dass eine echte Sichtbarkeitsoption weiter erkannt wird. Phase 1 jetzt 81 statt 80 Prüfungen.
- **Files modified:** scripts/dev/acceptance-phase1.sh
- **Commit:** adadb36

**2. [Rule 3 - Blocking] uv-Kindprozess überlebt das Beenden der PID unter Windows**
- **Fix:** `kill_backend` im Abnahmeskript beendet zuerst die PID aus .dev/exapp.pid und, falls der Heartbeat weiter antwortet, den Prozess auf Port 10040 per taskkill. Der Owner-Schritt 7 bestätigt das Muster (PID-Datei stale).
- **Commit:** adadb36

**3. [Rule 1 - Doku] install.md nannte pauschal 512 MB RAM pro Welt**
- **Fix:** ergänzt um "(Abenteuer-Welt 1 GB)".
- **Commit:** adadb36

## Issues Encountered

- K4b und Owner-Schritt 7 zeigen "wieder running nach 0 s": register-exapp.sh blockiert bis zum Ende des Handshakes, der Boot-Abgleich läuft also davor. Dass R1 vor der Registrierung wirklich gestoppt war, prüft das Skript ausdrücklich.

## Offene Punkte für das Phasen-Audit

- Live-Join mit Luanti-Client 5.17 offen (Schritt 6); "Gerade online" mit echtem Spieler ist bisher nur über den Welt-Mod und Unit-/E2E-Tests belegt.
- Nebenbefund: .dev/exapp.pid kann unter Windows stale sein (uv-Elternprozess endet, Python-Kind läuft weiter); register-exapp.sh fängt das über den Heartbeat ab.

## Next Phase Readiness

- Phase 2 bereit für den Verifier; Phase 3 (Zugang und Rollen) kann auf Presets, Status-Mod und Reconciler aufbauen.

## Self-Check: PASSED

- FOUND: scripts/dev/acceptance-phase2.sh
- FOUND: commit adadb36
- acceptance-phase2.sh nach der Owner-Abnahme erneut: 104 von 104, Exit 0
