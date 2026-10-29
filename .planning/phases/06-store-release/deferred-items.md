# Phase 06: zurückgestellte Befunde

## Aus 06-12 (Abnahme über HaRP, 24.10.2026)

### Talk-Raum eines frisch (wieder) ernannten Verwalters bleibt bis zum Schnappschuss allein

- Beobachtet in der HaRP-Abnahme K7 (zweiter Lauf): gw-alt wird per `occ group:adduser lehrkraefte` wieder Verwalter und legt sofort eine Welt an. `ensure_room` legt den Raum als gw-alt an, `_sync_locked` nimmt aber nur Konten aus dem Verwalter-Schnappschuss (`_admins()`, höchstens alle 60 s aufgefrischt) als handelnde Kandidaten. gw-alt steht dort noch nicht, admin ist noch kein Teilnehmer, der Abgleich bricht ohne Änderung ab. Bis zum nächsten Schnappschuss plus Talk-Abgleich (5 min) ist gw-alt allein im Raum.
- Wird gw-alt in diesem Fenster gelöscht, greift der Sperrfall richtig (Log "hat keinen Moderator mehr, neuer Raum wird angelegt", neuer Raum für admin erreichbar, `orphaned_token` gemeldet). Kein Datenleck, kein Kind im Raum ohne Verwalter; nur der alte Raum bleibt als verwaist stehen.
- Möglicher Fix: In `ensure_room` den eben per `require_verwalter` frisch bestätigten Anleger als ersten Kandidaten für den ersten Abgleich zulassen oder vor dem Anlegen `refresh_admins(acting, force=True)` aufrufen. Sicherheitsrelevant (CR-01, nur bestätigte Konten handeln), darum nicht nebenbei in 06-12, sondern mit deep Review (Owner-Regel Gameworld).
- Die Abnahme wartet in K7 jetzt, bis admin Moderator ist, und prüft damit den regulären Übernahmeweg (Token bleibt gleich).

## Aus 06-24 (K8-Abnahme am Dev-Stack, 24./25.10.2026)

### K7: derselbe Befund wie oben jetzt auch beim ersten Raum

- Lauf 1: erster Raum bestanden, zweiter Raum trotz 480-s-Wartezeit ohne admin; Lauf 2: erster Raum HTTP 404 (admin noch kein Teilnehmer), zweiter bestanden. Ursache wie in 06-12 beschrieben (Anleger noch nicht im Verwalter-Schnappschuss, `_sync_locked` findet keinen handelnden Kandidaten). Die Abnahme wartet jetzt auch beim ersten Raum (`room_synced TOKEN`, ec5577c). Der Produkt-Fix bleibt sicherheitsrelevant (CR-01) und gehört in einen eigenen Plan mit deep Review.

### Regression 4.1 kollidiert mit der Demo-Umgebung aus 06-13

- Seit der Demo (18:30, nach dem letzten grünen Lauf) sind `eltern` (mama) und `lehrkraefte` (gw-lehrer) Verwalter-Gruppen. acceptance-phase4_1.sh K5/K6 (smoke-talk.sh) erwartet als Raum-Teilnehmer genau admin und gw-kind und findet admin, gw-kind, gw-lehrer, mama; K2 (Sammelnachricht, Zählung je Verwalter, sechs Namen in der Liste) scheitert im selben Lauf in 6 Prüfungen, K5/K6 in 3 (zusammen 9 von 128). Die Phasen 5, 4, 3, 2 und 1 blieben grün.
- Die Demo darf laut Owner nicht verändert werden; die Regression müsste fremde Verwalter als Grundlinie mitrechnen (wie die fremden Welt-Container) oder auf einem Stack ohne Demo laufen. Nicht in 06-24 umgebaut (fremde Abnahme, eigener Befund).

### Demo-Konto gw-lehrer ohne Sprach-Einstellung

- `occ user:setting gw-lehrer core lang` ist leer, Nextcloud meldet dann `en` (Standardsprache des Dev-Stacks). Frau Weber sieht Gameworld also auf Englisch, neue Welten von ihr wären englisch. Für die DE-Screenshots in 06-13 vorher `core lang de` setzen (Owner-Entscheid, Demo nicht von 06-24 verändert).

### Talk-Bot 401 und Raum-Anlegen 404 im Log

- `.dev/exapp.log`: "Bot-Nachricht nicht gesendet: Status 401" (23:55) und "Talk-Anlegen für Welt d41684555773 gescheitert: TalkUnavailableError" nach "Talk-Aufruf gescheitert: Status 404" (00:05, K8-Welt eines frischen Verwalters, gleiche Ursache wie oben möglich). K8 prüft keinen Bot-Text; beobachten.

### ERLEDIGT (06-26 Vorab-Fix): tests/test_admin_snapshot.py::test_ex_admin_gets_no_attempt_or_review_after_check

- Ursache: Der Test bucht Nutzung auf das feste DAY 21.10.2026; `TimeEngine._maybe_prune` (`_RETENTION_DAYS = 7`, Uhr `time.time`, als Default-Argument beim Import gebunden) löschte die Zeile ab dem 29.10.2026, der "Tagesrückblick" fehlte. Fix: Die Engine-Uhr (`world_service.time._clock`) wird in der service-Fixture per monkeypatch auf die Test-Epoche gesetzt. Produkt und Assertions unverändert.
- Offen (anderer Mechanismus, kein Prune): tests/test_alerts_api.py hat Review-Tests, die bei weit späterer Uhr (+40 Tage) am heutigen Datum scheitern; heute grün, später beobachten.

### 06-25: Aktionsnamen in backup/files.py bleiben deutsch im Log

- `_map_error(exc, "Upload"|"Auflisten"|"Abfrage"|"Download"|"Löschen")` übergibt deutsche Aktionsnamen als %s-Argument an die englisch gewordene Log-Zeile "Nextcloud files: %s failed ...". Das sind Code-Argumente außerhalb des Log-Aufrufs (D-29 verbietet Code-Änderungen in 06-25, Zeilenangaben in tests/i18n_exceptions.tsv hängen daran). Beim nächsten Pass, der Code anfassen darf, auf englische Labels umstellen.

### 06-25: Negativ-Log-Asserts ohne Positivkontrolle (Bestand)

- tests/test_backup_archive.py (`GEHEIMNAME` not in caplog.text), tests/test_notify_loop.py (`mama`), tests/test_bot_events.py (`Lena`/`lena`) haben keinen Positiv-Assert auf einen vorhandenen Log-Eintrag. Von 06-25 nicht verändert (AST-Gleichheit); bei Gelegenheit je ein `assert caplog.records` ergänzen.

### 06-26: Deutsche Aktionsnamen in talk/service.py bleiben im englischen Log

- `TalkService._isolated("Löschen"|"Abgleich"|"Anlegen", ...)` und `_spawn(...)` übergeben deutsche Aktionsnamen als `%s`-Argument an die englisch gewordene Log-Zeile "Talk %s for world %s failed: %s". Code-Argumente außerhalb des Log-Aufrufs, D-29 verbietet Code-Änderungen; tests/test_talk_service.py ruft `_spawn("Abgleich", ...)` direkt. Beim nächsten Pass, der Code anfassen darf, auf englische Labels umstellen (wie die Aktionsnamen in backup/files.py aus 06-25).

### 06-26: Lua-Syntaxtest nicht gegen echtes Docker gelaufen

- Docker Desktop startet auf diesem Rechner derzeit nicht ("Docker Desktop is unable to start", Daemon-Pipe fehlt, Dev-Proxy tcp://127.0.0.1:23750 nicht erreichbar). `tests/e2e/test_mod_syntax_e2e.py` (8 Tests) ist angelegt, ruff/pyright grün, wird ohne Proxy übersprungen. Nachholen, sobald Docker läuft: `uv run pytest -m docker -q tests/e2e/test_mod_syntax_e2e.py tests/e2e/test_play_proxy_e2e.py tests/e2e/test_play_srp_e2e.py` und ggf. test_time_mod_e2e.py/test_access_e2e.py. Ob das gepinnte Luanti-Image einen Lua-Compiler mitbringt (luac, luac5.1, luajit), ist damit offen; ohne Compiler überspringt der Test mit Begründung und die bestehenden Welt-Start-e2e-Tests sind der Ersatz.

### 06-27: Lua-Syntaxtest gegen echtes Docker nachgeholt (Ergebnis)

- Docker läuft wieder (Engine 29.5.2). `uv run pytest -m docker -q tests/e2e/test_mod_syntax_e2e.py tests/e2e/test_play_proxy_e2e.py tests/e2e/test_play_srp_e2e.py`: 7 bestanden, 8 übersprungen. Die 8 Syntaxtests springen mit Begründung an, weil das gepinnte Luanti-Image keinen Lua-Compiler (luac, luac5.1, luajit) mitbringt. Der Ersatz läuft: `tests/e2e/test_time_mod_e2e.py` und `tests/e2e/test_access_e2e.py` (Welt-Start parst init.lua): 5 bestanden. Offen bleibt nur, ob ein Image mit Lua-Compiler den Syntaxtest scharf schalten soll (derzeit nie aktiv).

### 06-27: Bundle ist nicht byte-gleich, js/ liegt nicht im Git

- Die Planannahme "sha256 von js/gameworld-main.js vorher gleich nachher" und `git diff BASE -- js/...` gelten nicht: `js/` steht in `.gitignore` (Bundle und Source-Map werden nie committet), und Vue leitet die scoped-CSS-Kennung (`data-v-xxxxxxxx`) im Produktionsbuild aus Pfad plus Quelltext der .vue-Datei ab. Jede Kommentaränderung in einer SFC ändert damit die Kennung dieser Komponente. Dazu vergibt der Minifier an 108 Stellen andere Kurznamen. Ergebnis und Beleg: siehe 06-27-SUMMARY.md. Für künftige Passes: Beleg als Token-Vergleich mit Normalisierung dieser beiden Größen führen, nicht als Hash.
- Zeilenenden: Die Arbeitskopie von frontend/ hatte gemischte Zeilenenden (65 Dateien LF, 3 CRLF, 1 gemischt) bei `core.autocrlf=true`. Ein `git checkout` auf frontend/ stellt alles auf CRLF um und ändert damit den Quelltext-Hash der SFCs (und das Bundle). Für Bundle-Vergleiche nie per Checkout auf den Basisstand zurück.

### 06-27: Stellen, die NC 32 nennen und bewusst nicht angefasst wurden

- `.planning/REQUIREMENTS.md` Zeile 56: PLATT-01 "Ziel NC 32+". Planungsdokument des Owners, nach dem Minimum-Wechsel auf 33 inhaltlich veraltet; Anpassung auf Zuruf.
- `CLAUDE.md` (Zeilen 28, 59, 76, 96, 104): "NC 32+" sind Aussagen über HaRP (empfohlener Deploy-Weg, DSP-Entfernung NC 35), kein Gameworld-Minimum.
- `.dev/info-harp.xml`: von `scripts/dev/harp-install.sh` erzeugte, ignorierte Kopie der info.xml; wird beim nächsten Lauf neu erzeugt.
