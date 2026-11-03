---
phase: 06-store-release
plan: 16
subsystem: store-release
tags: [store-upload, certificate, signing, release]
requires: ["06-15"]
provides:
  - "Gameworld im Nextcloud App Store: App-ID registriert, Releases 1.0.0 und 1.0.1 (je HTTP 201)"
  - "Installation aus dem Store auf einer Test-Nextcloud mit HaRP belegt (ohne --info-xml)"
key-files:
  created:
    - docs/release-notes/1.0.0.md
    - docs/release-notes/1.0.1.md
  modified:
    - docs/store-listing.md
    - docs/forum-thread.md
    - appinfo/info.xml
decisions:
  - "Owner 03.11.2026: 1.0.0 ohne discussion-Link ('Wir warten nicht'), Link kam mit 1.0.1 (D-28-Abweichung für 1.0.0)"
  - "Owner 03.11.2026: Submit-Weg 'local' (curl vom Owner-Rechner), Token in ~/.nextcloud/appstore_token, nie ausgegeben"
  - "Owner 03.11.2026 (1.0.1): Banner als erstes Store-Bild, 'Was Gameworld kann' vor den Privilegien, kein Satz zu den Schwester-Apps"
completed: 2026-11-03
---

# 06-16: Store-Release

## Ergebnis

Gameworld ist aus dem Nextcloud App Store installierbar (PLATT-01).

| Schritt | Beleg |
|---|---|
| Zertifikat | nextcloud/app-certificate-requests#1364, state MERGED, mergedAt 2026-11-02T17:02:06Z (nur gelesen); CN=gameworld bis 2037, Modulus passt zum Schlüssel (Hash-Vergleich) |
| 1.0.0 | PR #2, Tag v1.0.0 (11e68e6), Run 41603501299, Asset 17933 B, Digest sha256:90810bc2..., Registrierung HTTP 201, Release HTTP 201 |
| 1.0.1 | PR #3, Tag v1.0.1 (2308e10), Run 41628531751, Asset 17903 B, Digest sha256:7e40408a..., Release HTTP 201 |
| Store-Seite | https://apps.nextcloud.com/apps/gameworld 200, Banner als Hauptbild (Spiegel 225330 B = Quelle), Discussion-Link, neue Beschreibung; Kategorie Spiele Platz 1 nach Wichtigkeit |
| Katalog | /api/v1/appapi_apps.json führt 1.0.1 und 1.0.0 (ExApps stehen nicht in apps.json) |
| Store-Installation | Test-Nextcloud 34.0.3 mit harp_dev (harp-install.sh --source ghcr --tag 1.0.1), dann unregister und `app_api:app:register gameworld harp_dev --env GAMEWORLD_DOCKER_URL=tcp://gameworld-docker-proxy:2375 --wait-finish` ohne --info-xml: "ExApp gameworld deployed successfully", app:list `gameworld (Gameworld): 1.0.1 [enabled]`, Container ghcr.io/street1983nk/gameworld:1.0.1 als 10001:10001, appdata/appstore/appapi_apps.json vom Store geladen |

## Abweichungen

- D-28 für 1.0.0: ohne discussion-Link getaggt, Owner-Entscheid wörtlich "Wir warten nicht"; seit 1.0.1 drin.
- Store-POSTs, Tag-Push und PR-Merge blockt der Auto-Mode-Classifier; der Owner hat sie selbst ausgeführt (submit.sh im Scratchpad, PowerShell ohne &&).
- Volle pytest-Suite für 1.0.1 zweimal wegen RAM-Mangel abgebrochen; gezielt 241 Tests grün (nur info.xml, Doku, Tests geändert, kein App-Code).
- Store-Installation auf der Dev-Nextcloud 8091 statt dessen auf dem HaRP-Teststack 8093, weil nur dieser einen HaRP-Daemon hat.

## Kein Geheimnis in Belegen

Token und Schlüssel nie ausgegeben; submit.sh zeigt nur HTTP-Codes und Antwortkörper.
