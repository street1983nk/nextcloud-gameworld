# Gameworld 1.0.0: Volltest vor dem Store-Release (02.11.2026)

## Ergebnis in einem Satz

Kein blockierender Befund, kein Sprachfehler in den drei Sprachen. Drei Punkte sollten vor dem Release angesehen werden (Erwachsen-Marke hinkt deutlich länger als bekannt, Admin-Hauptansicht knapp über 3 s, Escape schließt drei Dialoge nicht), dazu sieben kosmetische Punkte.

## Umfang und Umgebung

| Punkt | Wert |
|-------|------|
| Datum | 02.11.2026, 18:30 bis 20:05 Uhr |
| Gameworld | 1.0.0 (ExApp, Dev-Host unter Windows, Code-Stand c489944 plus nur `scripts/audit/`) |
| Nextcloud | 34.0.3, AppAPI 34.0.0, Talk (spreed) 24.0.6 |
| Luanti | ghcr.io/luanti-org/luanti:5.17.0 |
| Werkzeuge | Python 3.13.1 (uv), Node 22.21.0, Playwright 1.63.0 aus dem npx-Cache e41f203b7505f1fb |
| Konten | `admin` (Nextcloud-Admin, Gruppe admin), `gw-lehrer` (Gruppenverwalter über lehrkraefte), `mia` (Kind) |
| Ausgangszustand lang-Settings | admin = de, gw-lehrer = ungesetzt, mia = fr (`.dev/audit/261102/baseline.txt`) |
| Bestehende Welten | 8 Welten der Instanz 788fff30 (4 laufend, 4 gestoppt), 2 Volumes der Instanz a60510fd |
| Belege | `.dev/audit/261102/` (gitignored), Zusatzlauf Ferien-Dialog `.dev/audit/261102-holiday/` |

Geprüft wurden alle drei Rollen in de, en und fr, jeweils am Desktop (1280 x 900) und mit 390 x 844 px. Die Prüfwerkzeuge liegen wiederholbar unter `scripts/audit/` (README dort).

## Detektor-Selbstprüfung

- `node scripts/audit/selftest.mjs . .dev/audit/server.json`: SELFTEST PASSED (Exit 0).
- Exklusive Wörter je Sprache: de 673, en 460, fr 669 (Mindestwert 200).
- Positivkontrollen mit handgeschriebenen Sätzen (nicht aus den Wörterbüchern): deutscher Satz als en geprüft meldet de, englischer Satz als fr meldet en, französischer Satz als de meldet fr, englischer Satz mit dem einzelnen Wort "Sicherung" meldet de: sicherung.
- Negativkontrollen: je ein sauberer Satz in de, en und fr ohne Treffer.
- Unabhängige Zusatzprobe im Lauf: das Ferien-Label "audit261102-ferien" im Zusatzlauf wurde in den en- und fr-Ansichten sofort als deutsches Wort gemeldet.
- Darstellungsprüfung: `node scripts/audit/layout_selftest.mjs` erkennt abgeschnittenen Text und waagerechtes Scrollen und ignoriert die visuell versteckte Tabellenkopfzeile (4 von 4, `layout-selftest.log`).
- Serverquellen des Wortschatzes: API-Katalog (catalog_en/catalog_fr), Spieltexte beider Mods, Benachrichtigungen, Talk-Bot, Sicherungszusatz.

## Befunde

| Nr | Schwere | Bereich | Rolle | Sprache | Reproduktion | Beleg |
|----|---------|---------|-------|---------|--------------|-------|
| 1 | sollte vor Release | Spieler-Dialog, Erwachsen-Marke | admin (gilt für jeden Verwalter) | de (sprachunabhängig) | Welt mit eingeladenem Kind, "Spieler" öffnen, Schalter "Erwachsen" an, "Als erwachsen markieren" bestätigen: der Schalter springt sofort, die Marke "Erwachsen" am Namen erscheint erst nach 11,3 s; beim Ausschalten verschwindet sie erst nach 13,1 s. Bekannt war "1 bis 2 s". | `functional-s2.json` (measures.adultOnChipMs, adultOffChipMs), `functional-s2.log` |
| 2 | sollte vor Release | Ladezeit Hauptansicht | admin | de | Hauptansicht als admin dreimal laden: bis Weltentabelle sichtbar Median 3,06 s, Maximum 4,5 s; langsamste Aufrufe /api/admin/orphans 2,4 s, /api/playtime 2,4 s, /api/admin/verwalter-groups 2,2 s, /api/worlds 1,7 s. Grenzfall knapp über der 3-s-Schwelle (Dev-Host unter Windows). | `loadtimes.json`, `loadtimes.log` |
| 3 | sollte vor Release | Tastaturbedienung der Dialoge | admin, gw-lehrer | de, en, fr | "Einladen" öffnen: der Fokus steht im Suchfeld, Escape schließt den Dialog nicht (auch dreimal nicht). Gleiches bei "Zeitfenster" (Fokus auf dem ersten Schalter). Im "Spieler"-Dialog schließt Escape nicht mehr, nachdem "Neues Passwort" oder "Name ändern" mit "Abbrechen" verlassen wurde (Fokus geht verloren). Nach Klick auf die Dialogüberschrift schließt Escape jeweils. "Sicherungen" und "Löschen" schließen mit Escape. Vermutlich Verhalten von NcDialog/NcSelect bei Fokus in Eingaben. | `report.json` (escapeLog, 36 Fälle), `audit.log` |
| 4 | kosmetisch | Setup-Check, Link "Anleitung" | admin | de, fr | Docker-Proxy fehlt: die Meldung verlinkt in jeder Sprache `docs/install.md` (englisch), obwohl `docs/install.de.md` existiert. Für fr gibt es keine eigene Anleitung. Quelle `src/gameworld/provisioner/setup_check.py:21` (DOCS_URL). | `functional-s5.json` (setup check without proxy) |
| 5 | kosmetisch | Ablehnung ohne JSON (CSRF-Regel) | alle | alle | Änderung ohne `Content-Type: application/json` schicken: der 403-Text folgt der Kontosprache, nicht der UI-Sprache aus `X-Gameworld-Language`. Bei ungesetzter Kontosprache und Header `X-Gameworld-Language: de` kam die englische Meldung "Gameworld only accepts changes as JSON from its own page." Über die Oberfläche nicht auslösbar, nur bei fremden Clients. Quelle `src/gameworld/api/csrf.py:70`. | `.dev/audit/261102-try/cleanup-1793641300796.log`; in `functional-s13.json` bei gesetzter Kontosprache korrekt in allen drei Sprachen |
| 6 | kosmetisch | Meldung Tageslimit | gw-lehrer (jeder Verwalter) | de, en, fr | POST /api/playtime/children/{konto} mit limit_minutes 0: "Das Tageslimit liegt zwischen 1 und 1440 Minuten oder ist None." (en "or None", fr "ou vaut None"). Das Python-Wort "None" steht im Nutzertext. Über die API erreicht; ob der Dialog den Wert 0 zulässt, nicht geprüft. | `functional-s13.log` ([3] playtime limit 0) |
| 7 | kosmetisch | Rohmeldungen bei en | gw-lehrer | en | Für englische Konten bleiben pydantic- und Starlette-Texte stehen: "String should match pattern '^[0-9a-f]{12}$'", "Input should be 15, 30 or 60", "List should have at least 7 items after validation, not 6", "Not Found". de und fr bekommen stattdessen "Die Eingabe ist ungültig." bzw. "Diese Anfrage kann Gameworld nicht ausführen." So gewollt (language.py), wirkt aber technisch. Über die Oberfläche kaum erreichbar. | `functional-s13.log` ([3] en) |
| 8 | kosmetisch | Rechte-Meldung bei lesenden Routen | gw-lehrer | de, en, fr | GET /api/admin/groups als Verwalter ohne Admin-Recht: "Nur Nextcloud-Admins dürfen das ändern." auch beim reinen Lesen. | `functional-s4.json` |
| 9 | kosmetisch (Owner-Entscheid) | Weltzeile Starten, Stoppen, Neustarten | admin, gw-lehrer | alle | Die drei Knöpfe wirken sofort ohne Rückfrage; "Stoppen" trennt spielende Kinder ohne Bestätigung. Löschen hat einen Bestätigungsdialog. Kein Fehler, nur zur Entscheidung. | `frontend/src/views/ParentView.vue` Zeilen 160 bis 178; Prüfskript klickt diese Knöpfe bewusst nie |
| 10 | kosmetisch (nur Tests) | Docker-e2e-Suite | - | - | Ein Lauf der e2e-Suite hinterließ 8 anonyme, verwaiste Docker-Volumes (Label com.docker.volume.anonymous). Die Baseline enthielt schon viele solcher Volumes aus früheren Läufen. Die 8 neuen wurden nach Prüfung (dangling, Erstellzeit im Lauf) entfernt. | `docker-before-e2e.txt`, `docker-after-e2e.txt`, `e2e-volume-cleanup.log` |

Detektortreffer und ihre Einordnung:

- "eltern" in der Admin-Hauptansicht en und fr (4 Treffer): Gruppen-ID der Nextcloud-Gruppe `eltern` in der Verwaltergruppen-Liste, also Daten, kein UI-Text. Nach Prüfung in die Datenliste des Detektors aufgenommen (`scripts/audit/lang_detector.mjs`).
- "ferien" im Zusatzlauf en und fr: stammt aus dem selbst angelegten Ferien-Label "audit261102-ferien"; Label im zweiten Zusatzlauf geändert, danach kein Treffer.
- Sonst kein Treffer in 228 Ansichten und Dialogen, 114 Ansichten des Zusatzlaufs und 347 API-Ergebnissen. Zusatzscan der erfassten Texte: keine Gedankenstriche, keine Emojis, keine ASCII-Umlaute (nur echte Wörter wie "neue", "Abenteuer" und die Gruppen-ID lehrkraefte), keine offenen Platzhalter, kein "undefined" oder "null".

## Abdeckungsmatrix

Je Sprache (de, en, fr) und Breite (1280, 390), jeweils Text, Detektor, Screenshot und Darstellungsprüfung:

| Ansicht / Dialog / Meldung | admin | gw-lehrer | mia |
|----------------------------|-------|-----------|-----|
| Hauptansicht (inkl. Pause-Kachel, Spielzeiten, Ferien, Spieleradresse, Zeitzone, Tagesrückblick, Talk-Status je Welt, Weltsprache) | ja | ja | ja |
| Verwaltergruppen, Reste (Admin-Abschnitte) | ja | nicht sichtbar (richtig) | - |
| Dialog Einladen | ja | ja | - |
| Dialog Spieler, darin Neues Passwort (Warnung), Name ändern (Warnung), Erwachsen (Bestätigung) | ja | ja | - |
| Dialog Zeitfenster | ja | ja | - |
| Dialog Sicherungen | ja | ja | - |
| Dialog Welt löschen (nur geöffnet, Abbrechen) | ja | ja | - |
| Dialog Spielzeit bearbeiten, alle 6 Kinder | ja | ja | - |
| Dialog Ferien entfernen (Zusatzlauf mit Ferien 01.07.2027) | - | ja | - |
| Seiten Pause, Beitrittsversuche, Tagesrückblick | ja | ja | - |
| Kinderansicht mit Passwort angezeigt | - | - | ja |
| Setup-Check-Abschnitt ohne Proxy (Oberfläche) | ja (nur de) | - | - |
| Setup-Check-Meldungen ohne Proxy (API) | ja | - | - |
| Kopierbefehle AIO und Compose plus Beschriftungen | ja (Funktionsaufruf, siehe unten) | - | - |
| Erfolgs- und Fehlermeldungen Lebenszyklus, Sicherung, Wiederherstellen | admin teilweise | ja | - |
| Fehlermeldungen ungültiger Eingaben (21 Fälle plus CSRF) | - | ja | - |
| Rechte-Ablehnungen | - | ja | ja |

Nicht erfasst (Zustand im Dev-Stack ohne Eingriff nicht herstellbar): Dialog "Talk-Raum neu anlegen" (nur bei verwaistem Raum oder Ex-Verwalter-Raum), Dialog "Reste entfernen" (keine Reste gelistet).

## Funktionstests an Wegwerf-Welten

Je Sprache seriell, Welt `audit261102-<lang>` als gw-lehrer (347 Ergebnisse, 0 Fehlschläge):

| Schritt | de | en | fr |
|---------|----|----|----|
| Anlegen (201), Weltsprache = Kontosprache | ok | ok | ok |
| Laufend innerhalb 120 s ("Läuft", "Running", "En marche") | ok | ok | ok |
| Einladung mia als Gruppenverwalter abgelehnt (403, Text in Sprache) | ok | ok | ok |
| Einladung eigene Gruppe klasse und Entfernen | ok | ok | ok |
| Einladung mia als admin und Entfernen | ok | ok | ok |
| Spielzeitlimit mia setzen und exakt zurücksetzen | ok | ok | ok |
| Zeitfenster setzen und löschen | ok | ok | ok |
| Sicherung, Ordner Sicherungen / Backups / Sauvegardes, kein Ordner in den anderen Sprachen | ok | ok | ok |
| Wiederherstellen ohne Bestätigung 409, mit Bestätigung ok | ok | ok | ok |
| Vor-Restore-Sicherung mit Zusatz vor-restore / before-restore / avant-restauration | ok | ok | ok |
| Stoppen ("Gestoppt", "Stopped", "Arrêté"), Löschen 204, Ordner in Files entfernt | ok | ok | ok |

Admin-Prüfungen (de): Welt über die Oberfläche angelegt (4,5 s), Verwaltergruppe lehrkraefte entfernt und wieder hinzugefügt (vorher und nachher eltern, lehrkraefte, parents), Erwachsen-Marke gemessen (Befund 1), Setup-Check in drei Sprachen gelesen.

Kopierbefehle des Setup-Checks: der Dev-Stack nutzt 127.0.0.1:23750, dort zeigt Gameworld die Befehle absichtlich nicht. Deshalb über `proxy_commands()` mit Standardadresse erzeugt und geprüft: beide Befehle (Netz gameworld bzw. nextcloud-aio) enthalten `docker run -d`, Name, Neustartregel, Netz, Socket nur lesend, CONTAINERS/IMAGES/VOLUMES/POST=1, EXEC=0 und das gepinnte Image. Beschriftungen in de, en, fr ohne Detektortreffer.

Fehlender Proxy: reconciler.py verändert bei Docker-Fehlern keine Welt (periodischer Abgleich fängt ProvisionerError und wartet). Proxy 26 s gestoppt, danach sofort gestartet. Setup-Check meldet in allen drei Sprachen "proxy_refused" mit Text in Kontosprache, Weltenliste liefert 200 mit Status "Docker nicht erreichbar" / "Docker unreachable" / "Docker injoignable", nach dem Neustart wieder ok.

## Rechte-Matrix

| Konto | Routen | de | en | fr |
|-------|--------|----|----|----|
| mia | 32 Verwalterrouten (Welten, Presets, Sicherungen, Spieler, Einstellungen, Spielzeit, Ferien, Zeitzone, Pause, Setup-Check, Talk, Beitrittsversuche, Rückblick, Link-Ursprung) | 32 x 403 | 32 x 403 | 32 x 403 |
| mia | 7 Admin-Routen (/api/admin/...) | 7 x 403 | 7 x 403 | 7 x 403 |
| mia | ohne UI-Sprachheader | 403 in Kontosprache | 403 in Kontosprache | 403 in Kontosprache |
| mia | /api/me, /api/my/worlds, /api/my/playtime | 3 x 200 | 3 x 200 | 3 x 200 |
| gw-lehrer | 7 Admin-Routen plus ohne Header | 8 x 403 | 8 x 403 | 8 x 403 |

Alle Ablehnungen mit sauberer Meldung in der richtigen Sprache ("Nur Eltern können Welten verwalten." / "Only parents can manage worlds." / "Seuls les parents peuvent gérer les mondes."). Alle Körper waren absichtlich ungültig oder die Routen nur lesend, es wurde nichts verändert. Hinweis zur Planvorlage: attempts, review, review/prefs und origin liegen unter /api (Verwalter), nicht unter /api/admin; so geprüft.

## Darstellung Desktop und 390 px

- 228 Ansichten und Dialoge (plus 114 im Zusatzlauf), je Screenshot unter `.dev/audit/261102/shots/<lang>-<konto>-<ansicht>-<breite>.png`.
- Waagerechtes Scrollen: 0. Abgeschnittene Texte: 0. Scrollende Container: 0.
- Unter 480 px wechselt die Weltentabelle in die Kartenansicht; die visuell versteckte Kopfzeile wurde im ersten Probelauf als abgeschnitten gemeldet und ist als Fehlalarm aus der Prüfung genommen (Selbstprüfung Fall 4).
- Echte Telefone wurden nicht geprüft, nur emulierte Breite.

## Testsuiten

| Suite | Ergebnis | Beleg |
|-------|----------|-------|
| `uv run pytest -q -m "not docker"` | 2970 passed, 0 failed, 52 deselected, 8:57 min | `pytest-unit.log` |
| `GAMEWORLD_REQUIRE_DOCKER=1 uv run pytest -q -m docker tests/e2e` | 44 passed, 0 failed, 8 skipped, 20:47 min | `pytest-e2e.log` |

Die 8 übersprungenen e2e-Tests stammen aus `test_mod_syntax_e2e.py`: das gepinnte Luanti-Image bringt keinen Lua-Compiler mit, der Test verweist selbst auf die gleichwertigen Prüfungen in test_time_mod_e2e und test_access_e2e. Vor und nach e2e: Container identisch, Volumes bis auf die 8 anonymen Reste (Befund 10) identisch.

## Ladezeiten

Sprache de, je 3 Ladevorgänge, Dev-Host unter Windows. Schwellen: über 3 s sollte vor Release, über 8 s blockierend.

| Konto | Weltentabelle bzw. Karten sichtbar (Median / Max) | Mit Spielzeitliste (Median / Max) | Bewertung |
|-------|---------------------------------------------------|-----------------------------------|-----------|
| admin | 3,06 s / 4,49 s | 3,08 s / 4,85 s | über 3 s (Befund 2) |
| gw-lehrer | 2,41 s / 2,66 s | 2,62 s / 2,90 s | ok |
| mia | 1,75 s / 1,98 s | - | ok |

Langsamste API-Aufrufe (Median): /api/admin/orphans 2,4 s, /api/playtime 2,3 bis 2,4 s, /api/admin/verwalter-groups 2,2 s, /api/worlds 1,7 s, /api/setup-check 1,2 s, /api/my/worlds 1,3 s (mia). Die Aufrufe laufen parallel.

## Bekannte Kleinbefunde (bestätigt, nicht gefixt)

- Erwachsen-Marke hinkt nach: bestätigt, aber deutlich länger als die notierten 1 bis 2 s: 11,3 s beim Einschalten, 13,1 s beim Ausschalten (Befund 1). Ausgangswert von mia (nicht erwachsen) wiederhergestellt.
- Talk-Hinweis Ex-Verwalter erst nach Neuladen: nicht reproduziert. Nach Entfernen von lehrkraefte (gw-lehrer damit kein Verwalter mehr) meldete GET /api/talk nach 35 s weiterhin owner_not_admin = false; der Hinweis erschien weder ohne noch mit Neuladen. Vermutlich ist die Admin-Liste im Talk-Status gedrosselt oder gecacht. Offen, siehe unten.
- loadTalk nicht gepollt: beim Anlegen einer Welt über die Oberfläche wechselte der Talk-Status der neuen Zeile ohne Neuladen innerhalb von 45 s von "Talk-Raum wird eingerichtet" auf "Talk-Raum öffnen" (die Weltenliste lädt den Talk-Stand offenbar mit). Für diesen Fall also kein Befund; für den Ex-Verwalter-Fall nicht belegt.

## Aufräumnachweis

- `after.txt` gegen `baseline.txt`: Container (Name und Zustand Up/Exited) und Volumes identisch, Ausgabe BASELINE_IDENTICAL.
- Weltenliste als admin gegen `baseline-worlds.json`: 8 Welten, IDs, Namen, Status und Sollzustand identisch (`after-worlds.json`).
- Keine Container oder Volumes mit audit261102, keine Welt mit dem Präfix, keine Sicherungsordner der Wegwerf-Welten in Files von gw-lehrer.
- Verwaltergruppen: eltern, lehrkraefte, parents (wie vorher). Ferien: 0 (wie vorher). Spielzeitregeln von mia identisch, mia nicht erwachsen (wie vorher).
- lang-Settings: admin = de, gw-lehrer = ungesetzt, mia = fr, wie im Ausgangszustand.
- Docker-Proxy läuft wieder. Keine Browser- oder Audit-Node-Prozesse mehr aktiv.
- `git status`: außer `.planning/config.json` (vorher schon geändert) und dem Aufgabenordner keine Änderungen; keine Datei unter src/, frontend/ oder appinfo/ geändert.

## Offene Punkte für die Owner-Sicht

1. Luanti-Client-Begriffe der Kinderanleitung (de, fr) mit einem echten Luanti-Client prüfen; nicht automatisierbar.
2. Spieltexte der Mods und Talk-Bot- und Benachrichtigungstexte nur über den Katalog geprüft (Wortschatz des Detektors), nicht live im Spiel, in Talk oder in der Benachrichtigungsglocke.
3. Talk-Hinweis Ex-Verwalter: mit längerem Wartefenster (oder nach Ablauf des Admin-Caches) nachprüfen.
4. Dialoge "Talk-Raum neu anlegen" und "Reste entfernen" sowie die Kopierbefehle in der Oberfläche einmal auf einer Instanz mit Standard-Proxyadresse ansehen.
5. Entscheiden, ob Stoppen und Neustarten eine Rückfrage bekommen (Befund 9).
6. Darstellung auf einem echten Telefon (nicht nur 390 px emuliert) bei der gemeinsamen Abnahme.
