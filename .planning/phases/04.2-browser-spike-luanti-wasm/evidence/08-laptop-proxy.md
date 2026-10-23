# 04.2-08: Browser-Client über den eigenen Proxy (Dev-Front, Laptop)

Stand: 23.10.2026, autonomer Teil fertig, gemeinsamer Messlauf mit dem Owner steht aus.

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

## Live-Fragen aus Plan 05/07

- (a) Leeres RELIABLE(ORIGINAL) beim Verbinden: live mit selbst gebautem Paket über das Relais an die echte 5.17.0-Welt belegt, der Wächter leitet weiter und der Server antwortet mit SET_PEER_ID (test_auth_accept_ueber_relais_und_falsches_passwort). Ob der echte Browser-Client genau dieses Paket sendet, zeigt der Messlauf: Endet seine erste Sitzung nicht mit `reason=guard_unreadable`, ist es bestätigt.
- (b) SPLIT vor AUTH_ACCEPT: offen, nur mit dem echten Client prüfbar. Nach dem Messlauf `grep "reason=guard_split_before_auth" .dev/exapp-spike.log`.
- (c) BIND je Sitzung: Probe-Client 1. Echter Client: offen, Messlauf. Hinweis zur Zählerzeile: `newaddr=<k>` zählt je Konto und Welt über alle Sitzungen seit Prozessstart weiter (Plan 07, test_pos_end_log_newaddr_counts_per_uid_world); NEWADDR je Sitzung ist die Differenz zur vorigen Zeile desselben Kontos und derselben Welt.

## Messlauf (Owner, ausstehend)

| Welt | Besuch | Zeit bis spielbar | MB laut Proxy (bytes_out) | FPS | RAM Tab | CPU ExApp | BINDs | NEWADDR | Auffälligkeiten |
|------|--------|-------------------|---------------------------|-----|---------|-----------|-------|---------|-----------------|
| Minetest Game | 1 | ausstehend | | | | | | | |
| Minetest Game | 2 | ausstehend | | | | | | | |
| VoxeLibre | 1 | ausstehend | | | | | | | |
| VoxeLibre | 2 | ausstehend | | | | | | | |

- Netzwerk-Tab (nur localhost:8092, kein dustlabs): ausstehend
- Adresszeile ohne #t=: ausstehend
- Pausentest im Browser-Client: ausstehend

BIND_LIMIT: offen (Messlauf ausstehend)
