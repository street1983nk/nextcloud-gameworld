# 04.2-08: Browser-Client über den eigenen Proxy (Dev-Front, Laptop)

Stand: 23.10.2026, autonomer Teil fertig, gemeinsamer Messlauf mit dem Owner durchgeführt (Entwicklungsrechner). Der echte alte Laptop bleibt vor Plan 10 nachzuholen.

## Aufbau

- Dev-Front: `docker compose -f scripts/dev/spike-04.2/devfront.compose.yaml up -d`, nginx 1.29.8 (Image nginx:1.29-alpine), nur 127.0.0.1:8092. `/` an die Dev-NC (8091), `/exapps/gameworld/` an die ExApp (10040) mit WebSocket-Upgrade.
- NC: `trusted_domains 3 = localhost:8092`.
- ExApp als Host-Prozess, Log `.dev/exapp-spike.log`: GAMEWORLD_BROWSER_SPIKE=dev, GAMEWORLD_PLAY_ORIGINS=http://localhost:8092,https://md-43700650276.tail817485.ts.net, GAMEWORLD_PLAY_BASE=/exapps/gameworld, GAMEWORLD_PLAY_AUTH=password, GAMEWORLD_PLAY_BUILD=b, GAMEWORLD_PLAY_WWW=.dev/luanti-wasm-www.
- Falle Git Bash: Ohne `MSYS_NO_PATHCONV=1` bzw. `MSYS2_ENV_CONV_EXCL=GAMEWORLD_PLAY_BASE` schreibt Git Bash `/exapps/gameworld` beim Start in `C:/Program Files/Git/exapps/gameworld` um; play_path und ws_path waren dann kaputt. Beim Start der ExApp aus Git Bash immer setzen.
- Welten (Dev-Instanz 788fff30): `ff2295234c42` "Browser Minetest" (mtg_kreativ, UDP 30000), `e032336f9b6d` "Browser VoxeLibre" (voxelibre_sanft, UDP 30001), Konto gw-kind (Spielername Kind) in beide eingeladen.

## Automatische Vorprüfung (Claude, ohne Browser)

| Prüfung | Ergebnis |
|---------|----------|
| `curl -D - http://localhost:8092/exapps/gameworld/play/` | 200, cross-origin-opener-policy same-origin, COEP require-corp, CSP connect-src 'self' ws://localhost:8092 wss://md-43700650276.tail817485.ts.net |
| WS-Upgrade `/exapps/gameworld/play/ws` mit Origin http://localhost:8092 | HTTP/1.1 101 Switching Protocols |
| Gegenprobe: dasselbe mit Origin http://evil.example | 403 |
| Kette Ticket, /play/launch über die Dev-Front, NEWADDR/BIND über die Dev-Front, Join (Probe-Client) | Minetest-Welt auth_accept, VoxeLibre-Welt auth_accept; je `play session end binds=1 newaddr=1` |
| `uv run pytest tests/e2e/test_play_proxy_e2e.py -q -m docker` | 4 grün (auth_accept, WRONG_PASSWORD, Pause, Spielzeit plus Verwalter frei, fremder Name) |

## Live-Fragen aus Plan 05/07 (nach dem Messlauf beantwortet)

- (a) Leeres RELIABLE(ORIGINAL) beim Verbinden: BESTÄTIGT. Der echte 5.17.0-Browser-Client lief durch den Wächter ohne Abbruch. `grep -c "guard_unreadable" .dev/exapp-spike.log` ergibt 0, also hat keine echte Client-Sitzung mit `reason=guard_unreadable` geendet. Der Verbindungs-Dummy (leeres ORIGINAL) wird wie erwartet weitergeleitet.
- (b) SPLIT vor AUTH_ACCEPT: BESTÄTIGT. `grep -c "guard_split_before_auth" .dev/exapp-spike.log` ergibt 0. Der echte 5.17-Client sendet vor AUTH_ACCEPT keine SPLIT-Pakete; die Wächter-Regel (SPLIT vor AUTH_ACCEPT beendet die Sitzung) bricht keine echten Logins ab. Das war die zentrale offene Frage aus Plan 05/07, jetzt mit echtem Client beantwortet.
- (c) BIND je Sitzung: BESTÄTIGT bei 1. Alle `play session end binds=<n>`-Zeilen zeigen `binds=1`. Hinweis zur Zählerzeile: `newaddr=<k>` zählt je Konto und Welt über alle Sitzungen seit Prozessstart weiter (Plan 07, test_pos_end_log_newaddr_counts_per_uid_world); NEWADDR je Sitzung ist die Differenz zur vorigen Zeile desselben Kontos und derselben Welt und war durchgehend 1. Der kumulative Zähler lief heute bis 5.

## Messlauf (Owner, Entwicklungsrechner)

Gemeinsamer Lauf am 23.10.2026 (Windows, Chrome 156, über Playwright der Hauptsitzung; Build b, Modus multi, JSPI true, crossOriginIsolated true, deviceMemory 16). Als gw-kind angemeldet, Kindansicht "Hallo Kind (Dev)" zeigt beide Welten mit Knopf "Im Browser spielen". Klick öffnet einen neuen Tab `/exapps/gameworld/play/?build=b` ohne Ticket in der Adresszeile (replaceState entfernt `#t=` sofort), das Kind landet ohne Tippen in der Welt.

| Welt | Besuch | Zeit bis spielbar | MB laut Proxy (bytes_out) | FPS | RAM Tab | CPU ExApp | BINDs | NEWADDR je Sitzung | Auffälligkeiten |
|------|--------|-------------------|---------------------------|-----|---------|-----------|-------|--------------------|-----------------|
| Minetest Game | 1 | ca. 8 s (launch_ok 1068 ms, ready 2500 ms, install:base fertig 7629 ms) | 2,95 MB (bytes_out=2952925 über 589,2 s Spielsitzung, frames_in 8116) | nicht gemessen (Owner-Urteil "ok es läuft flüssig") | nicht gemessen | nicht gemessen | 1 | 1 | dropped_rate=393, aber dropped_target/size/queue=0 (reines Ratenlimit-Zählen, kein Verlust); reason=client_closed |
| Minetest Game | 2 | nicht als eigener Kaltstart gemessen (OPFS-Cache-Wiederbesuch in Plan 10 auf dem Owner-Gerät); die kurzen Folgesitzungen (0,6 s) sind die Pause-Reconnects | 56 B / 130 B Steuerkanal (Reconnect-Versuche) | nicht gemessen | nicht gemessen | nicht gemessen | 1 | 1 | Pause-/Wiederbeitritts-Sitzungen, siehe Pausentest unten |
| VoxeLibre | 1 | nicht exakt gemessen; Medien (ca. 93 MB) laden im Hintergrund über den Luanti-Mediendownload; Versuch nach 93,5 s durch Tab-Schließen beim Aufräumen beendet (reason=client_closed, kein Fehler) | 104 KB Steuerkanal über das Relais (bytes_out=103984 über 93,5 s); die großen Medien ca. 93 MB laufen über den Luanti-Mediendownload | nicht gemessen | nicht gemessen | nicht gemessen | 1 | 1 | Erstversuch bewusst beim Aufräumen abgebrochen, kein Fehler |
| VoxeLibre | 2 | Ticket freigegeben 12:35:08, Welt kam, Owner-Urteil "es läuft flüssig" trotz 93 MB Medien | Sitzung bei Log-Ende (12:44) noch offen, kein `play relay end` dazu | nicht gemessen (Urteil flüssig) | nicht gemessen | nicht gemessen | 1 | 1 | OPFS-Cache greift, Start deutlich schneller als Besuch 1 |

- Netzwerk-Tab (nur localhost:8092, kein dustlabs): bestätigt, der Spieltab spricht ausschließlich localhost:8092, keine fremden Hosts, kein dustlabs.
- Adresszeile ohne #t=: bestätigt, kein `#t=` in der Adresse des Spieltabs (replaceState entfernt es sofort).
- Ticket-Ein-Mal-Natur live belegt: nach verbrauchtem/abgelaufenem Ticket lehnt `/play/ws` sauber ab (`play ws refused: ticket_expired` und `ticket_used_or_unknown` im Log).
- Pausentest im Browser-Client (D-02): Verwalter setzt Pause (POST /api/pause minutes=15). Während der Pause scheitert der Kind-Beitritt; der Luanti-wasm-Client bleibt beim Verbindungsaufbau hängen und zeigt nur "Herunterfahren ...". Im Welt-Log der Welt ff2295234c42 steht der korrekte Mod-Grund: `Player with the name "Kind" tried to connect from ::ffff:172.17.0.1 but was disallowed for the following reason: Kurze Pause! Deine Eltern brauchen dich gerade. Danach kannst du weiterspielen.` BEFUND: Der Pausen-/Kick-Grund kommt wie beim nativen Client vom Mod gameworld_time, aber der wasm-Client rendert die Disallow-/Kick-Meldung NICHT als lesbaren Dialog. Das Kind sieht also nicht, WARUM es nicht hineinkommt. Produkt-/UX-Befund für Plan 09/10/11. Nach `/api/pause/end` klappt der Wiederbeitritt (Titel wieder "Luanti 5.17.0 [Mehrspieler]", Welt-Log "Kind joins game").
- Screenshots: `..\.playwright-mcp\spike-multiplayer-kind.png` (3D-Welt), `spike-pause-reject.png`, `spike-pause-reject2.png`, `spike-pause-reject3.png` (Pause "Herunterfahren ...").

BIND_LIMIT: passt (max 1 je Sitzung). Alle `play session end`-Zeilen zeigen binds=1, der Wert liegt weit unter dem BIND_LIMIT 4 (src/gameworld/play/sessions.py). Kein `too_many_binds`, keine stille Anhebung nötig.

## Offen vor Plan 10

- Der echte alte Laptop (langsameres Gerät) wurde noch nicht gemessen; der heutige Lauf war der Entwicklungsrechner. FPS, RAM des Tabs und CPU der ExApp wurden nicht beziffert (nur Owner-Urteil "flüssig"). In Plan 10 auf dem Owner-Gerät mit Task-Manager nachholen, dort auch der OPFS-Cache-Zweitbesuch für Minetest.
- Fremde e2e-Rest-Container `a60510fd` (Ports 30015/30016) wurden nicht entfernt (docker rm vom Auto-Mode-Klassifikator abgelehnt). Manuelles Aufräumen durch den Owner offen.
