---
phase: 03-zugang-und-rollen
plan: 07
subsystem: acceptance, docs
tags: [acceptance, phase-gate, playwright, prober, docs]
requires:
  - phase: 03-zugang-und-rollen
    provides: 03-01 bis 03-06 (Welt-Mod gameworld_access, Rollen, abgeleitete Spielpasswörter, Gruppen, Eltern-UI, Kind-Ansicht)
provides:
  - scripts/dev/acceptance-phase3.sh (K1 bis K5 plus Regression Phase 1 und 2, 75 Prüfungen)
  - CLI des UDP-Probers (uv run python -m tests.e2e.luanti_probe HOST PORT NAME [PASSWORT], JSON)
  - docs/install.md Abschnitt 8 "Zugang, Rollen und Spielpasswörter" inklusive Neuinstallations-Randfall
  - docs/dev-setup.md Abschnitt "Phasenabnahme Phase 3"
  - CLAUDE.md und .planning/research/STACK.md ohne ct_whitelist-Empfehlung
affects: [phase-3-verification, 04-spielzeitlimits]
tech-stack:
  added: []
  patterns:
    - "Abnahme unabhängig vom Implementierungsmuster: docker-CLI, curl über den AppAPI-Proxy mit echten Konten, jq, tar, grep; Python nur als Prober-CLI und lesend über die Standardbibliothek"
    - "Spielpasswörter nur als Muster, Länge oder sha256-Vergleich in Ausgaben"
key-files:
  created:
    - scripts/dev/acceptance-phase3.sh
  modified:
    - tests/e2e/luanti_probe.py
    - docs/install.md
    - docs/dev-setup.md
    - CLAUDE.md
    - .planning/research/STACK.md
key-decisions:
  - "03-07: Owner-Abnahme Phase 3 am 20.10.2026 per gemeinsamer Playwright-Abnahme erteilt (Verdict 'Abgenommen'); acceptance-phase3.sh 75/75 dreimal, Regression Phase 1 84/84 und Phase 2 104/104"
  - "03-07: A6 Anleitungstexte der Kind-Ansicht 'Ja, übernehmen'; A8 Adresse aus dem Browser-Hostnamen, Warnung nur bei Loopback 'Ja, bestätigt'; A9 Kindertexte im Spiel 'Ja, übernehmen'"
  - "03-07: Offen fürs Phasen-Audit: Live-Join mit echtem Luanti-Client und Kick nach Widerruf (A7) mit echtem Client"
requirements-completed: [ZUGANG-02, ZUGANG-03, ZUGANG-04, ROLLE-01, ROLLE-02]
metrics:
  duration: 120 min (inklusive Owner-Abnahme)
  completed: 2026-10-20
---

# Phase 3 Plan 07: Phasenabnahme Zugang und Rollen Summary

**acceptance-phase3.sh belegt alle fünf Erfolgskriterien gegen den echten Dev-Stack: per UDP-Prober wird ein Fremder abgewiesen und das eingeladene Kind mit den Daten aus Nextcloud eingelassen. Rollen kommen aus der Nextcloud-Gruppe admin, und Spielpasswörter liegen nirgends gespeichert. Der Owner hat Eltern- und Kind-Sicht gemeinsam per Playwright abgenommen.**

## Performance

- Duration: rund 120 min, davon die gemeinsame Owner-Abnahme
- Completed: 2026-10-20
- Tasks: 2 (1 auto, 1 Checkpoint human-verify)
- Files: 6 (1 neu, 5 geändert)

## Accomplishments

- `scripts/dev/acceptance-phase3.sh` (POSIX sh, Marker `# K1` bis `# K5`, trap räumt Welt, Gruppe `gw-familie`, Konto `gw-abnahme2`, join_host und gw-kind-in-admin in jedem Fall auf):
  - K1: Benutzer und Gruppe einladen, Muster für Name und Passwort, `via group:gw-familie`, 422 für unbekanntes Konto. Zugangsdatei per `docker cp` geprüft: Kopf, `end`, beide Namen, `-r--r--r-- 0/0`, kein Klartext-Passwort.
  - K2: Prober "Fremder" wird abgelehnt mit "nicht eingeladen", gw-kind kommt rein (`auth_accept`), falsches Passwort ergibt `WRONG_PASSWORD`. Nach dem Entfernen wird gw-kind abgelehnt. Nach der Rotation gilt das alte Passwort nicht mehr, das neue schon, ohne Neustart (StartedAt gleich). Der Proxy antwortet auf `/exec` weiter mit 403.
  - K3: `/my/worlds` liefert genau die eigene Welt. Port stimmt mit `docker port` überein, Name und Passwort mit der Verwalter-Ansicht, Join mit diesen Daten gelingt. join_host wird übernommen, `http://x` ergibt 422.
  - K4: Seite und Bundle 200 für gw-kind, fünf Verwaltungsaufrufe nicht 200 (404). Keine fremden Zugänge in der Kind-Antwort; Positivkontrolle über die Verwalter-Antwort.
  - K5:
    - Rolle spieler bzw. verwalter, Hin- und Rückweg über die Gruppe admin mit 35 s Cache-Wartezeit.
    - Spalten von `players` genau nc_user, player_name, rotation.
    - Passwörter nicht in der SQLite-Datei, Spielername schon.
    - Nach ExApp-Neustart gilt dasselbe Passwort (Join gelingt).
    - Statisch: keine eigene Kontenverwaltung.
- Prober-CLI: `main()` mit argparse und JSON auf stdout, druckt nie das Passwort, Timeout und Netzfehler ergeben `{"result":"timeout"}`.
- Doku:
  - install.md: Abschnitt 8 mit Rollen, Join-Schutz und Spielpasswörtern (abgeleitet, nicht gespeichert, "Neues Passwort" sofort wirksam, Updates behalten das Geheimnis, Randfall Neuinstallation), Adresse für Spieler, UDP im Heimnetz, kein Internet ohne VPN, ältere Welten brauchen einen Neustart.
  - dev-setup.md: Abnahme Phase 3.
- CLAUDE.md und STACK.md: Die sechs ct_whitelist-Zeilen sind durch den Welt-Mod gameworld_access ersetzt, jeweils mit dem Hinweis "ct_whitelist auf ContentDB nicht mehr auffindbar (19.10.2026), siehe 03-RESEARCH.md". `content.luanti.org` bleibt stehen, die Positivkontrolle in acceptance-phase2.sh braucht es.

## Task Commits

1. Task 1: add phase 3 acceptance script and access docs, `1aa3c4c`
2. Task 2: Owner-Abnahme (keine Codeänderung)

## Verification

- `sh scripts/dev/acceptance-phase3.sh`: dreimal Exit 0 mit "75 von 75 Prüfungen bestanden" (zweimal vor, einmal nach der Owner-Abnahme). Darin jedes Mal Regression acceptance-phase1.sh 84/84 und acceptance-phase2.sh 104/104.
- Mustersuche nach Spielpasswörtern in allen drei Lauf-Logs: 0 Treffer.
- ruff, ruff format, pyright (latest, 0 Fehler), vulture grün; `uv run pytest -q` 590 passed.
- `grep -c '^# K[1-5]'` = 5; keine U+2013/U+2014 in Skript und Doku.
- Nach dem Lauf: keine Container mit `gameworld.managed=true`, join_host leer, gw-kind nicht in admin, gw-familie und gw-abnahme2 gelöscht, Backend-Heartbeat ok.

## Owner-Abnahme (Task 2)

Verdict des Owners: **"Abgenommen"**. Die Schritte 1 bis 8 und 11 liefen per Playwright komplett grün.

Owner-Entscheide wörtlich:
- **A6** Anleitungstexte und Menübeschriftungen der Kind-Ansicht: "Ja, übernehmen". Die Texte bleiben wie gesehen: "Meine Welten", "So kommst du in die Welt", 5 Schritte, "Ändere dein Passwort bitte nicht im Spiel".
- **A8** Adress-Vorgabe aus dem Browser-Hostnamen ohne Einstellung, Warnung nur bei Loopback: "Ja, bestätigt".
- **A9** Kindertexte im Spiel (abgelehnter Join "Du bist in diese Welt nicht eingeladen. Frag deine Eltern.", Widerruf-Kick, Sperrtext): "Ja, übernehmen".

Beobachtet:
- Passwort-Rotation mit Warnhinweis. Altes und neues Passwort waren im Browser sichtbar; sie werden hier bewusst nicht protokolliert.
- `/api/worlds` als gw-kind ergab 404, `/api/me` die Rolle "spieler".
- `/api/my/worlds` lieferte nur die eigene Welt, mit dem rotierten Passwort und Host 192.168.178.20.
- Nach dem Entfernen: "Du bist noch zu keiner Welt eingeladen".
- Welt-Löschung mit Bestätigungsdialog, danach keine Welt-Container (nur gameworld-dev-app-1 und docker-proxy-1).
- Die join_host-Einstellung aus der Abnahme (192.168.178.20) hat der anschließende Abnahmelauf wieder auf leer gesetzt.

Screenshots:
- C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\26f83d85-f123-49b7-b92a-20e75304acd7\scratchpad\abnahme3-01-startseite.png
- C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\26f83d85-f123-49b7-b92a-20e75304acd7\scratchpad\abnahme3-03-einladen-dialog.png
- C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\26f83d85-f123-49b7-b92a-20e75304acd7\scratchpad\abnahme3-04-spieler-dialog.png
- C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\26f83d85-f123-49b7-b92a-20e75304acd7\scratchpad\abnahme3-04b-umbenennen-warnung.png
- C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\26f83d85-f123-49b7-b92a-20e75304acd7\scratchpad\abnahme3-05-einstellungen.png
- C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\26f83d85-f123-49b7-b92a-20e75304acd7\scratchpad\abnahme3-06-kind-ansicht.png
- C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\26f83d85-f123-49b7-b92a-20e75304acd7\scratchpad\abnahme3-08-kind-ohne-einladung.png

## Offen für das Phasen-Audit

- **Live-Join mit echtem Client:** Auf dieser Maschine ist kein Luanti-Client installiert. Belegt ist der Join nur per UDP-Prober (MTP plus SRP wie der echte Client).
- **Kick nach Widerruf (A7):** Laufende Spieler trennt der Mod im 5-s-Takt. Das ist mit einem echten, eingeloggten Client noch nicht beobachtet.
- **Randfall Neuinstallation der Spielpasswörter:** Bei kompletter Neuinstallation der ExApp (mit Daten) entsteht ein neues Geheimnis. Alle Spielpasswörter ändern sich dann einmalig, Gameworld schreibt die neuen Zugänge automatisch in alle Welten. Das ist in docs/install.md dokumentiert, aber nicht live durchgespielt; ExApp-Updates behalten das Geheimnis (live belegt in K5).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blockierend] sqlite3 nicht installiert**
- Found during: Task 1
- Issue: Der Plan sah `sqlite3 ... "PRAGMA table_info(players)"` vor; auf dieser Maschine gibt es kein sqlite3.
- Fix: Das Skript nutzt sqlite3, wenn vorhanden, sonst die Python-Standardbibliothek (`uv run python -I`, `mode=ro`), unabhängig vom ExApp-Code.
- Commit: 1aa3c4c

**2. [Ergänzung] GAMEWORLD_SKIP_REGRESSION=1**
- Für schnelle Iterationen ohne Regression. Ein so gekürzter Lauf zählt bewusst als Fehlschlag (Exit 1), kann also nie als Abnahme durchgehen. Dokumentiert in dev-setup.md.

**3. [Ergänzung] Zusätzliche Kontrollen**
- Positiv-Join von gw-abnahme2 vor der Rotation, Join mit den Daten aus `/my/worlds`, Join nach dem ExApp-Neustart, join_host bleibt nach dem 422, Positivkontrolle `occ user:info`.

## Known Stubs

Keine.

## Threat Flags

Keine neuen Flächen. T-03-45 (keine Passwörter in Ausgaben, per Mustersuche belegt), T-03-46 (trap und Abschlussprüfung "gw-kind nicht in admin") und T-03-48 (blockierender Checkpoint, Owner-Antwort wörtlich oben) sind umgesetzt.

## Self-Check: PASSED

- scripts/dev/acceptance-phase3.sh, docs/install.md, docs/dev-setup.md, tests/e2e/luanti_probe.py vorhanden
- Commit 1aa3c4c vorhanden
- alle sieben Screenshot-Dateien im Scratchpad vorhanden
