---
phase: 06-store-release
plan: 11
subsystem: docs, store-listing
tags: [docs, privacy, store-listing, i18n, readme, d-09, d-11, d-12, d-24]
requires: ["06-04", "06-06", "06-07", "06-09", "06-10"]
provides:
  - "docs/privacy.md (EN) und docs/privacy.de.md: Privilegien-Abschnitt zuerst, gespeicherte Daten, nie, Kontrolle, Löschen, Aufbewahrung"
  - "docs/install.md (EN, Hauptfassung) und docs/install.de.md: 13 Abschnitte gleicher Nummerierung, Anker setup-check und cleanup"
  - "README.md (EN), README.de.md, README.fr.md: Sprachverweis, shields.io-Badges, Faktenliste, byte-identisches Mermaid-Diagramm, Screenshots-Platzhalter"
  - "docs/store-listing.md: eine wortgleiche Quelle der neun Store-Texte, Was bewusst nicht drinsteht, Abnahme: offen"
  - "appinfo/info.xml: name/summary/description EN/DE/FR, documentation, category games+tools, sechs -v1-Screenshots"
  - "tests/test_docs.py (neu), tests/test_info_xml.py (erweitert)"
affects: [06-12, 06-13, 06-16]
tech-stack:
  added: []
  patterns:
    - "Store-Texte aus store-listing.md per Skript in info.xml übernommen, Test prüft Wortgleichheit"
    - "Doku-Anker per URL-Konstanten aus Code (setup_check.DOCS_URL, orphans.js CLEANUP_DOCS_URL) getestet"
    - "Sonderzeichen in Tests nur per chr(), nie als Literal (RUF001, Owner-Typografie)"
key_files:
  created:
    - docs/privacy.md
    - docs/privacy.de.md
    - docs/install.de.md
    - README.md
    - README.de.md
    - README.fr.md
    - docs/store-listing.md
    - tests/test_docs.py
  modified:
    - docs/install.md
    - appinfo/info.xml
    - tests/test_info_xml.py
decisions:
  - "HaRP-Compose nutzt HP_SHARED_KEY_FILE mit Compose-Secret (im HaRP-README belegt) statt Klartext-Schlüssel"
  - "install.md bekommt 13 Abschnitte: Store-Installation (1), Deploy-Daemon mit 3a Compose/3b AIO/3c Host-Netz-Warnung, Setup-Check 7, Updates in 8, Aufräumen 13"
  - "Setup-Check-Tabelle der EN-Fassung zeigt die deutschen Meldungen wörtlich plus ID und englische Bedeutung (Oberfläche nur Deutsch)"
  - "Neuinstallation: Spielpasswörter ändern sich auch ohne Daten-Löschen, weil AppAPI die ExApp-Konfiguration beim Deinstallieren löscht (RESEARCH 6.1); Text entsprechend korrigiert"
  - "Store-Beschreibung ohne Backticks und Tabellen (Store-Markdown-Teilmenge), per Test gesichert; dazu Element-Reihenfolge nach info.xsd als Test"
  - "README-Badges: image.yml-Status, GitHub-Release, Lizenz AGPL--3.0--or--later, Nextcloud-32--35 (shields.io)"
metrics:
  duration: "ca. 60 min"
  completed: "2026-10-24"
  tasks: 3
  files: 11
---

# Phase 6 Plan 11: Öffentliche Doku und dreisprachiges Store-Listing Summary

privacy.md/install.md als englische Hauptfassungen mit deutschen Fassungen, dreisprachige README mit Badges und Mermaid-Diagramm sowie ein ehrliches EN/DE/FR-Store-Listing (Privilegien zuerst, "Interface: German", Deinstallation lässt Volumes und Sicherungen) als Entwurf in docs/store-listing.md und wortgleich in info.xml.

## Tasks

| Task | Name | Commits | Dateien |
|------|------|---------|---------|
| 1 | privacy.md und privacy.de.md | 6fc5a32 | docs/privacy.md, docs/privacy.de.md |
| 2 | install.md (EN), install.de.md, README EN/DE/FR | b83b508 | docs/install.md, docs/install.de.md, README.md, README.de.md, README.fr.md |
| 3 | store-listing.md, info.xml-Texte, Doku-Tests | 5f5b49c (RED), 3b8c189 (GREEN) | tests/test_docs.py, tests/test_info_xml.py, docs/store-listing.md, appinfo/info.xml |

## Was gebaut wurde

- **privacy.md/privacy.de.md** (169/172 Zeilen): Kurzfassung, dann "What this app may do and why" mit Flag-Tabelle (CONTAINERS, IMAGES, POST, VOLUMES = 1, Rest 0), ehrlichem root-gleichen Restrisiko, gemeinsamem Netz (nextcloud-aio, andere ExApps), UDP nur Heimnetz, uid 10001, gehärteten Welt-Containern (AR-23-Stand); Datentabelle aus dem echten Schema (worlds, invites, players, world_access, adults, verwalter_seen, talk_rooms, backups, ...); nie/Kontrolle/Löschen (purge nur nach Besuch eines NC-Admins, D-17, D-15, Orphan-Liste, gameworld-orphans.sh); Aufbewahrung.
- **install.md/install.de.md** (je 428 Zeilen, gleiche Gliederung): git mv des deutschen Stands nach install.de.md, dann aktualisiert; EN neu übersetzt. Store-Installation, HaRP-Compose (Netz gameworld, Proxy ohne Host-Port, HP_SHARED_KEY_FILE), AIO-Snippet (nextcloud-aio external, harp_aio), Host-Netz nur mit Loopback und Warnung, Restrisiko gemeinsames Netz, AR-23-Härtung (bestehende Welten: Sicherung plus Wiederherstellen), Anker setup-check mit neuen Zeilen proxy_dns/proxy_timeout/proxy_refused/docker_url_socket/docker_url_exposed, D-17 unter "Deaktivieren und Updates", Verwalter-Gruppen mit Einladungsgrenze und Kinder-Warnung, Erwachsen-Schalter (was er tut, was nie), Talk-Übernahme samt "Raum neu anlegen" und occ talk:room:delete, Anker cleanup mit Skript-Download-URL, Optionen und Warnung zu --remove-volumes.
- **README.md/.de.md/.fr.md**: Sprachverweis in Zeile 1 (English | Deutsch | Français), vier shields.io-Badges, Faktenliste inkl. "Interface: German", Abschnitt Privilegien, identischer Mermaid-flowchart (Browser and Luanti client, Nextcloud mit AppAPI und Files, HaRP, ExApp uid 10001, docker-socket-proxy, Docker engine, Welt-Container), "## Screenshots" mit Hinweis auf die Store-Abnahme, Installation, Doku-Links (FR auf englische Fassungen), Lizenz.
- **docs/store-listing.md**: Regeln, feste Felder (Kategorien, Doku, 6 Screenshot-Namen), neun Texte in Codeblöcken, "Was bewusst nicht drinsteht" (kein Internet-Spiel-Versprechen, kein Minecraft, keine weiteren Oberflächensprachen, keine Image-Sichtbarkeit, keine ungemessenen Zahlen, kein Panel-Vergleich), "Abnahme: offen (Owner-Abnahme in 06-13, vor dem Tag v1.0.0)".
- **info.xml**: Texte per Skript aus store-listing.md übernommen; documentation user/admin install.md, developer dev-setup.md; category games, tools; sechs Screenshots; keine Zeichenfolge public/announce.

## Verifikation

- `uv run pytest -q tests/test_info_xml.py tests/test_docs.py`: 58 passed (RED vorher: 11 failed, 45 passed).
- `uv run pytest -m "not docker" -q`: 2587 passed, 44 deselected, 1 warning.
- ruff check, ruff format --check (196 Dateien), pyright latest 0 Fehler, vulture: ohne Befund.
- Gedankenstrich-Prüfung U+2013/U+2014 über alle docs/*.md und README*: ok; Emoji-Regex mit Positivkontrolle (U+1F600, U+2705 erkannt, Umlaute und Akzente nicht).
- Mermaid-Blöcke der drei README byte-identisch (Test test_readme_mermaid_identical).
- Gegenprüfung gegen die echte Store-XSD (raw.githubusercontent.com/nextcloud/appstore/.../info.xsd): Element-Reihenfolge, category games und tools erlaubt, documentation user/admin/developer, screenshot secure-url; ohne lxml/xmllint keine Vollvalidierung, Reihenfolge per Test gesichert.
- `grep -ci "public\|announce" appinfo/info.xml`: 0.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Falsche Aussage zur Neuinstallation in install.md**
- **Found during:** Task 2
- **Issue:** Bisheriger Text sagte, Spielpasswörter ändern sich nur bei Entfernen "mit Daten". Laut RESEARCH 6.1 löscht AppAPI die ExApp-Konfiguration (und damit das Geheimnis) bei jeder Deinstallation.
- **Fix:** Randfall-Text in beiden Fassungen korrigiert, Abschnitt 13 verweist darauf.
- **Commit:** b83b508

**2. [Rule 1 - Bug] Veralteter Satz zum Talk-Besitzer**
- **Found during:** Task 2
- **Issue:** "Wer einen Talk-Raum angelegt hat, bleibt als Besitzer gespeichert" widersprach der Übernahme (D-16).
- **Fix:** Umformuliert auf das handelnde Besitzerkonto mit Verweis auf den Übernahme-Abschnitt; Pause und Zeitfenster nennen zusätzlich als erwachsen markierte Konten.
- **Commit:** b83b508

**3. [Rule 2 - Korrektheit] Zusätzliche Tests über den Plan hinaus**
- Element-Reihenfolge nach info.xsd, Längen name/summary <= 128, Store-Markdown-Teilmenge (keine Backticks, keine Tabellen), Wortgleichheit store-listing.md und info.xml, relative Links samt Anker in allen öffentlichen Docs, gleiche Gliederung install.md/install.de.md.
- **Commit:** 5f5b49c

**4. Abschnittsnummern geändert**
- install.md hat jetzt 13 statt 11 Abschnitte (Store-Installation und Aufräumen neu, Deploy-Daemon erweitert). Setup-Check ist jetzt Abschnitt 7. Code verweist nur per Anker, daher ohne Folgen.

## TDD Gate Compliance

RED 5f5b49c (`test(06-11)`, 11 Tests rot), GREEN 3b8c189 (`feat(06-11)`, 58 passed). Kein REFACTOR nötig.

## Known Stubs

- README*.md "## Screenshots": Platzhalter-Hinweis; die sechs -v1-Bilder folgen in 06-13 (geplant, D-24).
- info.xml-Screenshot-URLs zeigen auf docs/screenshots/*-v1.png, die es noch nicht gibt; 06-13 legt sie mit genau diesen Namen an.

## Threat Flags

Keine neuen Angriffsflächen (nur Doku und Manifest-Texte). T-06-48 (Privilegien zuerst, Test je Sprache), T-06-49 (Snippets ohne Host-Port, Host-Netz-Warnung, Setup-Check-Tabelle), T-06-50 (test_docs koppelt DOCS_URL und CLEANUP_DOCS_URL an die Anker), T-06-51 (Deinstallation wörtlich: Volumes und Sicherungen bleiben, Test prüft gameworld-orphans.sh je Sprache) umgesetzt.

## Offen für 06-13

- Owner-Abnahme der neun Store-Texte in docs/store-listing.md (Vermerk "Abnahme: offen"), danach Vermerk datieren.
- Screenshots unter den sechs festen Namen aufnehmen und README-Platzhalter ersetzen.

## Self-Check: PASSED

- FOUND: docs/privacy.md, docs/privacy.de.md, docs/install.md, docs/install.de.md, README.md, README.de.md, README.fr.md, docs/store-listing.md, tests/test_docs.py
- FOUND: 6fc5a32, b83b508, 5f5b49c, 3b8c189
