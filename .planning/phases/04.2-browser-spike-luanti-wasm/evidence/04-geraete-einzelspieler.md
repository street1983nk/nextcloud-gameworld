# Beleg 04: Gerätetest Einzelspieler (Plan 04.2-04, Task 2 und 3)

Builds aus Lauf 39909473743 (bc0a515, Luanti 5.17.0): a = Release 0083d7819fd7 (1,875 GiB fest, Pool 22), b = Release 5b1532c2ce14 (768 MiB bis 1 GiB, Pool 12). Details in 04-ci-build.md.

## Gerätematrix

| Gerät | Browser und Version | Build | crossOriginIsolated | JSPI | Zeit bis Menü in s | Zeit bis Welt in s | RAM | FPS | Touch | Fehler |
|-------|---------------------|-------|---------------------|------|--------------------|--------------------|-----|-----|-------|--------|
| Entwicklungsrechner | Chrome (Windows, Playwright der Hauptsitzung), localhost und Tailscale-URL | a | true | true | nicht gemessen (Menü erreicht) | nicht gemessen | nicht gemessen | nicht gemessen | nicht zutreffend | keiner im Spiel; 6x CSP Inline-onclick aus der launcher.js-Einstellungsleiste (bekannt aus Plan 02), favicon 401 (kosmetisch) |
| Entwicklungsrechner | Chrome (Windows, Playwright der Hauptsitzung), localhost und Tailscale-URL | b | true | true | nicht gemessen (Menü erreicht) | nicht gemessen | nicht gemessen | nicht gemessen | nicht zutreffend | wie a; Screenshot Hauptmenü Luanti 5.17.0: `.playwright-mcp/spike-single-b-menu.png` (Hauptsitzung, nicht im Repo) |
| iPhone (iOS 26.5.2, vor Update) | Safari 26 | b | true (SharedArrayBuffer vorhanden) | false | kein Start | kein Start | nicht messbar | nicht zutreffend | nicht testbar | `TypeError: undefined is not a constructor (new WebAssembly.Suspending)`; Beleg `04-iphone-ios26-jspi-false.png` |
| iPhone (iOS 27.0.1, vor Shim) | Safari 27.0.1 | b | true | true | kein Menü | kein Start | nicht messbar | nicht zutreffend | nicht testbar | Downloads und Installation certs, base, minetest je 100 %, dann `LuantiError: TypeError: undefined is not an object (evaluating 'document.exitPointerLock.bind')`; Ursache: kein Pointer-Lock-API in iOS-Safari, Emscripten-Code von bc0a515 prüft nicht; Fix 5d9085f (Shim in webplay/play.js) |
| iPhone (iOS 27.0.1, mit Shim 5d9085f) | Safari 27.0.1 und Chrome iOS (WebKit) | b | true | true | nicht gemessen (Menü erreicht) | nicht gemessen (Welt erreicht) | nicht messbar (kein Mac mit Web Inspector) | Owner-Eindruck flüssig | ja: Laufen, Bauen, Abbauen per Finger | keiner; Owner-Urteil wörtlich "ja es laeuft perfekt und fluessig" |
| iPhone (iOS 27.0.1) | Safari 27.0.1 | a | nicht getestet | nicht getestet | nicht getestet | nicht getestet | nicht getestet | nicht getestet | nicht getestet | Build a nicht geöffnet, b lief einwandfrei |
| iPad (iPadOS 26.7.1, iPadOS 27 für das Gerät noch nicht verfügbar) | Safari 26 und Chrome iPadOS | b | wie iPhone vor Update | false | kein Start | kein Start | nicht messbar | nicht zutreffend | nicht testbar (zählt als geht nicht, D-07) | startet nicht, gleiches Bild wie iPhone unter iOS 26 (JSPI fehlt) |
| iPad (iPadOS 26.7.1) | Safari 26 | a | nicht getestet | false | kein Start | kein Start | nicht messbar | nicht zutreffend | nicht testbar | ohne JSPI startet keiner der beiden Builds (beide brauchen WebAssembly.Suspending) |
| Laptop (älterer) | nicht getestet | a, b | ausstehend | ausstehend | ausstehend | ausstehend | ausstehend | ausstehend | nicht zutreffend | heute nicht getestet; Owner-Entscheid: wird vor Plan 10 nachgeholt |

Test am 2026-10-23 vormittags gemeinsam mit dem Owner (D-05, D-08) über Tailscale Serve `https://md-43700650276.tail817485.ts.net`, Backend direkt auf 127.0.0.1:10040 ohne Docker, `GAMEWORLD_BROWSER_SPIKE=dev`. Zeiten bis Menü und Welt wurden nicht mit Stoppuhr gemessen; Bildrate auf dem iPhone nur als Owner-Eindruck.

## Befunde

- JSPI ist die harte Grenze: unter iOS/iPadOS 26 bricht der Start mit `new WebAssembly.Suspending` ab, crossOriginIsolated und SharedArrayBuffer sind dort schon vorhanden. Ab iOS 27 (Safari 27.0.1) läuft der Client.
- iOS-Safari hat kein Pointer-Lock-API; luanti-wasm bc0a515 ruft `document.exitPointerLock.bind` ungeprüft auf. Der Shim in webplay/play.js (5d9085f) setzt leere Funktionen, wenn das API fehlt; danach läuft der Client in Safari und Chrome auf iOS (gleiche WebKit-Engine).
- Touch (D-07) auf dem iPhone erfüllt: Bewegen, Bauen und Abbauen per Finger funktionieren.
- Das iPad (iPadOS 26.7.1) bekommt iPadOS 27 derzeit nicht angeboten; bis Apple liefert, kann es den Browser-Client nicht starten.
- Nebenbefund: Das Diagnosefeld `#diag` ist auf Touch nicht scrollbar (pointer-events none); 77069e7 scrollt es automatisch auf die neueste Zeile.
- Freigabe: Tailscale Serve vom Owner gestartet; Beenden (`tailscale serve --https=443 off`) liegt beim Owner.

## Urteil

KO-STATUS-TABLETS: TEILWEISE (iPhone: GO ab iOS 27 mit Pointer-Lock-Shim, Touch erfüllt; iPad: NO-GO derzeit, iPadOS 27 für das Gerät nicht verfügbar; Laptop: OFFEN, vor Plan 10)
BUILD-WAHL: b

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
