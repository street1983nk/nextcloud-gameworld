# Beleg 10: Praxistest Mehrspieler über den eigenen Proxy (Plan 04.2-10)

**Stand:** 2026-10-23
**Build:** b (Release 5b1532c2ce14, Luanti 5.17.0)
**Anmeldevariante:** password (Vorgabe); Variante A proxy_srp ist live belegt und schaltbar (Plan 09)
**Welten:** Browser Minetest (mtg_kreativ, UDP 30000) und Browser VoxeLibre (voxelibre_sanft, UDP 30001), Konto gw-kind in beide eingeladen, Verwalter-Konto für den Pausentest

## Owner-Entscheid zu diesem Lauf

Der Owner hat entschieden: den förmlichen Praxistest nicht erneut live durchführen, sondern diesen Beleg aus dem füllen, was am 23.10.2026 bereits live erbracht wurde, und die offenen Teile ehrlich als "nachzuholen" markieren. Es wurden in diesem Lauf keine neuen Geräte angefasst, keine neue Tailscale-Freigabe gestartet und keine Messwerte erfunden. Unbekanntes steht als "nicht gemessen" bzw. "nachzuholen".

Die hier zusammengetragenen Belege stammen aus:
- evidence/04-geraete-einzelspieler.md (Gerätetest Einzelspieler iPhone, iPad, Build-Wahl)
- evidence/08-laptop-proxy.md (Mehrspieler-Messlauf über den Proxy auf dem Entwicklungsrechner, Pausentest)
- 04.2-09-SUMMARY.md (Variante A SRP-Übernahme live belegt)

## Gerätematrix Mehrspieler über den Proxy

| Gerät | OS und Browser | Welt | Ein-Klick-Weg ok | Zeit bis spielbar (1./2. Besuch) | MB laut Proxy | FPS | RAM | Touch Laufen/Bauen/Abbauen | 15-Minuten-Urteil | Auffälligkeiten |
|-------|----------------|------|------------------|----------------------------------|---------------|-----|-----|----------------------------|-------------------|-----------------|
| Laptop-Klasse (Entwicklungsrechner als Ersatz; echter alter Laptop offen) | Windows, Chrome 156, über die Dev-Front localhost:8092 | Minetest Game | ja (Kind klickt in Nextcloud "Im Browser spielen", neuer Tab, kein Tippen, in der Welt; Adresszeile ohne #t=, Netzwerk nur localhost:8092) | 1. ca. 8 s (launch_ok 1068 ms, ready 2500 ms, install:base 7629 ms); 2. nicht als eigener Kaltstart gemessen | 2,95 MB bytes_out über 589 s Sitzung (frames_in 8116) | nicht gemessen (Owner-Urteil "ok es läuft flüssig") | nicht gemessen | nicht zutreffend (Tastatur/Maus) | kein förmlicher 15-Min-Kindertest am Stück; stabil flüssig über eine ca. 9,8-min-Sitzung (589 s), Owner-Urteil "flüssig" | dropped_rate=393 reines Ratenlimit-Zählen, dropped_target/size/queue=0 (kein Verlust); reason=client_closed; BINDs 1, NEWADDR je Sitzung 1 |
| Laptop-Klasse (Entwicklungsrechner als Ersatz) | Windows, Chrome 156, über die Dev-Front localhost:8092 | VoxeLibre | ja (gleicher Ein-Klick-Weg) | 1. nicht exakt gemessen (ca. 93 MB Medien laden über den Luanti-Mediendownload; Erstversuch nach 93,5 s bewusst beim Aufräumen abgebrochen); 2. deutlich schneller, OPFS-Cache greift | 104 KB Steuerkanal über das Relais (bytes_out=103984 über 93,5 s); die ca. 93 MB Medien laufen über den Luanti-Mediendownload | nicht gemessen (Owner-Urteil "es läuft flüssig" trotz 93 MB) | nicht gemessen | nicht zutreffend | kein förmlicher 15-Min-Test; läuft flüssig, Owner-Urteil "es läuft flüssig" | Erstversuch bewusst beim Aufräumen beendet (kein Fehler); Zweitbesuch über OPFS spürbar schneller, aber nicht systematisch beziffert |
| iPhone | iOS 27.0.1, Safari 27.0.1 (und Chrome iOS, gleiche WebKit-Engine), Build b mit Pointer-Lock-Shim 5d9085f | Einzelspieler-Start über Tailscale (Plan 04); der volle Nextcloud-Mehrspieler-Klick wurde auf dem Entwicklungsrechner belegt, nicht erneut auf dem iPhone | Einzelspieler-Start belegt; Mehrspieler-Ein-Klick auf dem iPhone nicht erneut geprüft | nicht mit Stoppuhr gemessen (Menü und Welt erreicht) | nicht über den Proxy gemessen (iPhone-Lauf war Einzelspieler) | nicht gemessen (kein Mac mit Web Inspector) | nicht messbar (kein Web Inspector) | ja: Laufen, Bauen, Abbauen per Finger (D-07 erfüllt) | kein förmlicher 15-Min-Test am Stück; Owner-Urteil wörtlich "ja es läuft perfekt und flüssig" | JSPI ab iOS 27 vorhanden; ohne den Pointer-Lock-Shim bricht der Start ab (document.exitPointerLock.bind); Beleg Vorzustand evidence/04-iphone-ios26-jspi-false.png |
| iPad | iPadOS 26.7.1, Safari 26 (iPadOS 27 für das Gerät noch nicht verfügbar) | kein Start | nicht zutreffend (startet nicht) | kein Start | nicht messbar | nicht zutreffend | nicht messbar | nicht testbar (zählt als geht nicht, D-07) | NO-GO: JSPI fehlt, new WebAssembly.Suspending schlägt fehl; gleiches Bild wie iPhone unter iOS 26 | Belegt in Plan 04; bis Apple iPadOS 27 für das Gerät liefert, kann es den Browser-Client nicht starten |

## Pausentest im Browser-Client (D-02)

Belegt am 23.10.2026 auf dem Entwicklungsrechner (evidence/08-laptop-proxy.md):

- Verwalter setzt Pause (POST /api/pause minutes=15). Während der Pause scheitert der Kind-Beitritt. Im Welt-Log der Welt ff2295234c42 steht der korrekte Mod-Grund: `Player with the name "Kind" tried to connect ... but was disallowed for the following reason: Kurze Pause! Deine Eltern brauchen dich gerade. Danach kannst du weiterspielen.`
- Nach POST /api/pause/end klappt der Wiederbeitritt (Titel wieder "Luanti 5.17.0 [Mehrspieler]", Welt-Log "Kind joins game").
- Ergebnis: Pause wirkt im Browser-Client sichtbar (Kind kommt während der Pause nicht rein, nach Pausenende wieder); Spielzeit-Limit greift unverändert (e2e belegt); Verwalter bleibt frei (D-11); fremder Name wird vor der Welt abgefangen; Ticket ist ein-mal (ticket_expired, ticket_used_or_unknown im Log).

## Befund für den Go/No-Go-Bericht (Produktbau-Punkt)

Der luanti-wasm-Client rendert den Pausen- bzw. Kick-Grund NICHT als lesbaren Dialog. Der Client bleibt beim Verbindungsaufbau hängen und zeigt nur "Herunterfahren ...". Der Grund kommt wie beim nativen Client korrekt vom Mod gameworld_time und steht im Welt-Log, aber für ein Kind ist im Browser nicht erkennbar, WARUM es nicht hineinkommt. Für einen Produktbau braucht es eine eigene Grund-Anzeige (etwa über die Spielseite). Betrifft Plan 11.

## Variante A (Passwort verlässt den Server nie)

Live belegt in Plan 09 (test_play_srp_e2e.py 3/3 grün): der Proxy übernimmt die SRP-Anmeldung, das Kind bekommt nur ein wertloses Platzhalter-Passwort "gameworld". Vorgabe bleibt password, proxy_srp ist schaltbar. D-10 ist damit als machbar belegt.

## Offene Punkte (vor einem etwaigen Produktbau nachzuholen)

Diese Punkte sind KEIN K.-o.-Kriterium, bleiben aber als offene Punkte für den Go/No-Go-Bericht (Plan 11) stehen:

1. **D-06 förmlicher 15-Minuten-Spieltest am Stück mit einem echten Kind:** nicht durchgeführt. Belegt ist flüssiges Spiel über längere Sitzungen (589 s auf dem Entwicklungsrechner) und das Owner-Urteil "perfekt und flüssig" auf dem iPhone, aber kein ununterbrochener 15-Minuten-Kindertest.
2. **D-05 echter alter Laptop:** nicht getestet. Stellvertretend diente der Entwicklungsrechner-Chrome. Das konkrete ältere Gerät (langsamere Klasse) ist nachzuholen.
3. **Android-Tablet:** deferred (kein Gerät greifbar, D-05/deferred im Context).
4. **FPS-Zahl, RAM des Tabs, CPU der ExApp:** nicht beziffert, nur das Urteil "flüssig". Auf dem Owner-Gerät mit Task-Manager nachzuholen.
5. **OPFS-Zweitbesuch (schnellerer Zweitstart):** nicht systematisch als Kaltstart gemessen; der Effekt wurde bei VoxeLibre beobachtet ("deutlich schneller"), aber nicht beziffert.

## Teststand und Rückbau

In diesem Lauf wurde kein neuer Teststand aufgebaut und keine Geräte-Freigabe gestartet (Owner-Entscheid). Der Aufbau- und Rückbauweg ist in evidence/08-laptop-proxy.md beschrieben; die Geräte-Freigabe läuft ausschließlich über eine vom Owner selbst gestartete Tailscale Serve (D-08), kein öffentlicher Tunnel. Für einen späteren Nachhol-Lauf gelten die dort und in evidence/04-geraete-einzelspieler.md notierten Befehle:

- Start (Owner, eigene PowerShell): `tailscale serve --bg --https=443 http://127.0.0.1:8092`
- Ende (Owner): `tailscale serve --https=443 off`
- ts.net-Adresse: `tailscale status --json` (Self.DNSName ohne Punkt am Ende); GAMEWORLD_PLAY_ORIGINS um `https://<DNSName>` ergänzen.
- NC trusted_domains und trusted_proxies vorher lesen (config:system:get) und nach dem Lauf exakt zurücksetzen.
- Website-Daten auf den Testgeräten nach dem Lauf löschen (T-04.2-50).

RÜCKBAU: In diesem Lauf nicht nötig, da kein neuer Teststand gestartet wurde. Offen bleibt das vom Owner zu erledigende manuelle Entfernen fremder e2e-Rest-Container a60510fd (Ports 30015/30016, aus Plan 08), das der Auto-Mode-Klassifikator nicht entfernen durfte.

## Urteil

Praxis-Tauglichkeit ist auf zwei Geräteklassen live belegt (iPhone ab iOS 27 flüssig mit Touch; Laptop-Klasse/Chrome flüssig für Minetest Game und VoxeLibre), die Elternkontrolle greift durch den Browser-Weg hindurch, und Variante A ist machbar. Offen und ehrlich ausgewiesen bleiben der förmliche 15-Minuten-Kindertest, der konkrete alte Laptop, das Android-Tablet und die beziffbaren Leistungswerte (FPS, RAM, CPU, OPFS-Zweitstart). Diese Punkte sind kein K.-o., gehören aber in den Go/No-Go-Bericht (Plan 11) und vor einen etwaigen Produktbau.
