# Beleg 04: Gerätetest Einzelspieler (Plan 04.2-04, Task 2 und 3)

Builds aus Lauf 39909473743 (bc0a515, Luanti 5.17.0): a = Release 0083d7819fd7 (1,875 GiB fest, Pool 22), b = Release 5b1532c2ce14 (768 MiB bis 1 GiB, Pool 12). Details in 04-ci-build.md.

## Gerätematrix

| Gerät | Browser und Version | Build | crossOriginIsolated | JSPI | Zeit bis Menü in s | Zeit bis Welt in s | RAM | FPS | Touch | Fehler |
|-------|---------------------|-------|---------------------|------|--------------------|--------------------|-----|-----|-------|--------|
| Entwicklungsrechner | ausstehend (Owner) | a | ausstehend | ausstehend | ausstehend | ausstehend | ausstehend | ausstehend | nicht zutreffend | ausstehend |
| Entwicklungsrechner | ausstehend (Owner) | b | ausstehend | ausstehend | ausstehend | ausstehend | ausstehend | ausstehend | nicht zutreffend | ausstehend |

Laptop, iPad und iPhone folgen im gemeinsamen Gerätetest (Task 3, D-05, D-08).

## Serverseitige Vorprüfung (ohne Browser, 2026-10-23)

Docker war aus, daher kein Start über scripts/dev/register-exapp.sh (braucht die Dev-Nextcloud). Stattdessen das Backend einmal allein gestartet, nur für die Prüfung, danach wieder beendet: Port 10041 (10040 war von einem älteren Backend ohne Spike-Schalter belegt, das antwortet auf /play/ mit 401 und wurde nicht angefasst), `GAMEWORLD_BROWSER_SPIKE=dev`, `GAMEWORLD_PLAY_WWW=.dev/luanti-wasm-www`, `GAMEWORLD_PLAY_ORIGINS=http://localhost:10041`.

- `GET /play/?mode=single&build=b`: 200, `cross-origin-opener-policy: same-origin`, `cross-origin-embedder-policy: require-corp`, `cross-origin-resource-policy: same-origin`, CSP mit `script-src 'self' 'wasm-unsafe-eval'` und `connect-src 'self' ws://localhost:10041`.
- `GET /play/release/a` = `{"release":"0083d7819fd7"}`, `GET /play/release/b` = `{"release":"5b1532c2ce14"}`.
- `GET /play/static/b/5b1532c2ce14/luanti.wasm`: 200, `application/wasm`, 13.847.470 Byte (wie Artefakt); Build a 13.847.471 Byte.
- launcher.js, luanti.js, worker.js, lockworker.js (text/javascript), base.pack, certs.pack, minetest.pack (application/octet-stream) je Build 200 mit erwarteter Größe und CORP same-origin.
- `node --check webplay/play.js` ohne Fehler; die Pfade in play.js (`release/<build>`, `static/<build>/<release>/launcher.js`, Pack-Name `minetest` aus `GAME_ID`) passen zum Artefakt, play.js blieb unverändert.

## Lokale Vorbereitung der Artefakte

- Das Artefakt legt den Release-Ordner unter `www/` ab (`a/www/0083d7819fd7`), die Routen aus Plan 02 erwarten ihn direkt unter dem Build-Ordner (`a/0083d7819fd7`). Lokal je Build den Inhalt von `www/` eine Ebene nach oben verschoben (nur `.dev/`, gitignored).
- Der Build enthält kein Spiel-Pack. `minetest.pack` lokal gebaut: Minetest Game aus `vendor/games/minetest_game-38214.zip` (SHA-256 5b364f6b... laut vendor/games/SHA256SUMS geprüft), Ordner als `luanti/games/minetest/` (Spiel-ID gleich Pack-Name `minetest`, wie play.js ihn nutzt), ohne .github/.gitignore/.luacheckrc, tar mit Pfaden `./luanti/...` wie base.pack, zstd Stufe 19 per Node 22 `zlib.zstdCompressSync`. 2.256.567 Byte, SHA-256 9c0441a83f8e0e1c00273534d190badd80092a7a203dfbfe58eb0cc9ff7f9cf4, in beide `packs/` kopiert. Ob launcher.js das Pack so annimmt, zeigt erst der Browser-Start.

## Befehle für die Geräte-Freigabe (Owner startet selbst, D-08)

- Start: `tailscale serve --bg --https=443 http://127.0.0.1:10040`
- Ende: `tailscale serve --https=443 off`
- ts.net-Adresse: `tailscale status --json` (Self.DNSName, Punkt am Ende weglassen); beim Neustart des Backends `GAMEWORLD_PLAY_ORIGINS` um `https://<DNSName>` ergänzen.
