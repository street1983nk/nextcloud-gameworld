---
phase: 06-store-release
plan: 14
subsystem: release
tags: [release-candidate, ghcr, push, owner-gate]
requires: ["06-13"]
provides:
  - "master auf GitHub (30f8758..903d7eb, 153 Commits)"
  - "ghcr.io/street1983nk/gameworld:1.0.0-rc.1 für linux/amd64 und linux/arm64, anonym abrufbar"
affects: [06-15, 06-16]
tech-stack:
  added: []
  patterns:
    - "Vor jedem Push: Trailer-Prüfung (0 Claude-Session-Zeilen), Autor street1983nk, Geheimnis-Suche plus Abgleich mit den echten lokalen Werten"
key-files:
  created:
    - docs/images/gameworld-banner-v1.jpg
  modified:
    - scripts/fetch-games.sh
    - README.md
    - README.de.md
    - README.fr.md
decisions:
  - "Owner Task 1 wörtlich: \"Ok dann hast du mein Go für 6-14\" (= push)"
  - "Owner zum zweiten Push (Build-Fix plus Titelbild): \"Ja, pushen\""
  - "Banner als Titelbild in den drei READMEs (Owner: READMEs, nicht Store)"
  - "Release-Badge bleibt bis v1.0.0 wie es ist (kein weiterer Push ohne Owner-Wort)"
metrics:
  duration: "rc-Build 4 min"
  completed: 2026-10-30
---

# Phase 6 Plan 14: Push und Release-Kandidat 1.0.0-rc.1 Summary

master ist auf GitHub, das Image 1.0.0-rc.1 für amd64 und arm64 liegt öffentlich in ghcr.io.

## Commits

| Schritt | Commit | Betreff |
| ------- | ------ | ------- |
| Push 1 | 30f8758..17b72e0 | 151 Commits seit Phase 5 (vorher 38 Claude-Session-Zeilen entfernt) |
| Build-Fix | 570803b | fix(06-14): fetch VoxeLibre via the ContentDB release link |
| Titelbild | 903d7eb | docs(06-14): banner as title image in the three READMEs |
| Push 2 | 17b72e0..903d7eb | Build-Fix und Titelbild |

## Belege

- Run (grün): https://github.com/street1983nk/nextcloud-gameworld/actions/runs/41023993186
- Index-Digest: sha256:84db978ee8a15bc286a9805d8e0c21be7cb6f605c32205999e6262178c2d25d7
- linux/amd64: sha256:76bca58c25e95e616a5bf1fbb09fc759ed64a820af93a58e9799987698f2666d
- linux/arm64: sha256:60291c2d9e41c15c533d4daaab9204554d310355199b9bf3e021553261e95463
- dazu zwei Attestations (unknown/unknown)
- Anonymer Manifest-Abruf 1.0.0-rc.1: 200; Gegenproben: falscher Tag 404, fremdes Paket 403; anonymer `docker pull --platform linux/amd64` vollständig.

## Abweichungen

- [Rule 3] Lauf 1 (https://github.com/street1983nk/nextcloud-gameworld/actions/runs/41023377522) scheiterte: cdn.content.luanti.org liefert seit 27.10.2026 ein Zertifikat für *.b-cdn.net (curl 60). fetch-games.sh lädt VoxeLibre jetzt über den ContentDB-Release-Link (Weiterleitung auf content.luanti.org/storage); SHA-256 identisch mit SHA256SUMS, frischer Skriptlauf grün.
- [Owner-Regel] 38 ungepushte Commits trugen eine Zeile "Claude-Session:". Vor Push 1 per commit-tree neu gebaut: Baum, Nachricht (ohne die Zeile), Autor und Datum je Commit geprüft, gleich; Sicherung als Zweig backup/vor-trailer-filter-0614.
- Task 3 entfiel: Das Paket war schon öffentlich (anonym 200 vor jeder Owner-Aktion, mit Gegenproben belegt). Die Sichtbarkeit selbst ist per API nicht lesbar (Token ohne read:packages).
- Zusatz auf Owner-Wunsch: Banner als Titelbild der READMEs.

## Geheimnis-Prüfung (T-06-60)

- Muster HP_SHARED_KEY=, APP_SECRET=, BEGIN PRIVATE KEY, APPSTORE_TOKEN, Token-Präfixe, password mit Wert: nur Plantexte, ein Platzhalter (APP_SECRET=local-test) und das Dev-Passwort der lokalen HaRP-Testinstanz (gleiches Muster wie das schon veröffentlichte gameworld-dev-admin).
- Echte lokale Werte (.dev/exapp.secret, .dev/harp.key, Ausschnitt des privaten App-Schlüssels): 0 Treffer in beiden Pushes.

## Self-Check: PASSED
