---
phase: 02-one-click-welten
plan: 02
subsystem: vendor-games
tags: [voxelibre, vendor, sha256, licensing]
requires: []
provides:
  - "scripts/fetch-games.sh: hash-geprüfter, idempotenter Abruf von vendor/games/mineclone2-39534.zip"
  - "SHA256SUMS-Eintrag für VoxeLibre 0.92.4"
affects: [02-03]
tech-stack:
  added: []
  patterns: ["Download in .part, Hash-Prüfung, atomares mv", "Hash nur in SHA256SUMS, Skript liest ihn per grep"]
key-files:
  created: [scripts/fetch-games.sh]
  modified: [vendor/games/SHA256SUMS, vendor/games/README.md, .gitignore, scripts/dev/register-exapp.sh, docs/dev-setup.md]
decisions:
  - "02-02: VoxeLibre-Zip (84 MB) nicht im Git, Abruf per scripts/fetch-games.sh gegen SHA256SUMS; register-exapp.sh ruft es vor Frontend-Build und Backend-Start"
  - "02-02: Offline-Variante über GAMEWORLD_GAME_SOURCE_DIR, Prüfsumme wird auch dann geprüft"
metrics:
  duration: 10 min
  completed: 2026-10-19
  tasks: 2
  files: 6
---

# Phase 02 Plan 02: VoxeLibre hash-geprüft bereitstellen Summary

VoxeLibre 0.92.4 (ContentDB-Release 39534) wird per POSIX-sh-Skript mit curl (nur HTTPS, TLS 1.2+) in eine .part-Datei geladen, gegen den SHA256 aus vendor/games/SHA256SUMS geprüft und erst dann atomar als vendor/games/mineclone2-39534.zip abgelegt; das Dev-Setup holt es automatisch, das Zip bleibt außerhalb des Git.

## Tasks

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Hash-geprüftes Fetch-Skript, Prüfsumme, Lizenzdoku, gitignore | 0454205 | scripts/fetch-games.sh, vendor/games/SHA256SUMS, vendor/games/README.md, .gitignore |
| 2 | Abruf im Dev-Setup verdrahten und dokumentieren | 3bc067d | scripts/dev/register-exapp.sh, docs/dev-setup.md |

## Verifikation

- Erster Lauf: Download in 19 s, "abgelegt und geprüft"; zweiter Lauf: "vorhanden und geprüft", beide Exit 0
- `sha256sum -c SHA256SUMS`: beide Spiele OK; `git check-ignore` trifft die Zip, `git ls-files vendor/games` listet sie nicht
- Negativkontrolle (Kopie mit angehängtem Byte über GAMEWORLD_GAME_SOURCE_DIR, Ziel vorher umbenannt): Exit 1, "Prüfsumme von mineclone2-39534.zip stimmt nicht, Datei verworfen", keine Zieldatei und keine .part-Datei übrig; Zustand danach wiederhergestellt
- Hash zählt in SHA256SUMS 1 Treffer, im Skript 0 (wird aus SHA256SUMS gelesen)
- README nennt GPL-3.0-or-later und CC-BY-SA-4.0; keine En-/Em-Dashes in den geänderten Dateien
- `sh scripts/dev/register-exapp.sh` (Exit 0, "vorhanden und geprüft", Backend wiederverwendet) und `sh scripts/dev/smoke.sh` ("Durchstich erfolgreich") grün; Dev-Stack läuft weiter

## Deviations from Plan

None - plan executed exactly as written. Der Aufruf von fetch-games.sh steht vor dem Frontend-Build (und damit vor dem Backend-Start), wie im read_first des Plans genannt.

## Hinweise für 02-03

- Die Konstante für den VoxeLibre-Hash in `src/gameworld/provisioner/presets.py` existiert noch nicht; README verweist bereits darauf, 02-03 legt sie an.

## Self-Check: PASSED

- FOUND: scripts/fetch-games.sh, vendor/games/mineclone2-39534.zip (lokal, ignoriert)
- FOUND: 0454205, 3bc067d
