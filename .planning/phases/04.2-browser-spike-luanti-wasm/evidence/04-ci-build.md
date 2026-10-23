# Beleg 04: CI-Build luanti-wasm (Plan 04.2-04, Task 1)

RUN-ID: 39909473743 (maßgeblich, Lauf 2, success)
BUILD-REF: bc0a515 (bc0a515b743baaf9597e38ed53e2671590db1b42, 2026-09-09 "Persistent storage locking")
LAEUFE: 2 von 2
Ergebnis: KO-STATUS-BUILD: GO

## Läufe

| Lauf | RUN-ID | Commit (headSha) | Ergebnis | Laufzeit a | Laufzeit b |
|------|--------|------------------|----------|------------|------------|
| 1 | 39906280343 | dc44db3 | failure (beide Jobs, exit 77) | 3:22 min (05:32:02 bis 05:35:24Z) | 3:34 min (05:32:03 bis 05:35:37Z) |
| 2 | 39909473743 | 1161e00 | success (beide Jobs) | 12:46 min (06:06:03 bis 06:18:49Z) | 20:37 min (06:06:04 bis 06:26:41Z) |

- Beide Läufe per Push auf spike/luanti-wasm (event push), nie per workflow_dispatch.
- `gh run list --branch spike/luanti-wasm --workflow luanti-wasm.yml --json databaseId --jq length` = 2.
- headSha von Lauf 2 = gepushter Commit 1161e001c66a0243652300338962cc96319cc627 (T-04.2-54).
- Log Lauf 2: `luanti-wasm HEAD: bc0a515b743baaf9597e38ed53e2671590db1b42 2026-09-09 Persistent storage locking`, `Pins in fetch_sources.sh bestätigt (Fork 038b341, webshims 70653a9)`.

## Lauf 1: Ursache und Klasse

Ursache in einem Satz: cmake auf dem Runner baut zstd zusätzlich als echtes Wasm-Side-Module `libzstd.so`; im libarchive-configure findet `-lzstd` diese Datei, emcc schaltet dadurch auf `MAIN_MODULE=2` (dynamisches Linken), und die erste Laufprobe danach (`checking size of wchar_t`, AC_CHECK_SIZEOF mit Programmlauf, weil configure nicht quer übersetzt) scheitert.

Klasse: Umgebung (Werkzeugstand des Runners, im Workflow korrigierbar; der Rückfall-Ref 5bfae52 hätte nicht geholfen, `git diff --stat bc0a515 5bfae52` ändert weder build_zstd.sh noch build_libarchive.sh noch install_emsdk.sh).

Geprüft und ausgeschlossen:
- emsdk-Version: install_emsdk.sh bei bc0a515 verlangt `./emsdk install 6.0.8`, der Lauf installiert genau 6.0.8 (`Resolving SDK version '6.0.8' to 'sdk-releases-9d70dbe8...'`). Kein Versionsproblem.
- Node: install_emsdk.sh verlangt v24.x (ab 24.18.0); Runner nutzt v24.21.0 (setup-node), NODE_JS in .emscripten zeigt darauf. Alle emsdk-Patches (darunter emsdk_jspi.patch, Shebang mit `--experimental-wasm-jspi`) wurden angewendet.
- Laufproben an sich: `checking whether we are cross compiling... no` lief vor dem Fehler erfolgreich (`./conftest`, `$? = 0`).

Indizien für die Ursache:
- build_zstd.sh baut mit cmake-Vorgabe `ZSTD_BUILD_SHARED=ON`; Lauf 1 installiert `build/install/lib/libzstd.so` neben `libzstd.a`.
- emscripten 6.0.8 `tools/link.py`, `get_dylibs()`: jedes `-lfoo`, zu dem eine Wasm-Dylib `libfoo.so` in den `-L`-Pfaden liegt, zählt als dynamische Bibliothek; danach `default_setting('MAIN_MODULE', 2)`. `cmake/Modules/Platform/Emscripten.cmake` meldet Shared-Library-Unterstützung nur für cmake 4.2.0 bis 4.2.5 und 4.3.0 bis 4.3.2 ab, sonst baut cmake echte Side-Modules.
- Die erste Probe mit `-lzstd` (`checking for ZSTD_decompressStream in -lzstd`) brauchte 13,5 s (05:34:55,8 bis 05:35:09,3) gegen 0,4 s für `-lz`, passend zum Bau der PIC-Systembibliotheken für MAIN_MODULE.
- `checking size of wchar_t` ist die erste Laufprobe nach dem Aufnehmen von `-lzstd` in LIBS.
- Gegenprobe in Lauf 2 (statisches zstd): die Laufproben nach `-lzstd`, etwa `checking for working memcmp` (configure:17801, Link mit `-lzstd -lz`), laufen mit `$? = 0` (build/libarchive/config.log im Artefakt).
- Upstream-CI von paradust7/luanti-wasm ist seit Monaten rot (Docker-Image ohne Node), daher kein Vergleichslauf von dort.

Einschränkung: Das config.log von Lauf 1 lag nicht im Artefakt (erst Lauf 2 lädt es hoch), der genaue Laufzeitfehler der wchar_t-Probe ist daher nicht direkt belegt. In Lauf 2 stammt `ac_cv_sizeof_wchar_t=4` aus der Absicherung (Cache-Variable, für wasm32 korrekt), nicht aus einer Laufprobe.

Log-Auszug Lauf 1, Job build (a):

```
2026-10-23T05:32:18.2482829Z + ./emsdk install 6.0.8
2026-10-23T05:32:43.6471956Z + sed -i 's|^NODE_JS = .*|NODE_JS = '/opt/hostedtoolcache/node/24.21.0/x64/bin/node'|' .emscripten
2026-10-23T05:34:28.4876405Z -- Installing: .../luanti-wasm/build/install/lib/libzstd.so.1.5.7
2026-10-23T05:34:28.4882973Z -- Installing: .../luanti-wasm/build/install/lib/libzstd.so
2026-10-23T05:34:28.4884031Z -- Installing: .../luanti-wasm/build/install/lib/libzstd.a
2026-10-23T05:34:28.4914458Z + ./build_libarchive.sh
2026-10-23T05:34:33.5189232Z checking whether we are cross compiling... no
2026-10-23T05:34:52.8487580Z checking for inflate in -lz... yes
2026-10-23T05:35:09.3113227Z checking for ZSTD_decompressStream in -lzstd... yes
2026-10-23T05:35:10.2503052Z checking for ZSTD_compressStream in -lzstd... yes
2026-10-23T05:35:20.1220530Z checking for wchar_t... yes
2026-10-23T05:35:20.9541888Z checking size of wchar_t... configure: error: in `.../luanti-wasm/build/libarchive':
2026-10-23T05:35:20.9543529Z configure: error: cannot compute sizeof (wchar_t)
2026-10-23T05:35:20.9544672Z See `config.log' for more details
2026-10-23T05:35:20.9843119Z ##[error]Process completed with exit code 77.
```

Job build (b) identisch (`05:35:34.7963750Z configure: error: cannot compute sizeof (wchar_t)`, exit 77).

## Fix für Lauf 2

Commit 1161e00 (spike/luanti-wasm), cherry-pick c742a15 (master), neuer Workflow-Schritt "zstd nur statisch bauen" für beide Varianten:
- `build_zstd.sh` per sed mit `-DZSTD_BUILD_SHARED=OFF`, danach Pflicht-grep (Log Lauf 2: `build_zstd.sh:16:emcmake cmake -DZSTD_BUILD_SHARED=OFF \`).
- Absicherung `ac_cv_sizeof_wchar_t=4` vor `emconfigure ./configure` in build_libarchive.sh, Pflicht-grep.
- `luanti-wasm/build/libarchive/config.log` zusätzlich im Artefakt.
- Luanti selbst linkt laut build_luanti.sh ausdrücklich `-DZSTD_LIBRARY=$INSTALL_DIR/lib/libzstd.a`, das Endprodukt war vom Side-Module nie gemeint.

## Artefakte (lokal, gitignored)

`gh run download 39909473743 -n luanti-wasm-www-a -D .dev/luanti-wasm-www/a` und `-n luanti-wasm-www-b -D .dev/luanti-wasm-www/b`. Der erste Download von b brach mit `HTTP 503: Egress is over the account limit` ab, der Wiederholungsversuch 60 s später gelang.

### Größen (aus www-sizes.txt)

| Datei | a roh | a gzip -9 | a brotli -q 11 | b roh | b gzip -9 | b brotli -q 11 |
|-------|------:|----------:|---------------:|------:|----------:|---------------:|
| luanti.wasm | 13.847.471 | 4.904.463 | 3.529.758 | 13.847.470 | 4.904.452 | 3.530.095 |
| luanti.js | 246.375 | 52.695 | 45.071 | 254.326 | 53.224 | 45.566 |
| launcher.js | 106.415 | 29.393 | 24.850 | 106.415 | 29.392 | 24.839 |
| worker.js | 346 | - | - | 346 | - | - |
| lockworker.js | 1.673 | - | - | 1.673 | - | - |
| packs/base.pack | 4.586.264 | 4.575.154 | 4.586.273 | 4.586.287 | 4.575.237 | 4.586.296 |
| packs/certs.pack | 102.544 | 102.593 | 102.549 | 102.592 | 102.641 | 102.597 |
| xterm/xterm.js | 488.663 | 120.455 | 99.311 | 488.663 | 120.455 | 99.311 |
| www gesamt (du -ab) | 19.401.313 | | | 19.409.334 | | |

Pflichtdownload für den Spielstart (luanti.wasm, luanti.js, launcher.js, worker.js, base.pack, certs.pack), Summe roh a 18.889.415 Byte; mit brotli für wasm/js und unverändert für die schon zstd-gepackten Packs rund 8,3 MB. Dazu kommt das Spiel-Pack (siehe unten). xterm lädt launcher.js nur für das Terminal.

Weitere Packs: keine. Die Builds enthalten kein Spiel-Pack (`minetest.pack` fehlt); build_www.sh legt nur base.pack und certs.pack ab und sieht für weitere Packs ein optionales `deploy.sh` vor.

### Versionsbeleg

`www/<release>/luanti.wasm: 2` Treffer für "5.17.0" in a und b (Pin bc0a515, kein Rückfall-Ref, also nicht 5.18.0-dev).

### Varianten unterscheiden sich wie geplant

- a: luanti.js enthält `2013265920` (INITIAL_MEMORY 1,875 GiB), `pthreadPoolSize=22`, kein growMemory.
- b: luanti.js enthält `805306368` und `1073741824` (768 MiB Start, 1 GiB Maximum), `growMemory`, `pthreadPoolSize=12`.

### Dateien im www-Wurzelverzeichnis (für play.js)

| Build | Release-Ordner | Dateien |
|-------|----------------|---------|
| a | 0083d7819fd7 | index.html, .htaccess, 0083d7819fd7/{launcher.js, luanti.js, luanti.wasm, worker.js, lockworker.js, .htaccess, packs/{base.pack, certs.pack, .htaccess}, xterm/{xterm.js, xterm.css, addon-fit.js, LICENSE.xterm, LICENSE.addon-fit}} |
| b | 5b1532c2ce14 | gleich, Release-Ordner 5b1532c2ce14 |

Genau ein Release-Ordner je Build, passt zur Route `/play/release/{a|b}` aus Plan 02; play.js lädt `static/<build>/<release>/launcher.js`, der Pfad stimmt mit dem Artefakt überein.

### Vergleich mit dem alten Build 01/2024 (RESEARCH)

| Datei | alt (01/2024) | neu a | Änderung |
|-------|--------------:|------:|---------:|
| minetest.wasm / luanti.wasm | 13.193.592 | 13.847.471 | +653.879 (+5,0 %) |
| base.pack | 6.769.983 | 4.586.264 | -2.183.719 (-32,3 %) |
