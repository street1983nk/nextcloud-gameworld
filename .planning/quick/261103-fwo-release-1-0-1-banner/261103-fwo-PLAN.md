---
quick_id: 261103-fwo
slug: release-1-0-1-banner
date: 2026-11-03
---

# Release 1.0.1: Banner als Store-Titelbild

Owner 03.11.2026: "Das ist das falsche Bild". Der Store zeigt den ersten `<screenshot>` als Titelbild; in 1.0.0 war das die Weltliste, das Banner `docs/images/gameworld-banner-v1.jpg` fehlte in der info.xml.

## Tasks

1. Banner als ersten `<screenshot>` in `appinfo/info.xml`, Test `test_banner_then_six_versioned_screenshots`.
2. Version 1.0.1 im Gleichschritt: info.xml `<version>` und `<image-tag>`, pyproject, uv.lock, Lockstep-Test.
3. `docs/release-notes/1.0.1.md` (englische Faktenliste), `docs/store-listing.md` Feste Felder.
4. PR, Merge, Tag v1.0.1 (Owner pusht), image.yml, Signatur über das heruntergeladene Asset, Release-Upload (Owner startet submit, 201 erwartet; keine Registrierung mehr nötig).

Ohne discussion-Link: Forum-Thread noch in Moderation.
