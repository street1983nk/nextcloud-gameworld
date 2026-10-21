---
status: resolved
trigger: "acceptance-phase4.sh Lauf 3 nach Review-Fixes: Regression Phase 2/3 HTTP 500, 104/107"
created: 2026-10-21T16:41:00+02:00
updated: 2026-10-21T18:10:00+02:00
---

## Current Focus

hypothesis: Backend-Prozess verschwindet während der Regression (kein Listener), Ursache offen
test: voller acceptance-phase4.sh-Lauf mit Log-Snapshot je PID (scratchpad/snap)
expecting: Endzeilen "Shutting down/Finished server process" = geordnetes Signal; keine Endzeilen = hart beendet
next_action: Lauf p4-full4-debug.log auswerten

## Symptoms

expected: acceptance-phase4.sh 107/107
actual: Phase 4 K1-K6 ok, Regression Phase 3 K3+ und Phase 2 K2 HTTP 500; Phase 1 84/84
errors: HTTP 500 auf /my/worlds, settings, bundle, /api/me, stop/start/restart
reproduction: sh scripts/dev/acceptance-phase4.sh
started: nach Commits 1c2b06f..7fc1033

## Evidence

- timestamp: 16:40
  checked: .dev/exapp.pid, netstat 10040
  found: PID-Datei 154661 (MSYS-PID des uv-Wrappers), Listener Windows-PID 2172; Log des alten Backends ist überschrieben
  implication: Beweise aus Lauf 3 verloren, Reproduktion nötig

- timestamp: 16:52
  checked: nextcloud.log (app_api-Einträge 21.10.)
  found: JEDE 500 aus Lauf 3 ist AppAPI "cURL error 7: Failed to connect to host.docker.internal port 10040" (14:29:49 bis 14:31:10 UTC und 14:34:03 bis 14:37:54 UTC); kein 401, kein Traceback-Pfad
  implication: Backend lauschte nicht (Prozess weg). Kein Secret-Mismatch (wäre 401 vom Backend), keine Exception im Handler (wäre Request im Backend-Log)

- timestamp: 16:49
  checked: acceptance-phase3.sh standalone (enthält Phase 1 und 2), Logs je PID mitgeschnitten
  found: 73/75, keine einzige 500; nur "keine Welt-Container übrig (ist 2)" wegen der Altlasten aus Lauf 3
  implication: Code-Pfade der Fixes (my/worlds, settings, me, bundle, stop/start/restart) funktionieren; Tod des Backends nicht deterministisch

- timestamp: 16:55
  checked: Windows Application/System Eventlog 16:20-16:40, Transkripte der Hauptsession
  found: kein Absturz-Event (1000/1001), keine Ressourcen-Erschöpfung; Hauptsession hat in dem Fenster nichts beendet
  implication: Prozess endete ohne Crash-Event (TerminateProcess oder geordnetes Herunterfahren)

- timestamp: 17:07
  checked: zweiter Reproduktionsversuch, voller acceptance-phase4.sh mit Listener-Protokoll je Sekunde
  found: kein ungeplanter Ausfall; jede Listener-Lücke = geplanter Neustart (K6, P3-K5, P2-K4a/K4b), Listener nach kill -TERM auf die PID-Datei binnen 1 s weg; nur Fehlschlag: Altlast-Welt 96257c5c81ae ("Abnahme Kreativ", Zeile aus Lauf 3) vom Boot-Abgleich neu angelegt
  implication: PID-Datei (MSYS-Stub von uv) trifft den echten Listener; kein Code-Fehler; Folgeschaden des Ausfalls = Weltzeile ohne Container

- timestamp: 17:12
  checked: AppAPI-Verhalten bei totem Backend (Listener gezielt beendet)
  found: jede Anfrage wird als cURL error 7 geloggt, auch die erste; in Lauf 3 fehlt für den ersten Kind-Aufruf /my/worlds ein solcher Eintrag
  implication: Das Backend antwortete darauf noch selbst mit 500 und verschwand Sekunden danach (Muster eines Prozessendes mitten im Betrieb); Grund nicht mehr belegbar, weil register-exapp.sh exapp.log bei jedem Start überschrieb

## Eliminated

- hypothesis: Secret-Mismatch (Neuregistrierung, alter Prozess hält Port 10040)
  evidence: Alle 500 = "Failed to connect" (kein Listener), nicht 401; "Invalid App secret" um 16:38 ist das Unregister des alten Eintrags gegen das frisch gestartete Backend (erwartbar); nie zwei Listener
  timestamp: 17:12
- hypothesis: Code-Regression aus 1c2b06f..7fc1033
  evidence: dieselben Aufrufe in zwei Reproduktionen 200 (Phase 3 standalone mit 1+2, voller Phase-4-Lauf); keine Exception in den Backend-Logs
  timestamp: 17:12
- hypothesis: PID-Datei zeigt auf uv-Wrapper, kill verfehlt den Listener
  evidence: Listener jeweils binnen 1 s nach kill -TERM weg (16:58:09, 17:02:32, 17:05:27); taskkill-Rückfall vorhanden
  timestamp: 17:12

## Resolution

root_cause: Das ExApp-Backend war in Lauf 3 zweimal ungeplant weg (kein Listener auf 10040, 16:29:49 bis K5-Neustart und 16:33:10 bis 16:37:54); AppAPI antwortet dann 500. Kein Secret-Mismatch, keine Code-Regression. Warum der Prozess endete, ist nicht mehr belegbar: register-exapp.sh überschrieb exapp.log bei jedem Neustart. Folgeschaden: Aufräumen der Phase 2 löschte nur Container/Volume, die Weltzeile blieb, der nächste Boot-Abgleich legte die Welt neu an (Altlast für Folgeläufe).
fix: register-exapp.sh bewahrt das Log des vorigen Backends in .dev/logs (20 Stück) und setzt PYTHONFAULTHANDLER=1; acceptance-phase4.sh räumt Weltreste aller Phasen per API weg und prüft am Ende, dass AppAPI seit Laufbeginn nie "Failed to connect" zur ExApp meldete (mit Positivkontrolle).
verification: voller acceptance-phase4.sh 17:17 bis 17:32 "109 von 109 Prüfungen bestanden", Exit 0 (scratchpad/p4-full5-final.log); Zählung gegen das echte Nextcloud-Log gibt für Lauf 3 189 Treffer und für die gesunden Läufe 0; Commit f6ecfed
files_changed: [scripts/dev/register-exapp.sh, scripts/dev/acceptance-phase4.sh, docs/dev-setup.md]

## Resolution (Owner bestätigt 21.10.2026)

- Keine Code-Regression; Backend-Prozess zweimal weg (AppAPI cURL 7), Ursache offen.
- Absicherung: Log-Archiv .dev/logs/ + faulthandler, Prüfung "kein Failed to connect" in acceptance-phase4.sh (f6ecfed).
- Voller Lauf danach 109/109. Offener Punkt fürs Audit: 500 auf /my/worlds kurz vor dem Ausfall.
