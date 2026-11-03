---
phase: quick-261102-plj
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - scripts/audit/README.md
  - scripts/audit/dump_catalog.py
  - scripts/audit/lang_detector.mjs
  - scripts/audit/selftest.mjs
  - scripts/audit/audit.mjs
  - scripts/audit/functional.mjs
  - scripts/audit/loadtimes.mjs
  - .planning/quick/261102-plj-gameworld-volltest-vor-store-release-1-0/261102-plj-BEFUNDE.md
autonomous: true
requirements: [QUICK-261102-PLJ]

must_haves:
  truths:
    - "Der Fremdwort-Detektor liegt im Repo (scripts/audit/) und erkennt in einer Selbstprüfung absichtlich falschsprachige Texte (de-Satz als en, en-Satz als fr, fr-Satz als de) und meldet bei einem sauberen Text der richtigen Sprache keinen Treffer"
    - "Jede Hauptansicht, jeder Dialog (auch zerstörende Bestätigungsdialoge, Setup-Check, Talk, Verwaltergruppen, Reste, Pause, Ferien, Zeitfenster, Sicherungen, Wiederherstellen, Spielername, Passwort, Erwachsen) und jede ausgelöste Erfolgs- und Fehlermeldung wurde je Rolle (NC-Admin "admin", gw-lehrer, mia) und Sprache (de, en, fr) erfasst und geprüft"
    - "Welt anlegen, starten, stoppen, löschen, Einladungen, Spielzeitlimits, Sicherung und Wiederherstellung mit Sprachordner und Sprachzusatz, Verwaltergruppen, Talk-Hinweis und Setup-Check (AIO und Compose) sind an Wegwerf-Welten live durchgespielt"
    - "Rechte-Negativtests belegen 403 bzw. eine saubere Meldung in Kontosprache für Kind gegen Verwalter- und Admin-Routen und für Verwalter gegen Admin-Routen"
    - "Desktop- und 390-px-Screenshots aller Hauptansichten je Rolle und Sprache liegen vor, mit maschineller Prüfung auf waagerechtes Scrollen und abgeschnittene Texte"
    - "pytest-Suite und Docker-e2e-Suite sind gelaufen, Ladezeiten je Rolle und Hauptansicht sind gemessen"
    - "Bestehende Welten, Container und Volumes (788fff30-, a60510fd-) sind vorher und nachher identisch, alle Wegwerf-Welten sind entfernt, lang-Settings der Konten sind auf den Ausgangszustand zurückgesetzt"
    - "261102-plj-BEFUNDE.md listet jeden Befund mit Schwere, Rolle, Sprache, Reproduktion und Beleg; keine Produktdatei wurde geändert"
  artifacts:
    - path: "scripts/audit/lang_detector.mjs"
      provides: "Fremdwort-Detektor aus Frontend-Wörterbüchern plus Server-Katalog"
      exports: ["loadVocab", "foreign"]
    - path: "scripts/audit/selftest.mjs"
      provides: "Positivkontrolle und Negativkontrolle des Detektors, Exit-Code != 0 bei Versagen"
    - path: "scripts/audit/audit.mjs"
      provides: "Sprach- und Darstellungslauf über Rollen x Sprachen x Desktop/390 px"
    - path: "scripts/audit/functional.mjs"
      provides: "Funktions- und Negativtests an Wegwerf-Welten inkl. Meldungstexte"
    - path: "scripts/audit/loadtimes.mjs"
      provides: "Ladezeitmessung der Hauptansichten je Rolle"
    - path: ".planning/quick/261102-plj-gameworld-volltest-vor-store-release-1-0/261102-plj-BEFUNDE.md"
      provides: "Befundbericht"
      contains: "Schwere"
  key_links:
    - from: "scripts/audit/lang_detector.mjs"
      to: "frontend/src/i18n/<lang>/index.js und src/gameworld/i18n/catalog_en.py, catalog_fr.py"
      via: "dynamic import der Wörterbücher, server.json aus dump_catalog.py"
      pattern: "i18n/\\$\\{lang\\}/index.js"
    - from: "scripts/audit/audit.mjs und functional.mjs"
      to: "scripts/audit/lang_detector.mjs"
      via: "import { foreign }"
      pattern: "from './lang_detector.mjs'"
---

<objective>
Großer Gesamttest von Gameworld 1.0.0 vor dem Store-Release (Owner-Vorgabe 02.11.2026: "Gameworld muss perfekt funktionieren, wenn die ersten User es nutzen", Sprachfehler sind ein No-Go). Das vorhandene Sprachprüfskript wird ins Repo übernommen, mit Positivkontrolle abgesichert und auf alle Aktionen erweitert; danach laufen Sprach-, Darstellungs-, Funktions-, Negativ-, Ladezeit- und Suitentests gegen den laufenden Dev-Stack.

Purpose: Belastbare Befundliste für die Owner-Sicht vor dem Release. KEINE Produktfixes in dieser Aufgabe.
Output: scripts/audit/ (committet), Belege unter .dev/audit/261102/ (gitignored), Befundbericht 261102-plj-BEFUNDE.md.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@./CLAUDE.md
@.planning/phases/06-store-release/06-13-SUMMARY.md
@.planning/phases/06-store-release/06-13-TASK3-NOTES.md

Bestehendes Prüfskript (Quelle, NICHT im Repo):
C:/Users/Student/AppData/Local/Temp/claude/C--Users-Student/8670d134-5812-468a-9b79-9c889538438a/scratchpad/langaudit/
- audit.mjs (170 Zeilen): Login je Konto, Haupttext, Dialoge aller nicht zerstörenden Buttons der ersten Weltzeile, Spielzeit-Bearbeiten-Dialoge, 9 API-Fehleraufrufe, Detektor `foreign(text, lang)` aus exklusiven Wortmengen, DATA-Ausnahmeliste, Positivkontrolle nur "de-Haupttext als en".
- dump_catalog.py: schreibt server.json aus gameworld.i18n.catalog_en/catalog_fr (de = Schlüssel).
- escape_quote.py: ersetzt U+2019 durch \u2019 (Hilfsmittel, nur übernehmen falls weiter gebraucht).
- Letzter Lauf run5.log: ein Treffer "fr admin main de: eltern" (prüfen, ob echter Befund oder Datenwort).

<interfaces>
Umgebung (verifiziert):
- Nextcloud: http://localhost:8091, App: /index.php/apps/app_api/embedded/gameworld/gameworld
- ExApp-API im Browser: fetch('/index.php/apps/app_api/proxy/gameworld' + path) mit Headern requesttoken: OC.requestToken, X-Gameworld-Language: <lang>
- occ: docker compose -p gameworld-dev -f scripts/dev/compose.yaml exec -T -u www-data app php occ ...
- Konten/Passwörter wie im Quellskript ACCOUNTS: Login "admin" mit Passwort gameworld-dev-admin (das ist das NC-Admin-Konto der Aufgabe; vor dem Lauf per occ user:info admin bestätigen), gw-lehrer (gw-lehrer-abnahme-13), mia (gameworld-demo-mia-13)
- Playwright ist keine Projektabhängigkeit: NODE_PATH=C:/Users/Student/AppData/Local/npm-cache/_npx/9833c18b2d85bc59/node_modules (Ausweich: .../_npx/e41f203b7505f1fb/node_modules); Muster createRequire(join(process.env.NODE_PATH ?? '.', 'x.js')) wie in scripts/dev/screenshot-capture.mjs
- Docker-Proxy für pytest: tcp://127.0.0.1:23750 (GAMEWORLD_DOCKER_URL), Marker "docker"; GAMEWORLD_REQUIRE_DOCKER=1 lässt e2e bei fehlendem Proxy fehlschlagen statt überspringen; tests/conftest.py docker_cleanup räumt nur Container/Volumes der Test-Instanz (Label gameworld.instance)
- Sprach-Sicherungsordner und Restore-Zusatz: src/gameworld/backup/naming.py PRE_RESTORE_SUFFIXES = {"de": "vor-restore", "en": "before-restore", "fr": "avant-restauration"}; Ordner Sicherungen/Backups/Sauvegardes
- Rechte: src/gameworld/access/roles.py require_verwalter (Prefix /api: worlds, backups, invites, setup-check, talk, playtime, pause, alerts), require_nc_admin (Prefix /api/admin: verwalter-groups, groups, orphans, attempts, review, origin); /api/me, /api/my/worlds, /api/my/playtime für alle angemeldeten Konten

API-Routen (aus src/gameworld/api/*.py):
- /api/worlds GET/POST; /api/worlds/{id}/start|stop|restart|language POST; DELETE /api/worlds/{id}; /api/presets GET
- /api/worlds/{id}/backups GET/POST; /api/worlds/{id}/restore POST
- /api/worlds/{id}/players GET; /api/worlds/{id}/invites POST; /api/worlds/{id}/invites/remove POST
- /api/players/password|adult|name POST; /api/settings GET/POST
- /api/playtime GET; /api/playtime/children/{nc_user} POST/DELETE; /api/playtime/holidays POST, DELETE /{id}; /api/playtime/time-zone POST; /api/playtime/worlds/{id}/window POST/DELETE
- /api/pause GET/POST, /api/pause/end, /api/pause/schluss POST
- /api/setup-check GET; /api/talk GET; /api/worlds/{id}/talk/read-only POST/DELETE; /api/worlds/{id}/talk/recreate POST; /talk/bot POST
- /api/admin/verwalter-groups GET, /add, /remove POST; /api/admin/groups GET; /api/admin/orphans GET, /container/remove, /volume/remove POST; /api/admin/attempts GET; /api/admin/review GET, /review/prefs GET/POST; /api/admin/origin POST
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Prüfwerkzeug ins Repo übernehmen, Detektor mit Positivkontrolle absichern</name>
  <files>scripts/audit/README.md, scripts/audit/dump_catalog.py, scripts/audit/lang_detector.mjs, scripts/audit/selftest.mjs</files>
  <read_first>
    - Quell-Skripte im Scratchpad-Ordner langaudit (audit.mjs, dump_catalog.py, escape_quote.py, run5.log)
    - scripts/dev/screenshot-capture.mjs (NODE_PATH-Muster, Konventionen)
    - src/gameworld/i18n/__init__.py (Katalogstruktur, translate)
  </read_first>
  <action>
Ordner scripts/audit/ anlegen. dump_catalog.py übernehmen (Ausgabepfad als Argument, Standard .dev/audit/server.json, Lauf per `uv run python scripts/audit/dump_catalog.py <out>`), zusätzlich Mod-Texte und Benachrichtigungstexte aufnehmen, sofern sie in eigenen Katalogen liegen (grep in src/gameworld nach weiteren MESSAGES/TEMPLATES-Dicts und in den Luanti-Mods nach Sprachtabellen; gefundene Quellen im README nennen). Detektor aus audit.mjs herauslösen nach scripts/audit/lang_detector.mjs mit Exporten loadVocab(repo, serverJsonPath, langs) und foreign(text, lang); Logik bleibt: Wortmengen je Sprache aus frontend/src/i18n/<lang>/index.js plus Servertexten, exklusive Wörter je Sprache, DATA-Ausnahmeliste für Namen (Welten, Konten, Spiele, Produkte, Sprachnamen). DATA-Liste in eine eigene Datei-Konstante mit Kommentar je Eintragsgruppe; den Treffer "eltern" aus run5.log nicht vorsorglich auf die Ausnahmeliste setzen, sondern in Task 2 als möglichen Befund prüfen. scripts/audit/selftest.mjs schreiben (Gegenprobe NICHT mit dem Muster der Umsetzung): eigene, handgeschriebene Prüfsätze, die nicht aus den Wörterbüchern kopiert sind, also (a) Positivkontrollen: ein deutscher Satz als en geprüft, ein englischer Satz als fr, ein französischer als de, ein en-Satz mit genau einem eingestreuten deutschen Wort (z. B. "Sicherung") als en, jeweils MUSS ein Treffer der richtigen Fremdsprache kommen; (b) Negativkontrolle: je Sprache ein sauberer Satz der eigenen Sprache, MUSS ohne Treffer sein; (c) Abdeckungszahl: Anzahl exklusiver Wörter je Sprache ausgeben und Fehler bei weniger als 200. Exit-Code 1 bei jedem Versagen. Ausgangspunkt audit.mjs ins Repo kommt in Task 2 (erweitert); escape_quote.py nur übernehmen, wenn ein Werkzeug es wirklich braucht. README.md (englisch, kurz): Zweck, Voraussetzungen (Dev-Stack, NODE_PATH, uv), Reihenfolge dump_catalog, selftest, audit, functional, loadtimes, Ausgabeordner .dev/audit/261102/, Schutzregeln (fremde Welten 788fff30-/a60510fd- nie anfassen, lang-Settings sichern und zurücksetzen). Quellcode-Kommentare englisch. Commit: "test(audit): add language audit tooling with detector self-test" (Autor street1983nk, keine Claude-Session-Zeile, nicht pushen; .planning/config.json nicht stagen).
  </action>
  <verify>
    <automated>cd C:/Users/Student/gameworld && uv run python scripts/audit/dump_catalog.py .dev/audit/server.json && node scripts/audit/selftest.mjs . .dev/audit/server.json</automated>
  </verify>
  <done>selftest.mjs beendet mit Exit 0, alle Positivkontrollen melden die erwartete Fremdsprache, alle Negativkontrollen sind leer, exklusive Wortzahlen je Sprache stehen in der Ausgabe; Commit enthält nur scripts/audit/*.</done>
</task>

<task type="auto">
  <name>Task 2: Lauf Rollen x Sprachen x Desktop/390 px plus Funktions- und Negativtests an Wegwerf-Welten</name>
  <files>scripts/audit/audit.mjs, scripts/audit/functional.mjs</files>
  <read_first>
    - Quell-audit.mjs im Scratchpad-Ordner langaudit
    - frontend/src/views/ParentView.vue und die Kind-Ansicht in frontend/src/views/ (Buttons, Dialoge, Abschnitte Verwaltergruppen, Reste, Setup-Check, Talk)
    - src/gameworld/api/setup_check.py (AIO- und Compose-Kopierbefehle), src/gameworld/worlds/reconciler.py (Verhalten bei fehlendem Proxy, bevor der Proxy kurz gestoppt wird)
    - src/gameworld/access/roles.py (require_verwalter, require_nc_admin, Fehlertexte)
  </read_first>
  <action>
Vorher (Pflicht, Ausgabe nach .dev/audit/261102/baseline.txt): `docker ps -a --format '{{.Names}} {{.Status}}'`, `docker volume ls`, GET /api/worlds als Admin (IDs der bestehenden Welten), sowie `occ user:setting <konto> core lang` für admin, gw-lehrer, mia (ungesetzt oder Wert protokollieren). Die alte Endzeile des Quellskripts (alle Konten auf de setzen) ersetzen durch Rücksetzen auf genau diesen Ausgangszustand; war gw-lehrer ungesetzt, am Ende `occ user:setting gw-lehrer core lang --delete`.

scripts/audit/audit.mjs (Erweiterung des Quellskripts, importiert foreign aus ./lang_detector.mjs): je Sprache de/en/fr und Konto (admin, gw-lehrer, mia) Haupttext, JEDER Dialog jedes Buttons der Weltzeile (auch Stoppen, Neustarten, Löschen: Bestätigungsdialog nur öffnen, Text erfassen, mit Abbrechen schließen, niemals bestätigen, und nur an einer Wegwerf-Welt, die das Skript selbst über die API anlegt und am Ende löscht), Spielzeit-Bearbeiten je Kind, Ferien-, Pause-, Zeitzonen-, Spielername-, Passwort-, Erwachsen-Dialoge, Setup-Check-Abschnitt, Talk-Abschnitt, Admin-Abschnitte Verwaltergruppen, Reste, Prüfprotokoll. Zusätzlich je Ansicht Screenshot Desktop 1280x900 und 390x844 (Dateiname <lang>-<konto>-<ansicht>-<breite>.png unter .dev/audit/261102/shots/) und maschinelle Prüfung: document.documentElement.scrollWidth > clientWidth (waagerechtes Scrollen) sowie Elemente mit scrollWidth > clientWidth bei overflow hidden/text-overflow ellipsis (abgeschnittene Texte) mit ihrem Text protokollieren. Ergebnis report.json plus Textdateien je Punkt. Browser je Kontext schließen.

scripts/audit/functional.mjs (eigenes Skript, API über eingeloggte Playwright-Seite wie apiErrors im Quellskript, Meldungen jeweils durch foreign geprüft und mit Status protokolliert; höchstens 2 Wegwerf-Welten gleichzeitig, Namen mit Präfix "audit261102-", nur deren IDs werden gestoppt oder gelöscht, Schutzprüfung vor jedem DELETE/stop: ID nicht in baseline): (1) als gw-lehrer je Sprache Welt anlegen, starten, Status laufend abwarten (Timeout 120 s), Einladung mia und Entfernen, Spielzeitlimit für mia setzen und zurücknehmen (Ausgangswert vorher sichern), Zeitfenster setzen und löschen, Sicherung anlegen, Sicherungsliste prüfen auf Ordner Sicherungen/Backups/Sauvegardes je Kontosprache, Wiederherstellen und prüfen, dass die Vor-Restore-Sicherung den Zusatz vor-restore/before-restore/avant-restauration trägt, stoppen, löschen; die Welten pro Sprache seriell. Angelegte Sicherungsdateien der Wegwerf-Welten in Nextcloud Files nachher ebenfalls entfernen (nur Ordner, deren Name die Wegwerf-Welt-ID trägt). (2) als Admin: Verwaltergruppe lehrkraefte entfernen und wieder hinzufügen (Endzustand gleich Ausgangszustand), Talk-Hinweis an einer Wegwerf-Welt von gw-lehrer prüfen und dokumentieren, dass er erst nach Neuladen erscheint (bekannter Kleinbefund, NICHT fixen), Erwachsen-Marke umschalten und Nachlauf in ms messen (bekannter Kleinbefund, NICHT fixen, Ausgangswert wiederherstellen), Setup-Check lesen und AIO- und Compose-Kopierbefehl je Sprache erfassen und auf Vollständigkeit prüfen. (3) Ungültige Eingaben je Sprache: leerer und überlanger Weltname, unbekanntes Preset, unbekannte Welt-ID bei start/stop/delete/backups/restore, ungültige Ferien, negative Pause, ungültiger Spielername, unbekanntes Konto bei Einladung. (4) Rechte: mia gegen alle Verwalter- und Admin-Routen, gw-lehrer gegen alle /api/admin-Routen (nur lesende oder mit absichtlich ungültigem Körper, damit nichts verändert wird); erwartet 403 mit Meldung in Kontosprache. (5) Fehlender Proxy: nur wenn reconciler.py bei fehlendem Proxy keine Welt verändert, `docker stop gameworld-dev-gameworld-docker-proxy-1` für höchstens 60 s, Setup-Check und Weltenliste je Sprache erfassen, `docker start` sofort danach; sonst stattdessen pytest tests/test_service_unavailable.py tests/test_setup_check.py als Beleg verwenden und das im Bericht begründen. Nachher Vergleich mit baseline.txt (bestehende Welten und Volumes identisch, keine audit261102-Reste), Abweichung = blockierender Befund. Commit nur scripts/audit/: "test(audit): cover all actions, roles, languages and 390 px".
  </action>
  <verify>
    <automated>cd C:/Users/Student/gameworld && NODE_PATH=C:/Users/Student/AppData/Local/npm-cache/_npx/9833c18b2d85bc59/node_modules node scripts/audit/audit.mjs . .dev/audit/261102 && NODE_PATH=C:/Users/Student/AppData/Local/npm-cache/_npx/9833c18b2d85bc59/node_modules node scripts/audit/functional.mjs . .dev/audit/261102 && docker ps -a --format '{{.Names}}' | grep -c audit261102 | grep -qx 0</automated>
  </verify>
  <done>report.json und functional.json unter .dev/audit/261102/ decken 3 Rollen x 3 Sprachen ab, Screenshots Desktop und 390 px je Hauptansicht liegen vor, alle Rechte-Negativtests haben Status und Meldungssprache protokolliert, Baseline-Vergleich ohne Abweichung, keine Wegwerf-Welt übrig, lang-Settings im Ausgangszustand.</done>
</task>

<task type="auto">
  <name>Task 3: pytest, Docker-e2e, Ladezeiten, Aufräumprüfung und Befundbericht</name>
  <files>scripts/audit/loadtimes.mjs, .planning/quick/261102-plj-gameworld-volltest-vor-store-release-1-0/261102-plj-BEFUNDE.md</files>
  <read_first>
    - tests/conftest.py (docker_url, GAMEWORLD_REQUIRE_DOCKER, docker_cleanup)
    - .dev/audit/261102/report.json, functional.json, baseline.txt aus Task 2
  </read_first>
  <action>
pytest im Vordergrund mit Timeout: zuerst `uv run pytest -q -m "not docker"`, dann `GAMEWORLD_REQUIRE_DOCKER=1 uv run pytest -q -m docker tests/e2e` (seriell, Timeout 600000 ms je Aufruf; falls länger, die e2e-Dateien in zwei Gruppen teilen); Ausgaben nach .dev/audit/261102/pytest-unit.log und pytest-e2e.log. Vor und nach e2e `docker ps -a` gegen baseline vergleichen. scripts/audit/loadtimes.mjs: je Rolle (admin, gw-lehrer, mia) und Sprache de Hauptansicht 3-mal laden, gemessen ab goto bis sichtbare Weltentabelle bzw. Karte und (Verwalter) .playtime__list/.playtime__empty bzw. (Kind) Weltenkarten, plus Dauer der Haupt-API-Aufrufe aus page.on('response') (Timing via performance.getEntriesByType('resource')); Median und Maximum nach loadtimes.json; Schwellen im Bericht: über 3 s sollte vor Release, über 8 s blockierend. Commit nur scripts/audit/loadtimes.mjs: "test(audit): measure main view load times". Abschlussprüfung: keine audit261102-Container/Volumes, bestehende 788fff30-/a60510fd-Objekte unverändert, lang-Settings wie in baseline (für gw-lehrer bei vorher ungesetzt `occ user:setting gw-lehrer core lang` liefert leer), Browserprozesse beendet, `git status --short` zeigt außer .planning/config.json und dem Aufgabenordner keine Änderungen an Produktdateien. Dann 261102-plj-BEFUNDE.md auf Deutsch mit echten Umlauten, ohne Gedankenstriche U+2013/U+2014, ohne Emojis: Abschnitte Umfang und Umgebung (Versionen, Datum, Konten, Ausgangszustand lang-Settings), Detektor-Selbstprüfung (Ergebnis), Befundtabelle mit Spalten Nr, Schwere (blockierend / sollte vor Release / kosmetisch), Bereich, Rolle, Sprache, Reproduktion, Beleg (Pfad unter .dev/audit/261102/ oder Ausgabe), dann Abdeckungsmatrix Rollen x Sprachen x Ansichten/Dialoge/Meldungen, Rechte-Matrix, Darstellung Desktop/390 px, Testsuiten (Zahlen passed/failed/skipped), Ladezeiten-Tabelle, bekannte Kleinbefunde (Erwachsen-Marke Nachlauf gemessen, Talk-Hinweis erst nach Neuladen, loadTalk nicht gepollt) als "bestätigt, nicht gefixt", Aufräumnachweis, offene Punkte für die Owner-Sicht (u. a. Luanti-Client-Begriffe der Kinderanleitung mit echtem Client, falls nicht automatisierbar). Jeder Detektortreffer wird gelesen und entweder als Befund oder begründet als Datenwort eingeordnet. Nach dem Schreiben per Python-Einzeiler auf U+2013/U+2014 prüfen (grep -P versagt hier bei \x{2013}). Keine Produktfixes.
  </action>
  <verify>
    <automated>cd C:/Users/Student/gameworld && test -f .planning/quick/261102-plj-gameworld-volltest-vor-store-release-1-0/261102-plj-BEFUNDE.md && uv run python -c "import sys; t=open(sys.argv[1],encoding='utf-8').read(); sys.exit(1 if chr(0x2013) in t or chr(0x2014) in t else 0)" .planning/quick/261102-plj-gameworld-volltest-vor-store-release-1-0/261102-plj-BEFUNDE.md && grep -c 'Schwere' .planning/quick/261102-plj-gameworld-volltest-vor-store-release-1-0/261102-plj-BEFUNDE.md && test -f .dev/audit/261102/pytest-e2e.log && test -f .dev/audit/261102/loadtimes.json && git diff --name-only -- src frontend appinfo | wc -l | grep -qx 0</automated>
  </verify>
  <done>Beide Suiten gelaufen und protokolliert, Ladezeiten gemessen, Bericht vollständig mit Schwere, Reproduktion, Rolle, Sprache und Beleg je Befund, Aufräumnachweis ohne Abweichung, keine Änderung an src/, frontend/, appinfo/.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Prüfskript -> Dev-Nextcloud/ExApp | Skript handelt mit echten Konten gegen lokale Instanz, zerstörende Aufrufe möglich |
| Prüfskript -> Docker (Proxy stoppen, e2e) | Eingriff in Container der Dev-Instanz neben fremden Owner-Welten |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-plj-01 | Tampering | functional.mjs stop/delete | mitigate | Nur IDs von selbst angelegten Welten mit Präfix audit261102-; Schutzprüfung gegen baseline-IDs vor jedem stop/DELETE; Bestätigungsdialoge in audit.mjs nie bestätigen |
| T-plj-02 | Denial of Service | Proxy-Stopp, RAM | mitigate | Proxy höchstens 60 s und nur nach Prüfung von reconciler.py; höchstens 2 Wegwerf-Welten; seriell; Browser je Kontext schließen |
| T-plj-03 | Tampering | lang-Settings, Verwaltergruppen, Spielzeit, Erwachsen | mitigate | Ausgangszustand vorher protokollieren und exakt wiederherstellen; gw-lehrer lang bei vorher ungesetzt per --delete |
| T-plj-04 | Information Disclosure | Commits | mitigate | Nur scripts/audit/ committen; Dev-Passwörter stehen bereits im bestehenden Prüfskript der Dev-Instanz, keine echten Zugangsdaten; nicht pushen |
| T-plj-SC | Tampering | Paketinstallationen | accept | Keine neuen Pakete; Playwright aus vorhandenem npx-Cache wie bei screenshot-capture.mjs |
</threat_model>

<verification>
- selftest.mjs Exit 0 (Positiv- und Negativkontrolle)
- report.json, functional.json, loadtimes.json, pytest-*.log unter .dev/audit/261102/
- baseline-Vergleich ohne Abweichung, keine audit261102-Reste, lang-Settings im Ausgangszustand
- git log zeigt nur Commits mit scripts/audit/*, keine Produktdateien geändert
</verification>

<success_criteria>
Owner erhält mit 261102-plj-BEFUNDE.md eine vollständige, belegte Befundliste über alle Rollen, Sprachen, Funktionen, Fehlerpfade, Darstellungen und Suiten; das Prüfwerkzeug ist wiederholbar im Repo; Dev-Instanz und fremde Welten sind unverändert.
</success_criteria>

<output>
Create `.planning/quick/261102-plj-gameworld-volltest-vor-store-release-1-0/261102-plj-SUMMARY.md` when done
</output>
