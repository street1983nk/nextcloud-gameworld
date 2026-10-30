---
phase: 06-store-release
plan: 13
subsystem: store, i18n, ui, backup
tags: [d-09, d-10, d-24, d-25, d-28, screenshots, store-listing, owner-acceptance]
requires: ["06-12", "06-24", "06-27", "06-28"]
provides:
  - "18 Store-Screenshots (6 Motive je DE/EN/FR, -v1), Store-info.xml mit dem englischen Satz"
  - "Owner-abgenommene Store-Texte EN/DE/FR mit Cross-Promo (D-28), Abnahme-Vermerk in docs/store-listing.md"
  - "README.md/.de.md/.fr.md mit eigenem Bildsatz (D-24)"
  - "Forum-Thread-Entwurf docs/forum-thread.md (Owner postet später)"
affects: [06-14, 06-16]
tech-stack:
  added: []
  patterns:
    - "Frontend schickt X-Gameworld-Language mit jeder ExApp-Anfrage; Backend nutzt sie für angemeldete Konten (de/en/fr), sonst die Kontosprache"
    - "Besuchs-Abgleich der Weltenliste läuft neben der Anfrage (höchstens einer, Lifespan wartet kurz und bricht dann ab)"
    - "Sicherungsordner und Zusatz je Kontosprache; Liste und Wiederherstellung durchsuchen alle Sprachordner"
key-files:
  created:
    - .planning/phases/06-store-release/06-13-TASK2-NOTES.md
    - .planning/phases/06-store-release/06-13-TASK3-NOTES.md
    - docs/forum-thread.md
  modified:
    - appinfo/info.xml
    - docs/store-listing.md
    - README.md
    - README.de.md
    - README.fr.md
    - docs/screenshots/*.png
    - frontend/src/views/ParentView.vue
    - frontend/src/api.js
    - frontend/src/backup.js
    - src/gameworld/api/language.py
    - src/gameworld/api/worlds.py
    - src/gameworld/playtime/service.py
    - src/gameworld/backup/naming.py
    - src/gameworld/backup/service.py
decisions:
  - "Owner Task 3 wörtlich: \"Abgenommen\""
  - "Owner Task 4 Texte wörtlich: \"Ok das passt so\" (unverändert, auch die geraden Apostrophe im Französischen)"
  - "Store-Bildsatz: EN"
  - "Forum-Thread: Owner wörtlich \"Thread später\" (Abweichung: info.xml ohne discussion-Element, 06-16 prüft vor dem Tag)"
  - "Sicherungsordner und vor-restore-Zusatz werden übersetzt (Owner: \"Sollen übersetzt werden\")"
  - "Weltentabelle unter 480 px als Karten; Besuchs-Abgleich im Hintergrund; Größen unter 1 MB in KB (Owner-Entscheide 30.10.)"
  - "Luanti 5.18.0 (stabil seit 29.10.): Wechsel später, nicht Teil von v1 (Owner)"
metrics:
  duration: "Abnahme 30.10.2026 vormittags"
  completed: 2026-10-30
---

# Phase 6 Plan 13: Store-Bilder, Store-Texte und gemeinsame Owner-Abnahme Summary

Die Store-Unterlagen sind vom Owner abgenommen: 18 Bilder, dreisprachige Texte mit Cross-Promo, README-Bilder; die Abnahme der Oberfläche hat neun Produktfehler gefunden, alle behoben.

## Commits

| Task | Commit | Betreff |
| ---- | ------ | ------- |
| 1 | 62986d6 | feat(06-13): Demo-Daten-Skript und Store-Screenshot-Vorschlag |
| 2 | fd91e66, a230442, 95ea205, 2084df0, 088beee, 2950e21 | Tabellen-Fix, Namensregel EN/FR, Demo/Aufnahme je Sprache, Bilder, Sprachzeilen und Thread-Entwurf, Notizen |
| 3 | ee503ec, 8eb994c, 460f8b0, a324c21, 8007712, 09a26aa, a8a8d64, 3ef6a1b, de2eaf1, a243710 | Fixes aus der Abnahme, Bilder neu, Notizen |
| 4 | 1a7cc43 | Store-Texte freigegeben, EN-Bildsatz, README-Bilder |

## Owner-Abnahme

- Task 3 (B1 bis B4, Sprachen, 390 px, Bilder): "Abgenommen". Ablauf je Schritt in 06-13-TASK3-NOTES.md.
- Task 4 (Texte, Cross-Promo, Bildsatz, Thread): "Ok das passt so", Bildsatz EN, "Thread später".

## Abweichungen

- [Rule 1] Sprachauswahl in der Weltentabelle abgeschnitten, auch in den Store-Bildern (ee503ec).
- [Rule 1] Servertexte bis 30 s nach einem Sprachwechsel in der alten Sprache (Rollen-Cache) (8eb994c).
- [Rule 1] pydantic- und Starlette-Meldungen englisch für de/fr-Konten (460f8b0). Owner: Sprachfehler sind ein No-Go.
- [Rule 1] Spielzeitliste rund 12 s für einen Verwalter ohne Admin-Rechte (a324c21) und Weltenliste rund 7 s durch den Besuchs-Abgleich (8007712, Owner-Entscheid).
- [Rule 1] Weltentabelle scrollte bei 390 px waagerecht, seit Phase 3 (09a26aa, Owner-Entscheid Kartenansicht).
- [Owner] Sicherungsordner und Zusatz je Kontosprache (a8a8d64), Größen unter 1 MB in KB (3ef6a1b).
- Thread später: kein discussion-Element in info.xml (siehe Entscheidungen).
- tests/test_docs.py prüft statt des Entwurfs-Markers jetzt den datierten Abnahme-Vermerk.

## Verifikation

- Sprachprüfung aller Ansichten und Dialoge als admin, gw-lehrer und mia in de/en/fr (71 Punkte, Wortdetektor aus den Wörterbüchern mit Positivkontrolle), dazu Stichproben gelesen.
- Jede Änderung mit Gegenprobe gegen den alten Code (Tests rot ohne die Änderung).
- Live gemessen als gw-lehrer: Weltenliste 0,8 bis 2 s (vorher 7 s), Spielzeitliste 2,1 s (vorher 12 s).
- 390 px in de und fr: kein Element breiter als der Bildschirm; 1280 px unverändert.
- Alle 18 Bilder gesichtet: nur Demo-Daten, Passwörter verdeckt, Spieleradresse nextcloud.example.org.
- Gates: ruff, ruff format, pyright (latest), vulture grün; pytest -m "not docker": 2907 passed, 52 deselected (417 s, Stand 1a7cc43).

## Für den Volltest vor dem Release (Owner 30.10.)

- Luanti-Client-Begriffe der Kinderanleitung in de/fr mit echtem Client prüfen
- Erwachsen-Marke hinkt 1 bis 2 s nach dem Umschalten
- Talk-Hinweis Ex-Verwalter erscheint erst nach Neuladen

Aufgeräumt: Kontosprache von gw-lehrer wieder ungesetzt (wie vor der Abnahme), admin steht auf de.

## Self-Check: PASSED
