---
phase: 01-fundament
plan: 05
subsystem: acceptance, dev-docs
tags: [acceptance, phase-gate, playwright]
requires: ["01-04"]
provides:
  - "scripts/dev/acceptance-phase1.sh: unabhängige Phasenabnahme K1 bis K5 per docker-CLI, curl, tar und jq mit Positiv- und Negativkontrollen, Exit 0 nur bei vollständigem Erfolg"
  - "docs/dev-setup.md: Abschnitt Phasenabnahme mit `sh scripts/dev/acceptance-phase1.sh`"
  - "Owner-Freigabe der UI per gemeinsamer Playwright-Abnahme (19.10.2026, \"Abgenommen\")"
affects: [02]
tech-stack:
  added: []
  patterns: [Gegenprobe per docker-CLI und curl statt Python-Testhelfer, Proxy-Neustart und Aufräumen per trap, Testkonto gw-kind bleibt für UI-Abnahme bestehen]
key-files:
  created:
    - scripts/dev/acceptance-phase1.sh
  modified:
    - docs/dev-setup.md
decisions:
  - "Phase 1 vom Owner am 19.10.2026 per gemeinsamer Playwright-Abnahme freigegeben (alle 8 Schritte bestanden)"
  - "Nicht-Admin-Zugriff bestätigt Variante A: gw-kind sieht kein Gameworld im Top-Menü und bekommt 404 auf Seite, Bundle und API"
  - "Owner-Befund 'Erneut prüfen' aktualisiert nur die Setup-Check-Karte, nicht die Statusspalte: Kosmetik, Kandidat für Phase 2 (Status-UI)"
  - "Offene Produktfrage fürs Phasen-Audit: failed-Zeile nach gescheiterter Anlage belegt einen der 20 UDP-Ports bis zum Löschen"
metrics:
  duration: "Task 1 ca. 30 min, Abnahme gemeinsam mit dem Owner"
  completed: "2026-10-19"
  tasks: 2
  files: 2
---

# Phase 01 Plan 05: Phasenabnahme Summary

Unabhängiges Abnahmeskript belegt alle fünf Erfolgskriterien der Phase 1 mit 81 von 81 Prüfungen (zweimal grün), und der Owner hat die UI am 19.10.2026 gemeinsam per Playwright mit "Abgenommen" freigegeben.

## Erledigt

| Task | Name | Commit | Dateien |
|------|------|--------|---------|
| 1 | Abnahmeskript für alle fünf Erfolgskriterien mit Positiv- und Negativkontrollen | a7395c3 | scripts/dev/acceptance-phase1.sh, docs/dev-setup.md |
| 2 | Gemeinsame UI-Abnahme mit dem Owner per Playwright | keine Codeänderung | Screenshots im Scratchpad |

### Task 1: Abnahmeskript

- K1 Installation, Top-Menü und Nicht-Admin-Grenze (gw-kind: Seite, Bundle, API kein 200; Positivkontrolle Bundle als admin 200)
- K2 Lebenszyklus und Parallelität (zwei Welten, verschiedene UDP-Ports, gepinnter Image-Digest, Stop/Start, Löschen samt Volume)
- K3 Limits per docker inspect (Memory/Swap 512 MiB, PidsLimit 128, 1 CPU, CapDrop ALL, no-new-privileges, read-only, User 30000:30000, keine Binds), Negativkontrolle mem_limit 422
- K4 Privat per Default (minetest.conf per docker cp gelesen: server_announce = false, disallow_empty_password, Weltschlüssel, default_privs ohne Admin; root-eigen, read-only), Negativkontrollen 422 und grep ohne Treffer
- K5 Proxy-Scope (exec/info 403, nur 127.0.0.1), Setup-Check grün, bei gestopptem Proxy ok:false und 503 mit deutscher Meldung, nach Neustart wieder grün; docker-py nur im Provisioner
- Ergebnis: **81 von 81 Prüfungen bestanden** (Lauf beim Commit und erneut nach der UI-Abnahme)

### Task 2: Gemeinsame Playwright-Abnahme (Owner, 19.10.2026: "Abgenommen")

1. Login als admin, "Gameworld" im Top-Menü, Seite ohne Fehlerkarte: bestanden
2. "Mias Welt" erstellt, Erfolgskarte mit einmaligem Weltschlüssel, läuft auf UDP 30000: bestanden
3. "Leos Welt" parallel auf UDP 30001: bestanden
4. Mias Welt gestoppt und gestartet, Leos Welt lief durchgehend weiter: bestanden
5. Sichtprüfung: keine Öffentlich-/Serverlisten-Option, echte Umlaute, keine Emojis: bestanden
6. Proxy gestoppt: deutsche Fehlerkarte "Gameworld ist noch nicht startklar", "Welt erstellen" gesperrt; nach Proxy-Neustart sofort wieder ok: bestanden
7. Beide Welten über den Dialog "Endgültig löschen" entfernt, Liste leer, 0 Container mit gameworld.managed=true: bestanden
8. gw-kind: kein Gameworld im Top-Menü, 404 auf Seite, Bundle und API (Variante A): bestanden

Screenshots:
- C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\26f83d85-f123-49b7-b92a-20e75304acd7\scratchpad\abnahme-01-gameworld-seite.png
- C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\26f83d85-f123-49b7-b92a-20e75304acd7\scratchpad\abnahme-02-mias-welt.png
- C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\26f83d85-f123-49b7-b92a-20e75304acd7\scratchpad\abnahme-03-zwei-welten.png
- C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\26f83d85-f123-49b7-b92a-20e75304acd7\scratchpad\abnahme-06-proxy-fehlerkarte.png
- C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\26f83d85-f123-49b7-b92a-20e75304acd7\scratchpad\abnahme-08-gw-kind-kein-gameworld.png

## Owner-Befunde (festgehalten, nicht behoben)

1. **"Erneut prüfen" aktualisiert die Statusspalte nicht:** Nur die Setup-Check-Karte wird neu geladen; die Welttabelle zeigt bis zum Seiten-Reload weiter "Docker nicht erreichbar". Kosmetik, Kandidat für Phase 2 (Status-UI).
2. **failed-Zeile belegt einen Port:** Ein gescheiterter Anlage-Versuch bei totem Docker hinterlässt eine failed-Zeile, die einen der 20 UDP-Ports belegt, bis sie gelöscht wird (Design aus 01-03). Offene Produktfrage fürs Phasen-Audit: automatisch aufräumen, Port erst bei Erfolg vergeben oder so lassen.

## Deviations from Plan

None - plan executed exactly as written.

## Requirements

WELT-04, WELT-05, ZUGANG-01 durch K1 bis K5 und die Owner-Abnahme belegt.

## Self-Check: PASSED

- scripts/dev/acceptance-phase1.sh vorhanden
- docs/dev-setup.md enthält acceptance-phase1.sh
- Commit a7395c3 vorhanden
