# Beleg 11: Sicherheitsreview der Spike-Logik (Plan 04.2-11, Task 1)

**Stand:** 2026-10-23
**Prüfgegenstand:** src/gameworld/play (Spielseite, Ticket, WS-zu-UDP-Proxy, SRP-Übernahme), webplay/play.js, frontend-Knopf, info.xml-Routen
**Methode:** Prüfliste mit echten Befehlsbelegen. Negativtests mit Positivkontrolle, Gegenprobe nie mit dem Muster der Umsetzung (eigene Testhilfen, Mutationsgegenproben). ASVS L1, Block ab Schweregrad hoch.
**Auditor-Lauf:** `PYTHONUTF8=1 uv run pytest -q -m "not docker" -p no:cacheprovider` am 2026-10-23: 1840 passed, 35 deselected, 1 Warnung (httpx/starlette-Hinweis, keine Abhängigkeitsänderung).

Alle play/-Module sind vorhanden (ws.py, relay.py, sessions.py, tickets.py, ticket_api.py, srp_proxy.py, mtp.py, commands.py, framing.py, pages.py, config.py, app.py); kein Plan wurde übersprungen. Der Review deckt den vollständigen Spike-Code ab.

---

## 1. disable_for trifft nie api/*

**Aussage:** Die Ausnahmeliste der AppAPIAuthMiddleware (play_disable_for) gibt den Proxy-/Spielpfad frei, aber niemals api/*; die signierten API-Routen bleiben hinter der AppAPI-Prüfung.

**Befehl:** `uv run pytest tests/play/test_play_config.py -q -k disable`

**Ausgabe (gekürzt):**
```
................. [100%]
17 passed, 47 deselected in 0.06s
```

**Beleg im Code:** config.py:51 `play_disable_for(mode)`; main.py:99 `APP.add_middleware(AppAPIAuthMiddleware, disable_for=play_disable_for(play_mode()))`; Kopfkommentar app.py:3 "Die Ausnahmen der AppAPIAuthMiddleware (play_disable_for) dürfen nie api/*". Plan 02 belegt per fnmatch-Gegenprobe, dass `api/my/play-ticket`, `api/my/worlds`, `api/me`, `heartbeat`, `init`, `playx` von den dev-Mustern nie getroffen werden (Positivkontrolle: `play`, `play/`, `play/ws`, `play/static/a/luanti.wasm` schon).

**Ergebnis:** ok.

## 2. Origin-Prüfung (und Schalter und Identität) vor accept

**Aussage:** Reihenfolge am WS-Upgrade ist Schalter, Origin, HaRP-Identität, dann erst accept; eine fremde Herkunft wird vor dem accept abgewiesen (CSWSH).

**Befehl:** `grep -n "origin_allowed\|accept(\|origin" src/gameworld/play/ws.py`

**Ausgabe (gekürzt):**
```
149:    if not origin_allowed(websocket.headers.get("origin"), allowed_origins()):
150:        await _refuse(websocket, "origin")
158:    await websocket.accept()
```

**Kontext ws.py:145-158:** `mode == "off"` -> close(POLICY); dann Origin-Prüfung (149) mit `_refuse`; dann bei `mode == "harp"` die Identität (`scope["username"]`, sonst `_refuse("no_identity")`); erst Zeile 158 `await websocket.accept()`. Origin (149) und Identitätsprüfung stehen vor accept (158).

**Ergebnis:** ok.

## 3. Kein sendto mit Ziel aus dem Frame

**Aussage:** Das UDP-Ziel kommt nur aus der Sitzung, nie aus dem WS-Frame. Je BIND ein mit `remote_addr=session.target` verbundener Socket; `sendto` wird ohne Zielargument aufgerufen, ein verbundener Socket nimmt zudem nur Antworten genau dieses Ziels an.

**Befehl:** `grep -nE "sendto\(|remote_addr|create_datagram_endpoint" src/gameworld/play/relay.py`

**Ausgabe (gekürzt):**
```
121:    transport, _protocol = await loop.create_datagram_endpoint(protocol_factory, remote_addr=session.target)
160:        transport.sendto(out)
```

**Kontext relay.py:150-160:** vor dem `transport.sendto(out)` laufen `unpack`, `target_allowed`, TokenBucket und `guard.check` (siehe Punkt 8, offenes Relais). `sendto(out)` hat kein Zieladressen-Argument (verbundener Socket). Gegenprobe Plan 07: Datagramme an 192.168.0.1:53, 127.0.0.1:Weltport und 10.77.0.1:30001 werden verworfen (dropped_target=3), die Sitzung bleibt offen.

**Ergebnis:** ok.

## 4. Keine Geheimnisse im Log

**Aussage:** Keine Zeile aus play/ loggt Ticket, Passcode, Passwort, SRP-Verifier, Spielername, UID oder vollständige Header.

**Befehl:** `grep -nE "LOG\.[a-z]+\(" src/gameworld/play/*.py`

**Ausgabe (gekürzt), jede Zeile bewertet:**
```
relay.py:220       play relay end seconds=.. frames.. bytes.. dropped_* srp_replaced=.. reason=..   -> nur Zahlen und fester Grund   ok
sessions.py:116    play session end binds=%d newaddr=%d                                              -> nur Zahlen                    ok
ticket_api.py:145  Spielstart abgelehnt: origin                                                     -> fester Text                   ok
ticket_api.py:148  Spielstart abgelehnt: content_type                                               -> fester Text                   ok
ticket_api.py:151  Spielstart abgelehnt: fetch_site                                                 -> fester Text                   ok
ticket_api.py:173  Spielstart vorbereitet                                                           -> fester Text                   ok
ticket_api.py:211  Spielstart abgelehnt: %s (error.reason)                                          -> feste Konstante, kein Wert    ok
ticket_api.py:216  Spielstart abgelehnt: renamed                                                    -> fester Text                   ok
ticket_api.py:219  Spielstart freigegeben                                                           -> fester Text                   ok
ws.py:72           play ws refused: %s (reason)                                                     -> feste Konstante               ok
ws.py:123          play ws refused: bind_%s (error.reason)                                          -> feste Konstante               ok
ws.py:182          play ws failed: %s (type(exc).__name__)                                          -> nur Typname                   ok
```

**Negativtest mit Positivkontrolle:** `tests/play/test_play_ws.py::test_neg_log_ohne_geheimnisse` und `tests/play/test_play_ticket_api.py::test_neg_log_ohne_geheimnisse` prüfen, dass im gesamten gameworld.play-Log kein Ticket, Passcode, Passwort, kein Spielername und keine UID steht. Plan 06 belegt per Mutationsgegenprobe: Ticket ins Log schreiben -> 1 roter Test. Live (Plan 08, evidence/08-laptop-proxy.md): `grep "guard_unreadable"` 0, `ticket_expired`/`ticket_used_or_unknown` als feste Gründe vorhanden, keine Werte.

**Ergebnis:** ok.

## 5. Kein derive_password in play/

**Aussage:** Der Spielpfad leitet keine Passwörter selbst ab; das Spielpasswort bleibt serverseitig (`access.accounts.derive_password`) und fließt nur über `check_play_access` (MyWorld.password) in Variante B bzw. gar nicht in Variante A.

**Befehl:** `grep -rn "derive_password" src/gameworld/play`

**Ausgabe:** keine Treffer (exit=1).

**Beleg:** Passwort in ws.py nur aus `check_play_access(ticket.uid)` für die SrpTakeover (Plan 09); in ticket_api nur aus `MyWorld.password` und nur bei `GAMEWORLD_PLAY_AUTH=password` (Plan 06).

**Ergebnis:** ok.

## 6. Passwort nie in einer URL

**Aussage:** Weder Ticket noch Passwort stehen in einer Adresse. Das Launch-Ticket kommt nur im URL-Fragment und wird sofort per `history.replaceState` entfernt; das Spielpasswort geht nur als JS-Objekt an den Launcher.

**Befehl:** `grep -nE "password" webplay/play.js frontend/src/components/ConnectionCard.vue`

**Ausgabe, jede Zeile bewertet:**
```
webplay/play.js:268            args.password = start.password ?? 'gameworld';   -> JS-Objekt des Launchers, keine URL; Variante A: start.password null -> Platzhalter 'gameworld'   ok
frontend/ConnectionCard.vue:33 NcFormBoxCopyButton ... :value="world.password"  -> Anzeige des Welt-Passworts für den NATIVEN Client (Eltern-Kopierknopf), nicht der Browser-Weg          ok (vorbestehend)
frontend/ConnectionCard.vue:129 navigator.clipboard.writeText(props.world.password) -> Kopierknopf des nativen Verbindungswegs, keine URL                                              ok (vorbestehend)
```

**Fluss im Browser-Weg (play.js):** Ticket aus `location.hash` (Z. 27-29), sofort `history.replaceState(null, '', location.pathname + location.search)` (Z. 33). `/play/launch` ist ein POST (Z. 226). Der ws_ticket geht in die WS-URL `?t=` (Z. 254), das ist der kurzlebige WS-Passcode, nicht das Passwort. Kein `https?://`/`wss?://<host>`-Literal in play.js (`grep -nE "https?://|wss?://[a-z]" webplay/play.js` 0 Treffer), alle Pfade relativ.

**Negativtest mit Positivkontrolle:** Plan 06 belegt `play.html?password=...` wirkt nicht (launcher.js liest aus der Adresse nur `storage` und `lang`, je mit Wertprüfung, Plan 02). Live (Plan 08): Adresszeile des Spieltabs ohne `#t=`, Netzwerk-Tab nur localhost:8092.

**Ergebnis:** ok. Hinweis: Der sichtbare Welt-Passwort-Kopierknopf in ConnectionCard.vue gehört zum vorbestehenden nativen Verbindungsweg (Eltern-Reveal), nicht zum Browser-Weg; er ist kein neuer Spike-Pfad.

## 7. Kein Fremdhost

**Aussage:** Kein externer Proxy (dustlabs) und kein fremder Host ist beteiligt (D-01).

**Befehl:** `grep -rn "dustlabs" webplay src/gameworld/play frontend/src`

**Ausgabe:** keine Treffer (exit=1). Zusatz: `grep -nE "https?://|wss?://[a-z]" webplay/play.js` 0 Treffer (alle Verbindungen relativ zum eigenen Origin).

**Live-Beleg (Plan 08):** Netzwerk-Tab des Spieltabs spricht ausschließlich localhost:8092, kein dustlabs, keine fremden Hosts.

**Ergebnis:** ok.

## 8. Owner-Negativfälle (je Fall Testname plus Positivkontrolle plus Ergebnis)

Die folgenden Fälle sind als Negativtests mit Positivkontrolle gebaut. Reine Fälle (Ticket, WS) laufen ohne Docker (Teil der 1840); e2e-Fälle gegen eine echte 5.17.0-Welt wurden in Plan 08 und Plan 09 live unter Docker belegt (dort 4 bzw. 3 grün) und in diesem Review nicht erneut live gefahren (Dev-Stack bewusst nicht gestartet, siehe Punkt 9).

| # | Owner-Negativfall | Testname (Datei) | Positivkontrolle | Ergebnis |
|---|-------------------|------------------|------------------|----------|
| a | Kind holt Ticket für fremde Welt | `test_neg_kind_fremde_welt` (test_play_ticket_api.py:193) | `test_pos_child_gets_ticket` (:169) | abgelehnt 403 |
| a' | fremde Welt = nicht vorhandene Welt (keine Enumeration) | `test_neg_nicht_vorhandene_welt_gleich_wie_fremde` (:205) | wie a | gleiche 403 |
| b | Ex-Verwalter (aus Gruppe admin entfernt, Rollencache frisch) | `test_neg_ex_verwalter` (:214) | aktiver Verwalter -> Ticket | abgelehnt 403 |
| b' | Verwalter ohne Einladung | `test_neg_verwalter_ohne_einladung` (:245) | eingeladenes Konto | abgelehnt 403 |
| c | Fremder ohne Konto / gefälschte Signatur | `test_neg_ohne_konto` (:255), `test_neg_gefaelschte_signatur` (:263) | signiertes Konto | abgelehnt (401/403) |
| d | manipulierte Welt-ID (6 Werte) | `test_neg_manipulierte_welt_id` (:302, parametrisiert) | gültige 12-Hex-Welt | 422/403 |
| e | manipulierter Spielername in TOSERVER_INIT (Variante A) | `test_neg_fremder_name_beendet_vor_srp_ersatz` (test_play_srp_e2e.py:164), `test_geschwistername`/`test_neg_geschwistername` (test_play_ws.py:682) | eigener Name -> AUTH_ACCEPT (`test_variante_a_positiv_gegenprobe_und_a1`, :115) | Sitzung endet vor der Welt, kein SRP-Ersatz |
| f | abgelaufenes Ticket (61 s) | `test_neg_launch_abgelaufen` (:415), `test_neg_ticket_abgelaufen` (test_play_ws.py:474) | 59 s gelingt | abgelehnt |
| g | wiederverwendetes Ticket | `test_neg_launch_wiederverwendet` (:403), `test_neg_ticket_wiederverwendet` (test_play_ws.py:464) | erstes Einlösen -> ADDR | abgelehnt (einmalig) |

Ergänzende Owner-Fälle:

| # | Fall | Testname | Positivkontrolle | Ergebnis |
|---|------|----------|------------------|----------|
| h | Cross-Site-WebSocket (fremder Origin) vor accept | `test_neg_origin_vor_accept` (test_play_ws.py:431) | `test_pos_allowed_origin_variants` (:389) | 1008/Abbruch vor accept |
| i | Offenes UDP-Relais (fremde Ziele verworfen) | `test_neg_fremde_ziele_verworfen` (test_play_ws.py:658) | Datagramm ans virtuelle Ziel -> Welt antwortet | dropped_target, Host-Netz unberührt |
| j | PROXY TCP / fremde Kommandos | `test_neg_fremde_kommandos` (test_play_ws.py:633), commands.py `grep -c PROXY` = 0 im Produktcode | NEWADDR/BIND UDP akzeptiert | abgelehnt, Ticket nicht verbraucht |
| k | TOSERVER_FIRST_SRP (Passwortänderung) | `test_neg_first_srp` (test_play_ws.py:700), `test_first_srp_und_split_beenden_sitzung` (test_play_srp_e2e.py:185) | regulärer Login | Sitzung endet |
| l | RELIABLE(SPLIT) vor AUTH_ACCEPT | `test_split_rules` (test_srp_proxy.py:257, Tabelle), mtp.ClientGuard | SPLIT nach AUTH_ACCEPT (Chunk 1) passiert unverändert | vor AUTH beendet |
| m | Pause über den Browser (D-02) | `test_pause_ueber_relais_prejoin_abgelehnt` (test_play_proxy_e2e.py:297) | nach `/api/pause/end` Wiederbeitritt (Plan 08 live) | Prejoin abgelehnt |
| n | Spielzeit aufgebraucht, Verwalter frei (D-11) | `test_spielzeit_aufgebraucht_ueber_relais_und_verwalter_frei` (test_play_proxy_e2e.py:317) | Verwalter bleibt frei, Kind mit Restzeit drin | Kind getrennt, Verwalter frei |
| o | falsches Passwort (Gegenprobe Variante B) | `test_auth_accept_ueber_relais_und_falsches_passwort` (test_play_proxy_e2e.py:235) | richtiges Passwort -> auth_accept | WRONG_PASSWORD |
| p | harp: fremde Identität/UID am WS | `test_neg_harp_fremde_identitaet_newaddr`/`_bind` (test_play_ws.py:568/581), `test_neg_launch_harp_fremde_uid` (test_play_ticket_api.py:543) | eigene Identität | abgelehnt, Ticket verbrannt |
| q | Ressourcen-Erschöpfung (viele WS / BIND) | `test_neg_fuenfter_bind` (test_play_ws.py:621), 20 parallele NEWADDR (Plan 07, 19x session_busy) | 1 Sitzung je UID/Welt ok (`test_pos_four_binds_share_session`, :409) | ab 2. abgelehnt |

**Unabhängige Gegenprobe (nicht das Muster der Umsetzung):** Die e2e-Tests bauen Frames und MTP-Pakete mit eigenem struct (kein framing.pack, kein mtp.py). Die SRP-Unit-Tests rechnen gegen eine unabhängige SRP-Server-Seite nach srp.cpp (`test_takeover_login_succeeds_with_real_password` :151 als Positivkontrolle, `test_takeover_login_fails_with_other_password` :158 als Gegenprobe mit anderem Passwort). Plan 05/06/07 belegen je eine Mutationsgegenprobe: jede entfernte Schutzstelle (Origin, target_allowed, Wächter-END, Zugangsprüfung, busy-Grenze, UID-Vergleich, BIND_LIMIT, pop-statt-get, Ticket-im-Log) macht mindestens einen Test rot.

**Ergebnis:** alle Owner-Negativfälle abgelehnt bei grüner Positivkontrolle. Reine Fälle live grün (Teil der 1840); e2e-Fälle in Plan 08/09 live gegen eine echte Welt belegt.

## 9. Volle Testläufe und die vier Qualitätsgates

**Befehl 1:** `PYTHONUTF8=1 uv run pytest -q -m "not docker" -p no:cacheprovider`
```
1840 passed, 35 deselected, 1 warning in 294.30s
```

**Befehl 2 (Docker-e2e):** `uv run pytest tests/e2e/test_play_proxy_e2e.py tests/e2e/test_play_srp_e2e.py -q -m docker` wurde in diesem Review NICHT erneut gefahren: der Dev-Stack wurde bewusst nicht gestartet (knapper RAM, keine fremden Container anfassen, Owner-Regel). Die Docker-e2e sind live belegt: Plan 08 `test_play_proxy_e2e.py` 4 grün (auth_accept, WRONG_PASSWORD, Pause plus Verwalter-frei, Spielzeit, fremder Name; evidence/08-laptop-proxy.md), Plan 09 `test_play_srp_e2e.py` 3 grün (Variante A Login, Gegenprobe password, fremder Name/FIRST_SRP/SPLIT; 04.2-09-SUMMARY.md). Die 35 deselektierten Tests des Non-Docker-Laufs sind diese e2e-Fälle.

**Die vier Qualitätsgates (play-Umfang):**
```
ruff check src/gameworld/play tests/play tests/e2e      -> All checks passed!
ruff format --check (dieselben Pfade)                   -> 45 files already formatted
PYRIGHT_PYTHON_FORCE_VERSION=latest pyright src/.../play -> 0 errors, 0 warnings, 0 informations
vulture src/gameworld/play                               -> kein Befund
```

**Ergebnis:** ok (Non-Docker live grün, Docker-e2e in Plan 08/09 belegt, vier Gates grün).

## 10. Schalter: Modus off gibt 404 auf /play/

**Aussage:** Ohne gesetzten Schalter bzw. bei `GAMEWORLD_BROWSER_SPIKE=off` liefert jede /play/-Route 404; kein wasm-/launcher-Inhalt tritt aus.

**Befehl:** Test aus Plan 02 `tests/play/test_play_pages.py::test_off_hides_everything` (parametrisiert über Modus None/off und mehrere Pfade).

**Kerninhalt (test_play_pages.py:56-67):**
```
response = await client.get(path, headers=appapi_headers("gw-kind"))
assert response.status_code == 404
assert b"asm" not in response.content
assert b"launcher" not in response.content
```
Teil des grünen Laufs (Punkt 1 und 9). `require_play_enabled` liest den Modus je Anfrage; ws.py schließt bei `mode == "off"` mit POLICY-Code. Positivkontrolle: `test_play_page` (:70) liefert bei Modus dev 200 mit COOP/COEP/CSP.

**Ergebnis:** ok.

---

## Befunde

Schwergrade: hoch (blockiert "sicher" nach D-04/ASVS L1), mittel, niedrig. Produktbau-Punkte sind ausdrücklich als solche markiert und sind im Spike-Scope keine Lücke.

| ID | Schweregrad | Bereich | Befund | Spike-Stand | Für den Produktbau |
|----|-------------|---------|--------|-------------|--------------------|
| S-01 | niedrig (Produktbau) | CSP | launcher.js nutzt Inline-onclick für die Einstellungsleiste; unter strenger CSP ohne 'unsafe-inline' sind diese Knöpfe wirkungslos und erzeugen 6 CSP-Meldungen. Das Spiel selbst ist nicht betroffen. | kein Spielabbruch, Dev-Front nur 127.0.0.1 | Einstellungsleiste ohne Inline-Handler oder bewusst entfernen |
| S-02 | niedrig (Produktbau/UX) | Fehleranzeige | Der wasm-Client rendert den Pausen-/Kick-Grund nicht lesbar ("Herunterfahren ..."); das Kind sieht nicht, warum es nicht hineinkommt. Der Grund kommt korrekt vom Mod und steht im Welt-Log. | Sicherheit nicht betroffen (Prejoin lehnt korrekt ab) | eigene lesbare Grund-Anzeige über die Spielseite |
| S-03 | niedrig | Credential-Forwarding (HaRP) | HaRP reicht bei Basic-Auth den Authorization-Header unverändert an die ExApp durch; das Skeleton loggt ihn. Gameworld darf Request-Header nie komplett loggen. | play/ loggt keine Header (Punkt 4) | Prüfpunkt beim HaRP-Produktbau, Log-Hygiene bestätigen |
| S-04 | niedrig | Altbibliotheken im Client | Die ausgelieferte wasm-Binary enthält openssl 1.1.1n (EOL 09/2023) und curl 7.82.0 (2022). Nur der HTTP-über-TCP-Pfad nutzt sie. | TCP-Pfad gesperrt: commands.py lehnt PROXY TCP/UDP ab (`grep -c PROXY` 0 im Produktcode), Negativtest j | bei jedem Pin-Anheben Stand nennen; Pfad bleibt gesperrt |
| S-05 | niedrig | Rollencache / D-11 | Ex-Verwalter bzw. aus einer Gruppe Entfernte behalten Zugang und Tickets bis zum nächsten Verwalter-Abgleich und bis der 30-s-Rollencache abläuft. Das ist dieselbe Regel wie beim nativen Luanti-Weg (D-11), kein neuer Pfad. | Test `test_neg_ex_verwalter` belegt den Zustand nach Abgleich | wie beim nativen Client, bewusst so (D-11) |

**Keine Befunde mit Schweregrad hoch oder mittel.** Damit geht aus dem Sicherheitsreview kein Blocker in die Bewertung "sicher" ein (D-04, ASVS L1, Block ab high). Die fünf niedrig eingestuften Punkte sind vier Produktbau-/Härtungshinweise (S-01 bis S-04) und eine bewusste D-11-Regel (S-05), keiner ist eine aktive Lücke im Spike (Dev-Front nur 127.0.0.1, produktiv nur HaRP).

**Hinweis (Owner-Regel):** Dieser Review ersetzt NICHT den laut Owner-Regel nach der Phase fälligen deep Review und `/gsd-secure-phase` durch den Orchestrator. Er ist der Spike-interne Befehlsbeleg für die Bewertung "sicher"; der förmliche Sicherheitsvertrag (04.2-SECURITY.md im Muster von 04.1) und der unabhängige Audit folgen.
