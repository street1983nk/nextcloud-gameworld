# Phase 6: Store-Release - Research

**Recherchiert:** 24.10.2026 (Primärquellen gelesen: AppAPI-Quelltext main/stable32/stable35, HaRP-README und -Dockerfile, App-Store-Schema info.xsd und REST-Doku, NC-Server provisioning_api stable32/stable35, Talk-Doku und -Quelltext, offizielles app-skeleton-python, ghcr-Manifeste; eigener Code gelesen, nichts geändert, kein Docker gestartet)
**Domain:** Nextcloud-ExApp-Veröffentlichung (AppAPI/HaRP, App Store, ghcr.io), Rollenmodell über OCS, Talk-Besitz, Spielzeit-Ausnahme
**Konfidenz gesamt:** HIGH für AppAPI-/Store-/OCS-Mechanik (Quelltext gelesen), MEDIUM für AIO-Testaufbau und Image-Details, LOW nur wo markiert

Konfidenz-Markierung wie in SCHULEN.md: [H] = Originalquelle oder Quelltext gelesen (entspricht VERIFIED/CITED), [M] = Doku plus Ableitung oder mehrere Quellen, [L] = Einzelquelle, Training oder Schätzung (entspricht ASSUMED, braucht Bestätigung).

<user_constraints>
## User Constraints (aus 06-CONTEXT.md, wörtlich)

### Locked Decisions

#### Verwalter-Gruppen (ROLLE-03)
- **D-01:** Ein Gruppen-Verwalter (Nicht-NC-Admin) lädt nur Konten aus Gruppen ein, in denen er selbst Mitglied oder Subadmin ist. Die App nutzt die Nextcloud-Sichtbarkeitsregeln wie vorgesehen (keine Lookups mit App-Systemrechten, keine Privacy-Umgehung); die Grenze wird in der UI verständlich erklärt. Harte Folge aus dem Research: Kontenabgleich und purge_missing_accounts dürfen NIE im Namen eines Nicht-Admin-Verwalters laufen (404-Falle, sonst würden Konten fälschlich vergessen).
- **D-02:** Die zusätzlichen Verwalter-Gruppen stellt der NC-Admin in einem eigenen Admin-Abschnitt der Gameworld-UI ein; der Abschnitt ist nur für echte NC-Admins sichtbar. Default bleibt die Gruppe admin.
- **D-03:** Alle Verwalter sehen alle Welten (heutiges Familienmodell bleibt; worlds bekommt KEIN owner_uid). Das Besitzer-Modell je Lehrkraft kommt erst im Schul-Meilenstein (v2, siehe SCHULEN.md). Sicherungen bleiben je Verwalter getrennt (D-13 aus Phase 5).
- **D-04:** Globale Einstellungen (Pause für alle, Ferien, Zeitzone, Spieler-Adresse) dürfen alle Verwalter bedienen, nicht nur NC-Admins.

#### Erwachsen-Schalter (ROLLE-04)
- **D-05:** "Erwachsen" gilt global je Konto, nicht je Welt-Einladung. Ein Zustand pro Person.
- **D-06:** Der Schalter sitzt im Einladen-Dialog UND in der Spielerliste (nachträglich änderbar). Nur Verwalter können ihn setzen.
- **D-07:** Einschalten verlangt einen Bestätigungsdialog, der die Folgen in Klartext nennt ("<Name> spielt dann ohne Pause, Zeitfenster und Spielzeitregeln"). Ausschalten geht ohne Dialog.
- **D-08:** Das Umschalten wirkt sofort, auch mitten im Spiel (Muster wie der Einladungs-Widerruf): Erwachsen hebt Pause/Zeitfenster/Limits sofort auf, zurück auf Kind greifen die Regeln sofort wieder. Erwachsene erscheinen nicht im Tagesrückblick und bekommen nie Verwaltungs- oder Luanti-Adminrechte.

#### Store-Auftritt
- **D-09:** Store-Listing dreisprachig: Englisch, Deutsch, Französisch (wie Findling 1.5.1). Stil: Faktenliste, kein Marketing (bestehende Owner-Regel); Entwurf vor dem Release zur Owner-Abnahme.
- **D-10:** Voller Screenshot-Satz 5-6 Bilder (Weltliste, Einladen, Kinder-Ansicht, Sicherungen, Spielzeit-Dialog, Handy-Ansicht), gemeinsam per Playwright aufgenommen, versionierte Dateinamen (-v1; Spiegel refetcht nie).
- **D-11:** Die Zusatz-Privilegien (Docker-Socket-Proxy, UDP-Ports) bekommen einen eigenen Abschnitt OBEN im Listing ("Was diese App darf und warum") plus ausführliche privacy.md im Repo. Ehrlichkeit als Verkaufsargument (Roadmap-Kriterium 4).
- **D-12:** privacy.md und öffentliche Repo-Doku auf Englisch als Hauptfassung, deutsche Fassung daneben verlinkt (privacy.de.md; Findling-Muster hardening/privacy).

#### Release-Mechanik
- **D-13:** Store-Version 1.0.0 (v1 ist nach dieser Phase feature-komplett, 27/27 Requirements).
- **D-14:** ExApp-Image auf ghcr.io am Repo street1983nk/nextcloud-gameworld, Build per GitHub Actions, Tag je Release.
- **D-15:** Deinstallation: Welt-Container werden gestoppt und entfernt, Spielstand-Volumes und Sicherungen in den Files BLEIBEN (kein stiller Datenverlust). Das Orphan-Kommando listet Reste auf und löscht sie gezielt; das Verhalten wird im Listing ehrlich beschrieben.
- **D-16:** Verwaiste Talk-Räume (Besitzer gelöscht oder kein Verwalter mehr) gehen an den dienstältesten bestätigten Verwalter; der Reconciler prüft das regelmäßig. Kein Raum bleibt ohne handlungsfähigen Besitzer (talk_rooms.owner_uid).

#### Rahmenbedingungen
- **R-01:** Die Store-Zertifikatsanfrage läuft (nextcloud/app-certificate-requests PR #1364, offen seit 21.10.2026). Owner-Vorgabe: NICHT nachhaken, einfach warten. Der eigentliche Store-Upload (Signieren + Submit) ist der letzte Plan der Phase, NICHT autonom und hängt am gemergten Zertifikat; alle anderen Pläne sind davon unabhängig.
- **R-02:** Test der Store-Installation auf AIO und Standard-Compose (Roadmap-Kriterium 1) gehört in die Phasenabnahme.

### Claude's Discretion
- Technische Umsetzung des Gruppen-Lookups (OCS-Endpunkte, Caching) und der sofortigen Wirkung des Erwachsen-Schalters.
- Form des Orphan-Kommandos (occ-Subcommand vs. API+UI), solange Roadmap-Kriterium 3 erfüllt ist.
- Setup-Check-Texte und AIO-Testaufbau.
- Kategorie und Schlagworte im Store (naheliegend: Games/Tools).

### Deferred Ideas (OUT OF SCOPE)
- Besitzer-Modell je Welt (jede Lehrkraft sieht nur eigene Welten), Schul-Meilenstein v2 (SCHULEN.md, Bedingungen: Store-Release stabil, Pilotpartner, Lasttest 30 Spieler).
- Weitere Listing-Sprachen über EN/DE/FR hinaus, nach Nachfrage.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Beschreibung | Research-Grundlage |
|----|--------------|--------------------|
| PLATT-01 | Gameworld ist als ExApp über den Nextcloud App Store installierbar (AppAPI/HaRP, Ziel NC 32+) | Abschnitte 3 (Image/HaRP), 4 (CI/ghcr), 5 (Store-Mechanik), 6 (Deinstallation), 7 (Setup-Check), 9 (Testaufbau AIO/Compose); Befunde F-01, F-02, F-05, F-06, F-07 |
| ROLLE-03 | NC-Admin stellt zusätzliche Verwalter-Gruppen ein; Mitglieder verwalten ohne NC-Admin zu sein; Default admin | Abschnitt 1 (OCS-Sichtbarkeit, 404-Falle, Routen-Sperre), Befunde F-03, F-04 |
| ROLLE-04 | Erwachsen-Schalter: frei von Pause, Zeitfenstern, Spielzeitregeln, nicht im Rückblick, keine Verwaltungs-/Luanti-Adminrechte, nur Verwalter setzen | Abschnitt 2 (Engine-Schnitt über die vorhandene frei-Zeile) |
</phase_requirements>

## Project Constraints (aus CLAUDE.md und Owner-Regeln)

- Python-ExApp über AppAPI, `AsyncNextcloudApp`, nie Sync-API; nc_py_api 0.30.3, FastAPI 0.143.2, uvicorn 0.54.0, docker 7.2.0 gepinnt (pyproject.toml).
- HaRP ist der Ziel-Deploy-Weg (NC 32+); DSP ist deprecated.
- Qualitätsgates vor jedem Commit lokal grün: ruff-Vollsatz, ruff format, pyright basic (`PYRIGHT_PYTHON_FORCE_VERSION=latest`), vulture.
- Docker-Zugriff nur über den gescopten tecnativa-Proxy (CONTAINERS, IMAGES, POST, VOLUMES = 1, Rest 0), nie roher Socket.
- Luanti-Pin per Digest (Index-Digest, siehe F-08), nie `latest`/`master`.
- Doku in Deutsch mit echten Umlauten, keine Em-/En-Dashes, keine Emojis; Umlaute nur in Prosa, nie in Code/URLs/YAML-Schlüsseln.
- Commits als street1983nk <k.cherif@outlook.de>, keine Claude-Trailer, Owner ist einziger Contributor.
- Store-/README-Texte: Faktenliste, Entwurf vor Release zeigen; Release-Beschreibung auf GitHub als englische Faktenliste; versionierte Bildnamen.
- Gameworld-Regel: sicherheitsrelevante Teile mit höchster Sorgfalt, deep Review plus /gsd-secure-phase, Negativtests Pflicht.
- Owner-Abnahmen von UI gemeinsam per Playwright.
- Parallel nur bei genug RAM; unter etwa 4 GB frei seriell testen.
- Claude sendet nie Mails/Posts; Store-Upload nicht autonom (R-01).
- GitHub-Actions im Repo sind per Commit-SHA gepinnt (Muster luanti-wasm.yml).

## Summary

Die Phase hat drei sehr unterschiedliche Teile: Rollen (ROLLE-03/04), Talk-Besitz und die eigentliche Store-Fähigkeit (PLATT-01). Die Recherche im Quelltext hat mehrere Befunde ergeben, die den Plan direkt formen und teils Owner-Entscheide brauchen:

1. **Es gibt noch kein ExApp-Image.** Das Repo hat weder Dockerfile noch Image-Workflow; bisher lief alles per manual-install als Host-Prozess. Phase 6 baut Dockerfile (mit FRP-Client, start.sh, Unix-Socket für HaRP), Multi-Arch-Build (amd64 und arm64, Luanti-Image und HaRP gibt es für beide) und die ghcr.io-Pipeline. Neue ghcr-Pakete sind privat, bis man sie einmal von Hand öffentlich schaltet. [H]
2. **AppAPI kann Deinstallieren und Update nicht unterscheiden.** Deinstallieren, Update und Deaktivieren rufen alle zuerst `PUT /enabled?enabled=0` und entfernen bzw. stoppen danach den ExApp-Container. Einen eigenen Deinstallations-Hook gibt es nicht. D-15 ("bei Deinstallation Container stoppen und entfernen") geht deshalb nur, wenn Gameworld die Welt-Container bei JEDEM Deaktivieren stoppt und entfernt und der Boot-Abgleich sie nach Update und Aktivieren aus den Volumes neu erzeugt. Das ist technisch sauber, ändert aber das Update-Verhalten (Kinder werden bei einem ExApp-Update kurz getrennt). Owner-Entscheid nötig (Offene Frage 1). [H]
3. **ROLLE-03 bricht heute an der AppAPI-Routensperre.** `^/api/.*` steht in info.xml auf ADMIN, und AppAPI prüft ADMIN mit `IGroupManager::isAdmin`. Ein Verwalter aus "lehrkraefte" bekäme auf jede Verwaltungsroute 404. Die Route muss auf USER, `require_verwalter` wird damit die einzige Sperre; ein strukturierter Test muss jede `/api/`-Route außer `/api/me` und `/api/my/*` auf diese Abhängigkeit prüfen. [H]
4. **Die 404-Falle ist breiter als bekannt.** Ein Verwalter, der nur Mitglied (nicht Subadmin) einer Gruppe ist, darf deren Mitgliederliste lesen, bekommt aber für jedes einzelne dieser Konten `GET /cloud/users/{id}` = 404. Der heutige Gruppen-Abgleich (`_resolve`) fragt jedes Konto einzeln ab und würde alle Gruppen-Eingeladenen entfernen. Nicht nur purge, sondern jeder Pfad, der aus "nicht gefunden" Zugänge entfernt, darf nur als bestätigter NC-Admin (oder als Subadmin für Konten seiner Gruppen) laufen. [H]
5. **NC 35 ist aktuell, NC 32 ist EOL.** info.xml erlaubt nur 32 bis 34; NC 35.0.2 (15.10.2026) könnte Gameworld aus dem Store nicht installieren. max-version muss auf 35. [H]
6. **Die UI ist nur deutsch.** Kein l10n im Frontend, Kindertexte im Spiel deutsch. Das dreisprachige Listing muss das ehrlich sagen ("Interface: German"). [H]

**Primäre Empfehlung:** Zuerst die Rollen- und Routenumstellung mit Negativtests (höchste Sicherheitsrelevanz), parallel Image plus CI, dann Lebenszyklus (Deaktivieren/Orphans/Setup-Check), dann Doku/Listing, Dev-HaRP-Abnahme, und als letzter, nicht autonomer Plan der Store-Upload nach gemergtem Zertifikat. Die Registry-Installation lässt sich VOR dem Zertifikat vollständig testen (`occ app_api:app:register gameworld <daemon> --info-xml <url>`).

## Architectural Responsibility Map

| Fähigkeit | Primäre Schicht | Sekundäre Schicht | Begründung |
|-----------|-----------------|-------------------|------------|
| Verwalter-Gruppen speichern und prüfen | ExApp-Backend (SQLite meta) | NC OCS (Gruppen der Selbstauskunft) | Rolle wird je Anfrage aus NC abgeleitet (ROLLE-02), Konfig gehört der App |
| Routensperre für Verwaltung | ExApp-Backend (`require_verwalter`) | AppAPI/HaRP nur noch USER | AppAPI kennt nur "NC-Admin", keine eigenen Verwalter-Gruppen |
| Einladungs-Umfang je Verwalter | NC OCS im Namen des Verwalters | ExApp prüft Mitgliedschaft | D-01: NC-Sichtbarkeit ist die Grenze |
| Konten vergessen/Gruppen-Entfernen | ExApp-Hintergrund als bestätigter NC-Admin | | 404-Falle (F-04) |
| Erwachsen-Flag | ExApp-Backend (Schema 8) | Zeit-Mod in der Welt (frei-Zeile) | Durchsetzung bleibt serverseitig im Mod |
| Talk-Besitzwechsel | ExApp-Reconciler | Talk OCS (Moderator) | Talk kennt keinen Owner-Wechsel per API |
| ExApp-Image | ghcr.io (CI) | AppAPI zieht per info.xml | D-14 |
| Store-Eintrag | apps.nextcloud.com | GitHub-Release-Asset (tar.gz) | Store speichert nur Metadaten, lädt Archiv zur Prüfung |
| Aufräumen bei Deaktivieren | ExApp `enabled_handler(False)` | Boot-Abgleich erzeugt neu | Einziger Hook, den AppAPI sendet (F-02) |
| Orphan-Suche nach Deinstallation | Host-Skript (docker CLI) | In-App-Liste solange installiert | Nach Deinstallation gibt es keine ExApp mehr |

## Wichtigste Befunde (F-01 bis F-12)

| # | Befund | Konfidenz | Folge für den Plan |
|---|--------|-----------|--------------------|
| F-01 | Kein Dockerfile, kein Image-Workflow im Repo; info.xml zeigt auf `ghcr.io/street1983nk/gameworld:0.1.0`, das es nicht gibt | [H] Repo gelesen | Eigener Plan "Image + CI" |
| F-02 | Uninstall (UI und occ), Update und Disable rufen alle `disableExApp` = `PUT /enabled?enabled=0`, danach Container stoppen (Disable) bzw. entfernen (Uninstall/Update). Kein eigener Uninstall-Hook | [H] app_api `ExAppsPageController::uninstallApp`, `Command/ExApp/Update.php:168`, `AppAPIService::disableExApp` | D-15 nur über Deaktivieren-Handler umsetzbar, Owner-Entscheid (Offene Frage 1) |
| F-03 | AppAPI-Routenstufe ADMIN = `groupManager->isAdmin($userId)` | [H] `ExAppProxyController.php:355` | `^/api/.*` auf USER, Python-Sperre wird alleinige Sperre |
| F-04 | `GET /cloud/users/{id}` liefert für fremde Konten nur Admin, delegiertem Admin oder Subadmin mit Zugriff Daten, sonst 404 (wie gelöscht). `GET /cloud/groups/{gid}` (nc_py_api `get_members`) erlaubt zusätzlich Mitgliedern der Gruppe; Reihenfolge: Gruppe fehlt = 404, Gruppe da aber kein Recht = 403 | [H] provisioning_api stable32 `AUserDataOCSController::getUserData`, `GroupsController::getGroupUsers` | Mitglied-Verwalter: Gruppenliste ja, Einzelkonto nein; `_resolve` darf für sie kein `user()` je Mitglied rufen |
| F-05 | NC 35.0.2 ist aktuell (15.10.2026), NC 32 EOL seit 09/2026 (letzte 32.0.15), 33/34/35 unterstützt | [H] GitHub-Releases, Wiki Maintenance-Schedule | `max-version="35"`; min-version 32 kann bleiben, Test auf 34 und 35 |
| F-06 | Unter AIO-HaRP (`harp_aio`, `exapp_direct: true`) setzt AppAPI KEIN `HP_SHARED_KEY` im ExApp-Container; Netz `nextcloud-aio`; HaRP-Host `nextcloud-aio-harp:8780` | [H] stable35 `AIODockerActions`, `DockerActions::buildDeployParams` | `lifecycle.api_base()` wählt unter AIO den PHP-Proxy-Pfad (funktioniert, nur langsamer); nc_py_api bindet dann TCP statt Unix-Socket (richtig für Direktmodus) |
| F-07 | App Store info.xsd kennt unter `external-app` nur `docker-install`, `scopes`, `system`, `environment-variables`; `routes` wird vorher per pre-info.xslt herausgefiltert. AppAPI liest Routen aus dem info.xml im heruntergeladenen Archiv | [H] appstore `info.xsd`, `pre-info.xslt`, app_api `ExAppArchiveFetcher` | Bestehendes info.xml passt; Routen bleiben drin |
| F-08 | Luanti-Pin `sha256:db682cae...` ist der Index-Digest von 5.17.0 (amd64 + arm64); HaRP-Image amd64 + arm64; tecnativa v0.5.0 multi-arch | [H] ghcr-Manifest abgefragt | arm64-Image der ExApp lohnt (Raspberry Pi 5 als Heimserver) |
| F-09 | Talk: Beförderung nur zum Moderator (Typ 2), Owner (Typ 1) kann von Moderatoren weder entfernt noch herabgestuft werden; Raum löschen dürfen Moderatoren; gelöschtes Konto wird aus allen Räumen entfernt, Raum bleibt (außer letzter Teilnehmer) | [H] spreed docs/participant.md, conversation.md, `Manager::removeUserFromAllRooms` | D-16 = Gameworld-Besitz (owner_uid) plus Moderator; ein Ex-Verwalter, der noch existiert, bleibt Talk-Owner (Offene Frage 3) |
| F-10 | Frontend ohne l10n, Spieltexte deutsch | [H] frontend/src gelesen | Listing nennt "Interface: German" |
| F-11 | Docker-Desktop-VM dieses Rechners hat 6,2 GB (MemTotal 6213029888) | [H] `docker info` | AIO-Test nur mit gestopptem Dev-Stack, seriell |
| F-12 | AppAPI stable35 kennt ExApp-Setup-Checks in der NC-Verwaltungsübersicht (`ExAppSetupCheckService`), stable32 bis 34 nicht | [H] Raw-Abruf je Branch: 404 auf 32/33/34, 200 auf 35 | Nur optional, Hauptweg bleibt der eigene Setup-Check in der Gameworld-Seite |

---

## 1. ROLLE-03: Verwalter-Gruppen

### 1.1 Was Nextcloud einem Nicht-Admin-Verwalter gibt (NC 32 bis 35)

| Aufruf (im Namen des Verwalters) | Ergebnis | Quelle |
|---|---|---|
| `GET /ocs/v1.php/cloud/user` (Selbstauskunft, nutzt `nc_profile`) | eigene `groups` UND `subadmin` (Liste der Subadmin-Gruppen) | [H] `getUserData`: `$data['groups']`, `$data['subadmin']`; nc_py_api `UserInfo.subadmin` vorhanden |
| `GET /cloud/groups/{gid}` (nc_py_api `users_groups.get_members`) | 200 für Admin, delegierten Admin, Subadmin der Gruppe, Mitglied der Gruppe; 403 sonst; 404 wenn Gruppe fehlt | [H] |
| `GET /cloud/users/{uid}` fremdes Konto | 200 nur für Admin, delegierten Admin, Subadmin mit `isUserAccessible`; sonst 404 (nicht 403!) | [H] |
| `GET /cloud/users/{self}/subadmins/details` | eigene Subadmin-Gruppen mit Details; unnötig, weil die Selbstauskunft `subadmin` schon liefert | [H] |

- "Echter NC-Admin" für D-02 = `"admin" in profile.groups` (genau die Prüfung von `IGroupManager::isAdmin`). Delegierte Admins zählen bei Nextcloud bei manchen Abfragen wie Admins, sind aber keine NC-Admins im Sinne von D-02. [H]
- Die Selbstauskunft ist das einzige, was Gameworld für die Rolle braucht; Konfig = Liste von Gruppen-IDs, Rolle = Schnittmenge nicht leer. [H, eigener Code]

### 1.2 Konkreter Umbau (empfohlen)

1. **Konfig:** meta-Schlüssel `verwalter_groups` (JSON-Liste, sortiert, ohne Duplikate; `admin` immer implizit enthalten und nicht entfernbar). Lesen in `RoleService`; Ändern verwirft den Rollen-Cache aller Konten.
2. **Admin-Abschnitt (D-02):** Route z. B. `GET/POST /api/admin/verwalter-groups`, Abhängigkeit `require_nc_admin` (Selbstauskunft OHNE 30-s-Cache, weil Rechteausweitung). Die UI zeigt den Abschnitt nur, wenn `/api/me` `nc_admin: true` liefert; die Sperre ist trotzdem serverseitig.
3. **Gruppenprüfung beim Speichern:** jede Gruppe muss existieren (`group_exists` als handelnder NC-Admin). Warnhinweis in der UI: "Alle Mitglieder dieser Gruppe können Welten verwalten, Kinder einladen und die Pause auslösen." Keine Gruppe, in der Kinder sind; das kann Gameworld nicht prüfen, nur sagen. [M]
4. **Routen:** `^/api/.*` in info.xml von ADMIN auf USER. Danach gilt: jede Verwaltungsroute nur mit `require_verwalter`. Heute erfüllt (alle Router außer `me.py`, `talk_bot.py`, play haben `dependencies=[Depends(require_verwalter)]`). Neuer Strukturtest: über `APP.routes` iterieren, jede Route unter `/api/` außer `/api/me` und `/api/my/...` muss `require_verwalter` (oder `require_nc_admin`) in ihren Abhängigkeiten haben. `tests/test_info_xml.py` (`test_admin_catch_all_is_last`, ADMIN-Zählung) muss angepasst werden. [H]
5. **`role_of`:** `ROLE_VERWALTER if set(profile.groups) & verwalter_groups else ROLE_SPIELER`. Fail closed bleibt: Lookup-Fehler = 503. Kaputte/fehlende Konfig = nur `admin`.

### 1.3 Verwalter-Schnappschuss neu denken (wichtig)

Heute: `meta time_admins` = Mitglieder der Gruppe `admin`, geholt als handelnder Verwalter (`refresh_admins`), bestätigt im Hintergrund (`verify_admins`: Kandidat muss die Gruppe `admin` lesen können und selbst darin stehen). Dieser Schnappschuss steuert drei Dinge: frei-Zeile im Zeit-Mod, Empfänger der Benachrichtigungen, Talk-Moderatoren und das handelnde Konto der Wartung (purge, Talk-Abgleich).

Mit ROLLE-03 trennen sich zwei Mengen:

| Menge | Inhalt | Wofür |
|---|---|---|
| `verwalter` | Vereinigung der Mitglieder aller Verwalter-Gruppen | frei-Zeile, Benachrichtigungen, Talk-Moderatoren, Rückblick-Ausschluss |
| `nc_admins` | Mitglieder von `admin` | handelndes Konto für purge und für jeden Abgleich, der aus 404 Zugänge entfernt |

- Abruf je Gruppe getrennt: Ein Lehrer kann `lehrkraefte` lesen (Mitglied), aber nicht `admin` (403 → heute `DirectoryRejectedError`, Stand bleibt). Darum Schnappschuss je Gruppe speichern (`meta verwalter_members:<gid>` oder Tabelle `verwalter_snapshot(gid, uid)`), je Gruppe mit dem letzten erfolgreichen Stand. [H für 403-Verhalten, M für Speicherform]
- Bestätigung (`verify_admins`) je Gruppe: Kandidat bestätigt, wenn er die Gruppe lesen kann UND darin steht. Nie ungeprüft einfügen (CR-01 bleibt).
- `purge_accounts` und Talk-Abgleich: `acting` nur aus bestätigten `nc_admins`. Gibt es keinen (NC-Admin öffnet Gameworld nie), läuft purge nicht. Das ist fail safe; in der Doku nennen: "Gelöschte Konten räumt Gameworld auf, sobald ein Nextcloud-Admin Gameworld einmal geöffnet hat." [M]
- `refresh_snapshot`-Abhängigkeit (alerts.py, pause.py) und `refresh_admins` in `list_children` fragen heute `ADMIN_GROUP` fest ab; beides auf die Gruppenliste umstellen. Alle Stellen: `grep ADMIN_GROUP` (roles.py, playtime/service.py), `META_TIME_ADMINS` (engine.py, talk/service.py, notify/loop.py). [H]

### 1.4 Einladen durch Nicht-Admin-Verwalter (D-01) und die 404-Falle

- **Gruppe einladen:** erlaubt, wenn die Gruppe in `profile.groups` oder `profile.subadmin` des Verwalters steht; Mitgliederliste per `get_members` als Verwalter (geht laut F-04). [H]
- **Einzelkonto einladen:** erlaubt, wenn das Konto Mitglied einer dieser Gruppen ist. Existenz ist dann durch die Gruppenliste belegt, NICHT durch `GET /cloud/users/{uid}` (gäbe 404 für Mitglied-Verwalter). Für Subadmins geht `user()` zusätzlich. [H]
- **Anzeigenamen:** für Mitglied-Verwalter nicht abrufbar; Rückfall Konto-ID (bestehendes Muster "Anzeigename ist Beiwerk"). Optional später über die Autocomplete-API (`/ocs/v2.php/core/autocomplete/get`), die die Teilen-Einstellungen der Instanz respektiert. [M, nicht im Quelltext geprüft]
- **Abgleich (`sync_all`, `_resolve`):** Für Gruppen-Einladungen bei Nicht-Admin-Handelnden kein `user()` je Mitglied, die Gruppenliste ist die Wahrheit; Entfernen aus einer Gruppe wirkt weiter (die Liste ist für ein Mitglied verlässlich). Für direkte Einladungen eines Kontos, das der Handelnde nicht sehen kann: nie entfernen, nur der NC-Admin-Abgleich darf das. Regel für den Plan: **"404 heißt gelöscht" gilt nur, wenn der Handelnde bestätigter NC-Admin ist.** [H für die Ursache, M für die Regel]
- **Deaktivierte Konten:** Mitglied-Verwalter sehen `enabled` nicht. Lösung: Prüfung auf deaktiviert nur im NC-Admin-Abgleich; die UI-Erklärung sagt, dass Gameworld deaktivierte Konten beim nächsten Admin-Abgleich ausschließt. [M]
- **UI-Grenze erklären (D-01):** "Du kannst Konten aus deinen Gruppen einladen: <liste>. Andere Konten zeigt dir Nextcloud nicht." Fehlertext statt "Konto unbekannt": "Dieses Konto ist in keiner deiner Gruppen."
- **Negativtests (Pflicht):** Lehrer lädt Konto außerhalb seiner Gruppen ein → 403/422 ohne DB-Änderung; Lehrer lädt fremde Gruppe ein → abgelehnt; Dashboard-Abruf durch Lehrer entfernt keinen einzigen Zugang (Fake-Directory gibt `user()` = None für alle); purge mit Lehrer als acting wird nie aufgerufen; Kind ruft jede Verwaltungsroute → 403; Lehrer ruft `/api/admin/verwalter-groups` POST → 403; Kind ist Mitglied einer als Verwalter-Gruppe konfigurierten Gruppe → wird Verwalter (dokumentiertes Verhalten, kein Fehler).

## 2. ROLLE-04: Erwachsen-Schalter

### 2.1 Wo greifen Pause, Zeitfenster, Limits heute

- Durchsetzung liegt komplett im Welt-Mod `gameworld_time`, gespeist aus der Regeldatei, die `TimeEngine.render` je Welt rechnet. [H]
- Der Mod kennt schon die Ausnahme `frei` (Zeile `-1 -1 -1 frei -`): Welt-Fenster und eigene Grenzen gelten nicht, und laut `time_mod.py:547/552` gilt auch die Pause "für alle außer frei". Nur der Sicherungs-Halt (`@halt`) trifft auch frei, das ist richtig so (Server stoppt). [H]
- `render` setzt `_FREI` heute für jedes eingeladene Konto in `parse_admins(meta time_admins)`. [H]
- Tagesrückblick: `book` zählt `play_daily` nur für Kinder mit Plan und nie für Verwalter. [H]

### 2.2 Kleinster sicherer Schnitt

- **Schema 8:** Tabelle `adults (nc_user TEXT PRIMARY KEY, set_by TEXT NOT NULL, set_at TEXT NOT NULL)`; `adults` in `ACCOUNT_TABLES` aufnehmen (sonst überlebt das Flag ein gelöschtes Konto, und eine neu angelegte gleiche ID wäre sofort erwachsen). [H, store.py ACCOUNT_TABLES gelesen]
- **Engine:** `frei = admins | adults` in `render` und `book` (Rückblick-Ausschluss). Pläne eines Erwachsenen bleiben in der DB und ruhen; zurück auf Kind greifen sie sofort wieder (D-08). Nichts am Mod ändern. [H]
- **Sofortige Wirkung:** Umschalten = DB-Schreiben plus `push_time` in alle Welten des Kontos unter `mutation()` (Muster `set_child`). Der Mod liest die Regeldatei alle paar Sekunden neu und trennt beim Zurückschalten im nächsten Takt (wie Widerruf). Verbrauch: zurück auf Kind zählt der bisherige Tagesverbrauch weiter; was als Erwachsener gespielt wurde, wurde nicht verbucht (book überspringt frei). [M, Ableitung aus engine.py]
- **API:** `POST /api/players/adult` `{nc_user, adult: bool}` im Router mit `require_verwalter`; Einladen-Dialog setzt es direkt nach erfolgreicher Einzel-Einladung (bei Gruppen-Einladung nur in der Spielerliste, weil das Flag je Person gilt). `set_child` für Erwachsene ablehnen oder Pläne erlauben aber kennzeichnen ("ruht, solange erwachsen"); empfohlen: erlauben und kennzeichnen.
- **Was Erwachsen nie tut:** keine Änderung an `require_verwalter`, an `minetest.conf`/`default_privs` oder an der Zugangsdatei. Gameworld vergibt ohnehin keine Luanti-Privs; ein Test prüft, dass die erzeugte Welt-Konfiguration für ein Erwachsenen-Konto identisch zur Kind-Konfiguration ist. [H]
- **Kind-Ansicht:** `/api/my/playtime` liefert für Erwachsene `limited: false`; ein Kind kann über `/api/my/*` nichts schreiben (nur GET-Routen, POST nur play-ticket). Negativtest: Kind sendet `POST /api/players/adult` für sich selbst → 403; Kind sendet es über die USER-Routen-Varianten (`/api/my/...`) → 404/405.
- **Verwalter + Erwachsen:** Schalter für Verwalter-Konten ausblenden (sie sind ohnehin frei); fällt ein Konto aus der Verwalter-Gruppe, gilt danach sein Erwachsen-Flag (falls gesetzt) oder die Kinderregeln.

## 3. ExApp-Image für HaRP (PLATT-01)

### 3.1 Pflichten aus HaRP-Doku und offiziellem Python-Skeleton [H]

- `start.sh` aus `nextcloud/HaRP/exapps_dev` als Entrypoint: schreibt `/frpc.toml` aus `HP_SHARED_KEY`, `HP_FRP_ADDRESS`, `HP_FRP_PORT`, `APP_ID`, `APP_PORT`, startet `frpc` im Hintergrund und dann die App. FRP-Proxy zeigt auf `unix:/tmp/exapp.sock`.
- nc_py_api `run_app` bindet bei gesetztem `HP_SHARED_KEY` auf `uds=/tmp/exapp.sock` (oder `HP_EXAPP_SOCK`), sonst auf `APP_HOST:APP_PORT`. Gameworld nutzt `run_app` bereits, passt also für FRP-Modus und AIO-Direktmodus. [H, nc_py_api 0.30.3 gelesen]
- frpc-Version wie HaRP und Skeleton: 0.71.1 mit Prüfsummen `FRP_AMD64_SHA256=1d9875210972a5d1a62b2dc4c48df45ab0af05d3ca1b5e494a014428259df803`, `FRP_ARM64_SHA256=8edf590b0c396fa42f9c147121a76af83cfc2002b08f5aef0ea1008c43482019` (aus HaRP-Dockerfile und app-skeleton-python übernommen, Stand 24.10.2026). [H]
- AppAPI kopiert FRP-Zertifikate per `docker cp` als root nach `/certs/frp`; das Verzeichnis muss für den Dienstnutzer lesbar sein; `/frpc.toml` für ihn schreibbar.
- HEALTHCHECK des Skeletons prüft nur, dass `frpc` läuft, wenn `HP_SHARED_KEY` gesetzt ist.
- Doku empfiehlt: Image-Standardnutzer root, Rechte zur Laufzeit per gosu abgeben.

### 3.2 Gameworld-spezifisch

- **Stufen:** (1) Node-Stufe: `npm ci --ignore-scripts && npm run build` (Bundle `js/gameworld-main.js`, nicht im Git); (2) Spiele-Stufe: `scripts/fetch-games.sh` gegen `vendor/games/SHA256SUMS` (VoxeLibre-Zip 84 MB wird geladen, minetest_game liegt im Git); (3) Python-Stufe: `uv sync --frozen --no-dev` aus `uv.lock`, frpc mit Prüfsumme; (4) Laufzeit `python:3.13-slim` mit `src/`, `js/`, `img/`, `vendor/games/`, `appinfo/`, `start.sh`, `healthcheck.sh`. [M]
- **Arbeitsverzeichnis:** `set_handlers` mountet `js/` und `img/` relativ zum cwd (Kommentar main.py); WORKDIR muss der App-Root sein. [H]
- **Persistenz:** AppAPI hängt das Volume `nc_app_gameworld_data` an `/nc_app_gameworld_data` und setzt `APP_PERSISTENT_STORAGE` darauf (SQLite, instance_id, Sicherungsaufträge). Das Volume gehört root; läuft die App als Dienstnutzer, muss der Entrypoint (als root) einmal `chown` auf das Speicherverzeichnis setzen und dann per gosu wechseln. [H für Volume/Variable, M für chown-Bedarf]
- **Browser-Spike:** luanti-wasm-Artefakte nicht ins Store-Image; `GAMEWORLD_BROWSER_SPIKE` bleibt aus, `/play/*` antwortet 404 (Owner-Entscheid 23.10.: Code bleibt, Flag aus). [H]
- **uvloop:** unter Linux nimmt uvicorn "auto" (uvloop aus `uvicorn[standard]`), es gibt Wheels für amd64 und arm64. [M]
- **api_base:** `HP_SHARED_KEY` fehlt unter AIO-Direktmodus (F-06), dann nimmt die UI den PHP-Proxy `/index.php/apps/app_api/proxy/gameworld`. AppAPI leitet den bei HaRP über `nextcloud_url/exapps/gameworld` weiter (`DockerActions::resolveExAppUrl`), funktioniert also, nur ohne WebSocket (für den ausgeschalteten Spike egal). [H]

## 4. CI: Image auf ghcr.io (D-14)

- **Workflow** `.github/workflows/image.yml`, Auslöser Tag `v*` plus `workflow_dispatch`; `permissions: contents: read, packages: write` (plus `id-token: write` und `attestations: write`, falls Provenance). [M]
- **Actions, per SHA gepinnt (Stand 24.10.2026, `gh api` abgefragt):** [H]
  - `actions/checkout` v7.0.1 `3d3c42e5aac5ba805825da76410c181273ba90b1`
  - `docker/setup-qemu-action` v4.4.0 `99012661954931238ded8c8b007157a8430204e1`
  - `docker/setup-buildx-action` v4.4.1 `f87e5991a6d7451dcb8d9637bfbc97413f497069`
  - `docker/login-action` v4.7.0 `81c6f93d4bc991e510b342a00b419b3bb4efc5c6`
  - `docker/metadata-action` v6.2.0 `dc802804100637a589fabce1cb79ff13a1411302`
  - `docker/build-push-action` v7.4.0 `c3c9e263c25d99ce0380d002d59b67737d91b0dc`
  - optional `actions/attest-build-provenance` v4.2.2 `4d101475d8b20a2381f78447822ac1eab6504dd8`
- **Plattformen:** `linux/amd64,linux/arm64` (F-08). QEMU ist am einfachsten; schneller wäre ein nativer `ubuntu-24.04-arm`-Runner mit Manifest-Zusammenführung. Für ein Release pro Woche reicht QEMU. [M]
- **Tags:** `1.0.0` (exakt der `image-tag` aus info.xml) plus `latest` nicht nötig; AppAPI zieht `registry/image:image-tag`. Der Workflow prüft, dass Git-Tag, info.xml `<version>`, `<image-tag>` und pyproject `version` übereinstimmen (Lockstep, wie `tests/test_info_xml.py`). [H für AppAPI-Image-Parameter]
- **Label:** `org.opencontainers.image.source=https://github.com/street1983nk/nextcloud-gameworld` verknüpft das Paket mit dem Repo. Der Paketname kann `gameworld` bleiben (info.xml `street1983nk/gameworld`). [M]
- **Sichtbarkeit (Falle):** neue ghcr-Pakete eines Nutzers sind privat; ein verknüpftes Paket erbt Zugriffsrechte, aber NICHT die Sichtbarkeit. Nach dem ersten Push einmal von Hand: Package settings → Change visibility → Public. Ohne das scheitert jede Installation mit 401/denied beim Pull. [H, docs.github.com]
- **Size:** VoxeLibre 84 MB plus Python-Laufzeit; Ziel unter 400 MB komprimiert. [L, Schätzung]

## 5. Store-Mechanik (ExApp)

### 5.1 Ablauf [H, appstore docs/developer.rst und docs/api/restapi.rst]

1. Zertifikat: `openssl req -nodes -newkey rsa:4096 -keyout gameworld.key -out gameworld.csr -subj "/CN=gameworld"`; CSR liegt als PR #1364 bei nextcloud/app-certificate-requests (R-01, warten). Nach Merge `gameworld.crt` aus dem Repo holen (Pfad `gameworld/gameworld.crt`, wie im Skeleton-Workflow).
2. **App einmalig registrieren** (Gameworld ist eine neue App-ID): `POST https://apps.nextcloud.com/api/v1/apps` mit `{"certificate": "<crt>", "signature": "<sig>"}`, Signatur = `echo -n "gameworld" | openssl dgst -sha512 -sign gameworld.key | openssl base64`. Antwort **HTTP 201** bei Neuregistrierung.
3. **Release hochladen:** `POST https://apps.nextcloud.com/api/v1/apps/releases` mit `{"download": "<https-URL des tar.gz>", "signature": "<sig>", "nightly": false}`, Signatur = `openssl dgst -sha512 -sign gameworld.key gameworld-1.0.0.tar.gz | openssl base64`. Antwort **HTTP 201** bei neuem Release. Auth `Authorization: Token <APPSTORE_TOKEN>` oder Basic. Das erklärt das Findling-Muster "2x HTTP 201" für Gameworld: Registrierung plus Release.
4. Archiv: genau ein Top-Ordner `gameworld/`, darin `appinfo/info.xml`; kein `.git`; tar.gz. Für eine ExApp reicht `gameworld/appinfo/info.xml` plus `img/app.svg` und `LICENSE`; AppAPI liest beim Installieren nur info.xml (und `l10n/`, falls vorhanden) und prüft die Archiv-Signatur selbst gegen das Zertifikat (`ExAppArchiveFetcher::downloadInfoXml`, `openssl_verify ... OPENSSL_ALGO_SHA512`). [H]
5. Download-URL: GitHub-Release-Asset `https://github.com/street1983nk/nextcloud-gameworld/releases/download/v1.0.0/gameworld-1.0.0.tar.gz`. Der Store lädt es zur Prüfung, speichert es nicht dauerhaft; AppAPI lädt es bei jeder Installation erneut. Das Asset darf also nie gelöscht werden. [H für Store-Verhalten, M für AppAPI]

- `occ integrity:sign-app` (signature.json) aus dem Skeleton-Workflow ist für PHP-Apps; AppAPI prüft bei ExApps nur die Archiv-Signatur. Nicht nötig. [M]
- Kein PHP-Code, keine `<php>`-Abhängigkeit; `<category>games</category>` ist im Schema erlaubt (Werte u. a. games, tools, integration, multimedia, social). Mehrere `<category>` sind erlaubt (z. B. games plus tools). [H]
- Mehrsprachig: `<name lang="de">`, `<summary lang="fr">`, `<description lang="..">` (jeweils eindeutig je Sprache, Schema `uniqueNameL10n` usw.); Beschreibung ist Markdown. `<screenshot>` (https-URL), `<documentation><user>/<admin>/<developer>` erlaubt. [H]
- info.xml muss `<version>1.0.0</version>` und `<image-tag>1.0.0</image-tag>` bekommen; pyproject `version = "1.0.0"` im Lockstep. [H]
- `<nextcloud min-version="32" max-version="35"/>` (F-05). [H]

### 5.2 Vorab-Test ohne Store (zertifikatsunabhängig)

- `occ app_api:app:register gameworld <daemon> --info-xml https://raw.githubusercontent.com/street1983nk/nextcloud-gameworld/v1.0.0/appinfo/info.xml --env GAMEWORLD_DOCKER_URL=... --wait-finish` zieht das Image aus ghcr.io genau wie eine Store-Installation; nur Archiv-Download und Signaturprüfung fehlen. Damit sind Kriterium 1 (Registry-Tag auf AIO und Compose) und die Abnahme vor dem Zertifikat machbar; nach dem Merge folgt ein kurzer echter Store-Durchlauf. [H, `Command/ExApp/Register.php` Optionen `--info-xml` (URL oder Pfad), `--env`, `--mount`, `--wait-finish`]

## 6. Deinstallation, Deaktivieren, Orphans (D-15, Kriterium 3)

### 6.1 Was AppAPI wirklich tut [H, app_api stable35/main]

| Aktion | Aufruf an die ExApp | Danach |
|---|---|---|
| Deaktivieren (UI, `occ app_api:app:disable`) | `PUT /enabled?enabled=0` (Timeout 60 s) | ExApp-Container gestoppt |
| Update | erst `disableExApp` (gleicher Aufruf), Routen entfernen | alter Container entfernt, neuer erzeugt, Heartbeat, `/init`, Aktivieren |
| Deinstallieren (UI `uninstallApp`, `occ app_api:app:unregister`) | `disableExApp` (gleicher Aufruf) | Container entfernt; Volume `nc_app_gameworld_data` nur mit "Daten löschen" bzw. `--rm-data`; Deploy-Optionen und ExApp-Konfiguration gelöscht |
| Host-Neustart | nichts | Docker stoppt/startet; Welten ohne Restart-Policy, Boot-Abgleich startet Soll-laufende |

- Folge: Aus Sicht der ExApp sind Deaktivieren, Update und Deinstallieren nicht unterscheidbar.
- Heute: `enabled_handler(False)` meldet nur Menü und Talk-Bot ab; die Welten laufen nach einer Deinstallation weiter, mit offenem UDP-Port, eingefrorener Zugangs- und Regeldatei, ohne Pause und ohne Abgleich. Kinder ohne Regeln könnten unbegrenzt weiterspielen; das widerspricht dem Produktkern. [H, eigener Code]
- Nach Deinstallation ohne "Daten löschen" bleibt die SQLite im Volume; eine Neuinstallation übernimmt die Welten wieder (gleiche instance_id). Spielpasswörter ändern sich trotzdem, weil das Geheimnis in der ExApp-Konfiguration liegt und mit der Registrierung gelöscht wird (bereits in install.md beschrieben). [H für Volume, M für appconfig_ex-Löschung]
- Mit "Daten löschen" sind instance_id und DB weg; alte Welt-Container (Label `gameworld.instance=<alt>`) und Volumes (`gameworld-<alt>-<welt>`, ohne Label) sind dann echte Orphans. [H, spec.py]

### 6.2 Optionen für D-15

| | A: Aufräumen bei jedem Deaktivieren (empfohlen, Owner-Entscheid) | B: Aufräumen nur auf Knopfdruck vor der Deinstallation |
|---|---|---|
| Umsetzung | `enabled_handler(False)`: alle eigenen Welt-Container parallel stoppen (kurzer Timeout) und entfernen, Volumes behalten, Soll-Zustand (`desired running`) NICHT ändern. Boot-Abgleich erzeugt fehlende Container aus dem Volume (gebaut in 02-06) | Admin-Abschnitt "Gameworld entfernen vorbereiten" (stoppt und entfernt Container); Listing und Doku sagen "vor dem Deinstallieren drücken" |
| Deinstallation | automatisch sauber | nur sauber, wenn jemand den Knopf kennt |
| Update | Kinder werden kurz getrennt (Stopp, neuer Container, Boot-Abgleich), Welten kommen von selbst wieder | Welten laufen durch (PLATT-02 wie abgenommen) |
| Deaktivieren | keine unverwalteten Spielserver | Welten laufen unverwaltet weiter |
| Risiko | 60-s-Timeout von AppAPI: bei vielen Welten parallel stoppen; Fehler loggen, nie Fehlertext zurückgeben, der das Deaktivieren blockiert | Sicherheitslücke nach stiller Deinstallation |

- Empfehlung A, weil D-15 so gemeint ist und Kindersicherheit vorgeht; Updates sind selten und vom Admin ausgelöst. PLATT-02 ("überleben Updates") bleibt im Sinn erfüllt (Daten und Soll-Zustand bleiben, Welten starten von selbst), aber das Verhalten ändert sich sichtbar. Doku und install.md Abschnitt 7 anpassen. [M]
- Beim Stoppen vorher kurz `@halt` setzen ist nicht nötig; Luanti trennt mit "Server shutting down." (aus 05-09 bekannt, kein Produktfehler). [H]

### 6.3 Orphan-Kommando (Kriterium 3, Claude's Discretion)

Empfohlen ist ein zweistufiges Muster:

1. **In-App (solange installiert):** NC-Admin-Abschnitt "Reste früherer Installationen": listet Container mit `gameworld.managed=true` und fremder `gameworld.instance` sowie Volumes mit Namen `gameworld-*`, die keiner eigenen Welt gehören (Proxy erlaubt `GET /containers/json` mit Label-Filter und `GET /volumes`, beides mit den vorhandenen Flags). Je Eintrag "Entfernen" mit Bestätigung; Volume-Löschen = Spielstand weg, eigener Klartext-Dialog. Nie Container ohne `gameworld.managed` anfassen. [H für Proxy-Rechte, M für Design]
2. **Nach Deinstallation (ExApp weg):** POSIX-Skript `scripts/gameworld-orphans.sh` (in Repo und Doku), läuft auf dem Docker-Host: Standard nur auflisten (`docker ps -a --filter label=gameworld.managed=true`, `docker volume ls --filter name=gameworld-`), mit `--remove-containers` entfernen, mit `--remove-volumes` zusätzlich Volumes (zweite Rückfrage). Das ist das eigentliche "Kommando". [M]

- Ein ExApp-occ-Befehl (nc_py_api `AsyncOccCommandsAPI.register`, AppAPI leitet an eine ExApp-Route weiter) wäre möglich, hilft aber nach der Deinstallation nicht und braucht eine eigene, abgesicherte Route. Nicht empfohlen für v1. [H für Existenz der API, M für Bewertung]

## 7. Setup-Check (Kriterium 2)

- Heutiger Check deckt Proxy fehlt, Flags falsch, zu offen, Engine zu alt ab. Für die Store-Installation fehlen [M, Ableitung aus HaRP/AIO-Netzlage]:
  - **Name nicht auflösbar** (`gameworld-docker-proxy` unbekannt): typischer Fall, wenn der Deploy-Daemon im Netz `bridge` oder `host` arbeitet oder der Proxy in einem anderen Netz hängt. Eigene Meldung: "Gameworld findet den Dienst gameworld-docker-proxy nicht. Er muss im selben Docker-Netz laufen wie Gameworld (das Netz des Deploy-Daemons, bei AIO nextcloud-aio)." Unterscheiden über die Ausnahme (`socket.gaierror`/NameResolutionError in der requests-Kette) statt nur `type(exc).__name__`.
  - **Verbindung abgelehnt** (Dienst läuft nicht) und **Zeitüberschreitung** (falsches Netz/Firewall) getrennt melden.
  - Verweise `siehe docs/install.md` durch eine feste URL ersetzen (Store-Nutzer haben das Repo nicht): `https://github.com/street1983nk/nextcloud-gameworld/blob/master/docs/install.md#...`.
  - Optional Warnung, wenn `GAMEWORLD_DOCKER_URL` auf einen Unix-Socket oder Port 2375 auf öffentlicher Adresse zeigt.
- HaRP-Netzlage [H, HaRP-README]: Daemon-Option `--net` (Standard `host`); Vorlage "HaRP Proxy (Host)" nutzt Host-Netz, dann ist der Proxy nur über `127.0.0.1:<port>` erreichbar und jeder Prozess auf dem Host könnte ihn nutzen. Doku: empfohlen ist ein eigenes Compose-Netz für HaRP-Daemon, ExApps und Proxy; Host-Netz nur mit Loopback-Bindung und klarer Warnung.
- AIO [H, AIO-README und stable35]: Netz `nextcloud-aio`; Fremdcontainer in dieses Netz zu hängen ist bei AIO üblich (Beispiele LDAP, pgAdmin). Compose-Snippet mit `networks: nextcloud-aio: external: true`. Restrisiko: jeder Container in `nextcloud-aio` (auch Nextcloud selbst) erreicht dann den Proxy. Ehrlich in privacy.md und im Listing.
- Optional NC 35: ExApp-Setup-Checks in der NC-Admin-Übersicht (F-12). Nicht für 32 bis 34 verfügbar, darum nicht als Hauptweg.

## 8. Talk-Raum-Übernahme (D-16, Kriterium 7)

- Talk-API kann nicht zum Owner befördern, Moderatoren können den Owner weder entfernen noch herabstufen; Raum löschen, Teilnehmer ändern, nur lesen setzen dürfen Moderatoren. [H, F-09]
- Gameworld braucht den Talk-Owner nicht: alle genutzten Aufrufe (participants, add, remove, promote, demote, read-only, delete) gehen als Moderator. `talk_rooms.owner_uid` ist das handelnde Konto der ersten Wahl (`_candidates`). [H, talk/service.py]
- **Übernahme = DB-Wechsel plus Moderator:** Reconciler prüft je Raum: `owner_uid` nicht in bestätigten Verwaltern ODER in NC gelöscht → neuer Besitzer = dienstältester bestätigter Verwalter, der den Raum sieht (participants gelingt) und Moderator ist bzw. gerade befördert wurde; dann `owner_uid` umschreiben. [M]
- **"Dienstältest" braucht Daten:** Heute ist der Schnappschuss eine sortierte Liste ohne Zeitpunkt. Schema 8: Tabelle `verwalter_seen (uid TEXT PRIMARY KEY, first_seen TEXT NOT NULL)`, befüllt bei jeder bestätigten Schnappschuss-Änderung, Zeilen entfernt beim Verlassen. Gleichstand: Konto-ID sortiert. [M]
- **Sperrfall:** Wird der einzige Moderator gelöscht, bleiben nur Kinder (Typ 3) im Raum; kein Verwalter kann mehr hinein (participants 404, hinzufügen braucht Moderator). Dann nur: Raumzeile vergessen, neuen Raum anlegen, alten Raum als "verwaist" loggen; er lässt sich ohne Moderator auch nicht löschen (nur per `occ talk:room:delete` durch den Server-Admin). In der UI ehrlich melden: "Der alte Raum gehört niemandem mehr. Ein Nextcloud-Admin kann ihn mit occ talk:room:delete <token> löschen." [H für Talk-Regeln, M für Ablauf]
- **Ex-Verwalter existiert noch:** bleibt Talk-Owner und liest mit; Gameworld kann ihn nicht entfernen. Optionen: (a) Hinweis wie heute (`owner_not_admin`, D-27) plus Knopf "Raum neu anlegen" (alter Raum samt Verlauf gelöscht, neuer Raum ohne den Ex-Verwalter), (b) automatisch neu anlegen. Owner-Entscheid (Offene Frage 3). [H]
- Vorbeugung: Der Abgleich hält schon alle Verwalter als Moderatoren; mit ROLLE-03 gibt es mehr Verwalter, der Sperrfall wird seltener.

## 9. Testaufbau AIO und Standard-Compose (R-02)

- **Dev-Compose um HaRP erweitern (Standard-Compose-Test):** Service `appapi-harp` (`ghcr.io/nextcloud/nextcloud-appapi-harp:release`, besser per Digest), `HP_SHARED_KEY`, `NC_INSTANCE_URL=http://app`, Docker-Socket, eigenes Compose-Netz; `gameworld-docker-proxy` ohne Host-Port im selben Netz. Daemon registrieren:
  `occ app_api:daemon:register harp_dev "HaRP Dev" docker-install http appapi-harp:8780 http://app --net gameworld-dev_default --harp --harp_frp_address appapi-harp:8782 --harp_shared_key <key>`
  (Form aus der Usage von `RegisterDaemon.php`). Die Nextcloud braucht eine `/exapps/`-Weiterleitung an HaRP (Apache-Container: `ProxyPass /exapps/ http://appapi-harp:8780/exapps/` oder ein kleiner nginx davor, Muster Dev-Front 8092 aus 04.2-08). [H für occ, M für Proxy-Snippet]
- **Achtung Windows-Docker-Desktop:** HaRP-README nennt `/run/desktop/mnt/host` für Bind-Mounts; Gameworld braucht keine Bind-Mounts, nur das Volume, also unkritisch. [H]
- **AIO-Test:** AIO braucht eine echte Domain mit TLS; lokal nur mit `SKIP_DOMAIN_VALIDATION=true` plus Reverse-Proxy-Modus und Hosts-Eintrag, aufwendig. Empfehlung: AIO-Test auf einer kurzlebigen VM (4 GB, ein Abend) oder auf einem Owner-Testserver, nie auf den InfraNode-Produktivboxen. AIO-Oberfläche: optionalen Container "HaRP" einschalten, dann legt AppAPI `harp_aio` automatisch an; Gameworld per `--info-xml` (Abschnitt 5.2) oder Store installieren; Proxy per Compose in `nextcloud-aio`. [M, AIO-Readme und Forenbericht; L für lokalen Aufwand]
- **RAM:** Docker-VM 6,2 GB gesamt (F-11). AIO plus Gameworld plus eine Welt grob 2,5 bis 3 GB [L, Schätzung]; Dev-Stack vorher stoppen, seriell testen (Owner-Regel).
- **Abnahmeskript `acceptance-phase6.sh`** nach Muster phase5: Image-Pull-Install, Setup-Check grün, Welt anlegen und joinen (luanti_probe), Lehrer-Konto (Gruppe lehrkraefte, Mitglied von "klasse") verwaltet, Negativtests, Erwachsen umschalten mit Wirkung im Mod, Talk-Übernahme nach Löschen des Owner-Kontos, Deaktivieren entfernt Container, Aktivieren erzeugt sie wieder, Orphan-Liste nach `--rm-data`-Neuinstallation, Regressionen Phase 1 bis 5.

## Standard Stack

### Kern (keine neuen Python- oder npm-Pakete)

| Baustein | Version | Zweck | Konfidenz |
|---|---|---|---|
| python:3.13-slim (Debian) | 3.13 | Laufzeit-Basis, wie pyproject | [M] |
| uv | 0.11.x (lokal 0.11.7) | `uv sync --frozen` im Image | [H] |
| frpc (fatedier/frp) | 0.71.1 + SHA-256 | FRP-Tunnel zu HaRP | [H] |
| HaRP start.sh | aus nextcloud/HaRP exapps_dev | Entrypoint | [H] |
| gosu | 1.19 (HaRP-Doku) oder `setpriv` aus util-linux | Rechte abgeben | [M] |
| GitHub Actions docker/* | siehe Abschnitt 4 | Multi-Arch-Build und Push | [H] |
| ghcr.io/nextcloud/nextcloud-appapi-harp | `release` (amd64, arm64) | Dev- und Test-Daemon | [H] |

### Alternativen

| Statt | Möglich | Abwägung |
|---|---|---|
| QEMU-Build | nativer arm64-Runner | schneller, aber zwei Jobs plus Manifest-Merge |
| Host-Skript für Orphans | ExApp-occ-Befehl | wirkt nur, solange die ExApp läuft |
| Eigener Admin-Abschnitt (D-02, gesetzt) | Declarative Settings in NC-Admin | durch D-02 ausgeschlossen |

## Package Legitimacy Audit

Diese Phase installiert keine neuen Python- oder npm-Pakete (pyproject.toml und package.json bleiben). Neu sind nur Build-Bausteine:

| Baustein | Quelle | Herkunft | Prüfung | Disposition |
|---|---|---|---|---|
| docker/setup-qemu-action, setup-buildx-action, login-action, metadata-action, build-push-action | GitHub, Org docker | offiziell | Release und Commit-SHA per `gh api` | Approved |
| actions/checkout, actions/attest-build-provenance | GitHub, Org actions | offiziell | wie oben | Approved |
| frp 0.71.1 | github.com/fatedier/frp Releases | von HaRP und Nextcloud-Skeleton genutzt | Prüfsumme im Dockerfile | Approved |
| HaRP start.sh | github.com/nextcloud/HaRP | offiziell | Inhalt gelesen | Approved (ins Repo kopieren, nicht zur Bauzeit laden) |

slopcheck nicht ausgeführt, weil keine Registry-Pakete hinzukommen.

## Architecture Patterns

### Datenfluss Installation und Betrieb

```
App Store (Metadaten, Release-URL, Signatur)
      |
      v
AppAPI (Nextcloud) --lädt tar.gz von GitHub-Release, prüft Signatur, liest appinfo/info.xml-->
      |
      | docker-install über Deploy-Daemon
      v
HaRP --(Docker-Engine)--> ExApp-Container "gameworld" (Netz des Daemons, Volume nc_app_gameworld_data)
      ^                           |
      | FRP-Tunnel (oder AIO direkt)  | tcp://gameworld-docker-proxy:2375 (gleiches Netz)
Browser /exapps/gameworld/...     v
                          tecnativa-Proxy (CONTAINERS/IMAGES/POST/VOLUMES)
                                  |
                                  v
                          Docker-Engine des Hosts --> Welt-Container (UDP-Port je Welt, Volume gameworld-<inst>-<welt>)
```

### Rollenentscheidung je Anfrage

```
Anfrage /api/...  -> AppAPI/HaRP: USER (angemeldet)  -> AppAPIAuthMiddleware (Signatur, scope.username)
  -> require_verwalter: Selbstauskunft (Cache 30 s) -> groups ∩ verwalter_groups ?
       nein -> 403 | Störung -> 503 | ja -> Route
  -> Einladen: Ziel in Mitglieder(eigene Gruppen ∪ Subadmin-Gruppen)? sonst 403 mit Erklärung
Hintergrund (Takt): acting = bestätigter NC-Admin -> purge, Entfernen-Abgleich
                    acting = bestätigter Verwalter -> Talk-Pflege, Schnappschuss je Gruppe
```

### Anti-Patterns

- **Abgleich als Verwalter mit Entfernen bei 404:** löscht Zugänge aller Gruppen-Eingeladenen, sobald ein Lehrer das Dashboard öffnet (F-04).
- **Lookups im Namen eines Admins, um die Grenze zu umgehen:** verboten durch D-01.
- **Deinstallations-Logik, die Update und Uninstall unterscheiden will:** AppAPI liefert dafür kein Signal (F-02).
- **ADMIN-Route stehen lassen und Lehrer per Ausnahme durchlassen:** AppAPI hat keine Gruppen-Stufe; nur USER plus Python-Sperre funktioniert.
- **Image ohne Prüfsummen** für frpc oder Spiele.

## Don't Hand-Roll

| Problem | Nicht bauen | Stattdessen | Warum |
|---|---|---|---|
| FRP-Konfiguration | eigenes Tunnel-Skript | HaRP `start.sh` unverändert | HaRP-Updates ändern die Konfig, das Skript folgt |
| Unix-Socket-Bindung | eigene uvicorn-Argumente | `nc_py_api.ex_app.run_app` | wählt Socket oder TCP anhand `HP_SHARED_KEY` |
| Multi-Arch-Manifeste | `docker manifest` von Hand | `docker/build-push-action` mit `platforms` | Attestations, Cache, Index in einem Schritt |
| Release-Signatur | eigenes Krypto | `openssl dgst -sha512 -sign ... | openssl base64` | vom Store und von AppAPI genau so geprüft |
| Owner-Wechsel in Talk | Owner-Hack über DB | Moderator plus Gameworld-owner_uid | Talk-API erlaubt keinen Owner-Wechsel |
| Rollen aus NC | eigene Rollentabelle | Selbstauskunft groups/subadmin | ROLLE-02 |

## Runtime State Inventory

Die Phase ändert Rollen- und Lebenszyklus-Verhalten auf bestehenden Installationen (Dev-Stack, Owner-Testwelten).

| Kategorie | Gefunden | Aktion |
|---|---|---|
| Gespeicherte Daten | SQLite Schema 7 im Dev-Storage `.dev/storage`; meta `time_admins` als Liste ohne Zeitpunkt; talk_rooms.owner_uid | Migration 8 (adults, verwalter_seen, verwalter_groups), Schnappschuss-Umzug; keine Datenmigration der Welten |
| Live-Service-Konfig | Dev-Nextcloud: ExApp unter Daemon `manual_install` registriert mit Routen aus info.xml (ADMIN) | Nach Routenänderung neu registrieren (register-exapp.sh tut das ohnehin) |
| OS-registrierter Zustand | keiner gefunden (kein Task Scheduler, kein pm2) | keine |
| Secrets/Env | `HP_SHARED_KEY` neu für Dev-HaRP; PlayerSecret in appconfig_ex der ExApp (geht bei Neuregistrierung verloren, bekannt) | Dev-Key in `.dev/` (gitignored), nie ins Repo |
| Build-Artefakte | `js/gameworld-main.js` lokal gebaut, nicht im Git; Image existiert nicht | Image-Build erzeugt Bundle selbst |

## Common Pitfalls

### P-01: Lehrer-Dashboard leert Gruppen-Einladungen
**Was passiert:** `sync_all` beim Dashboard-Abruf eines Mitglied-Verwalters ruft `user()` je Gruppenmitglied, bekommt 404, entfernt alle. **Vermeiden:** Regel "404 = gelöscht nur als NC-Admin" (1.4), Negativtest mit Fake-Directory. **Warnzeichen:** `effective` leer bei nicht leerer Gruppenliste.

### P-02: ADMIN-Route vergessen
**Was passiert:** Lehrer bekommt 404 auf jede Verwaltungsroute, sieht leeres Dashboard. **Vermeiden:** info.xml-Test und Strukturtest (1.2).

### P-03: Schnappschuss-Abfrage als Lehrer auf Gruppe admin
**Was passiert:** 403, `DirectoryRejectedError`; mit heutiger Logik kann ein Hintergrundlauf den Schnappschuss leeren ("Kein Konto ist noch Admin"), wenn nur Lehrer als Kandidaten bleiben. **Vermeiden:** Bestätigung je Gruppe, Leeren nur je Gruppe.

### P-04: ghcr-Paket privat
**Was passiert:** AppAPI-Pull scheitert, Installation hängt beim Deploy. **Vermeiden:** Sichtbarkeit nach erstem Push auf Public, Checkliste im Release-Plan; anonymer Manifest-Abruf (`curl` mit ghcr-Token ohne Login) als Prüfschritt.

### P-05: max-version zu niedrig
**Was passiert:** NC-35-Instanzen sehen die App nicht oder nur mit "nicht kompatibel". **Vermeiden:** `max-version="35"`, Test auf 35.

### P-06: Proxy im falschen Netz
**Was passiert:** Setup-Check meldet nur "nicht erreichbar". **Vermeiden:** eigene Meldung für Namensauflösung (Abschnitt 7), Doku mit AIO- und Compose-Snippet.

### P-07: Disable-Handler überzieht 60 s
**Was passiert:** AppAPI wertet Timeout als Fehler, stoppt den Container trotzdem, Welten halb gestoppt. **Vermeiden:** parallel stoppen mit kurzem Timeout, Fehler nur loggen, leere Antwort zurück; Boot-Abgleich räumt den Rest auf.

### P-08: Erwachsen-Flag überlebt gelöschtes Konto
**Vermeiden:** `adults` in `ACCOUNT_TABLES`, Test mit `forget_account`.

### P-09: Speicher-Volume gehört root
**Was passiert:** Dienstnutzer kann SQLite nicht anlegen; `load_settings` meldet "APP_PERSISTENT_STORAGE ist nicht nutzbar". **Vermeiden:** chown im Entrypoint vor gosu, oder bewusst als root laufen (Skeleton tut das) und das im Security-Review begründen.

### P-10: Release-Asset gelöscht oder Tag verschoben
**Was passiert:** Neue Installationen scheitern (AppAPI lädt das Archiv bei jeder Installation). **Vermeiden:** Assets nie ersetzen; neue Version statt Re-Upload.

### P-11: Listing verspricht mehr als die App kann
**Vermeiden:** "Interface: German" (F-10), LAN-first/kein Internetzugang ohne VPN, Docker-Proxy root-gleich, Restrisiko gleiches Netz.

## Code-Beispiele

### Einladungs-Umfang eines Verwalters (Skizze)

```python
# Quelle: Ableitung aus provisioning_api stable32 (getGroupUsers erlaubt Mitglieder und Subadmins)
async def invite_scope(profile: Profile, directory: Directory) -> dict[str, set[str]]:
    """Gruppe -> Mitglieder, die dieser Verwalter laut Nextcloud sehen darf."""
    scope: dict[str, set[str]] = {}
    for gid in sorted(set(profile.groups) | set(profile.subadmin)):
        members = await directory.group_members(profile.user_id, gid)  # 403/Störung -> Ausnahme, nie leer
        scope[gid] = set(members or ())
    return scope
```

### Dockerfile-Kern (Skizze)

```dockerfile
# Quelle: nextcloud/app-skeleton-python Dockerfile, HaRP-Doku ExAppHarpIntegration
ARG FRP_VERSION=0.71.1
ARG FRP_AMD64_SHA256=1d9875210972a5d1a62b2dc4c48df45ab0af05d3ca1b5e494a014428259df803
ARG FRP_ARM64_SHA256=8edf590b0c396fa42f9c147121a76af83cfc2002b08f5aef0ea1008c43482019
# ... frpc laden, Prüfsumme vergleichen, nach /usr/local/bin/frpc
COPY --chmod=755 scripts/image/start.sh /start.sh
WORKDIR /app
ENTRYPOINT ["/start.sh", "/app/.venv/bin/python", "-m", "gameworld.main"]
HEALTHCHECK --interval=2s --timeout=2s --retries=300 CMD /healthcheck.sh
```

### Release signieren und hochladen (Owner, nach Zertifikat)

```bash
# Quelle: appstore docs/developer.rst, docs/api/restapi.rst
tar -czf gameworld-1.0.0.tar.gz gameworld/        # gameworld/appinfo/info.xml, img/, LICENSE
SIG=$(openssl dgst -sha512 -sign ~/.nextcloud/certificates/gameworld.key gameworld-1.0.0.tar.gz | openssl base64 -A)
curl -X POST https://apps.nextcloud.com/api/v1/apps/releases \
  -H "Authorization: Token $APPSTORE_TOKEN" -H "Content-Type: application/json" \
  -d "{\"download\":\"https://github.com/street1983nk/nextcloud-gameworld/releases/download/v1.0.0/gameworld-1.0.0.tar.gz\",\"signature\":\"$SIG\",\"nightly\":false}"
# erwartet: HTTP 201
```

## State of the Art

| Alt | Aktuell | Seit | Wirkung |
|---|---|---|---|
| Docker Socket Proxy als AppAPI-Daemon | HaRP | AppAPI 34 deprecated, Entfernung für NC 35 angekündigt (stable35 enthält ihn noch als deprecated) | Nur HaRP testen und dokumentieren |
| AIO "Docker Socket Proxy"-Container | AIO "HaRP"-Container, Daemon `harp_aio` | AppAPI 34 | AIO-Doku auf HaRP schreiben |
| frpc 0.61.1 (HaRP exapps_dev) | 0.71.1 (HaRP-Dockerfile, Skeleton) | 2026 | 0.71.1 nehmen |
| Keine ExApp-Setup-Checks in NC | `ExAppSetupCheckService` | NC 35 | optional |

## Assumptions Log

| # | Annahme | Abschnitt | Risiko falls falsch |
|---|---|---|---|
| A1 | Disable-Handler kann 20 Welten in unter 60 s stoppen und entfernen (parallel) | 6.2 | Halb gestoppte Welten; Boot-Abgleich fängt es auf |
| A2 | AppAPI löscht appconfig_ex der ExApp bei Unregister (Passwortwechsel nach Neuinstallation) | 6.1 | Doku-Aussage leicht falsch, kein Sicherheitsproblem |
| A3 | Autocomplete-API liefert Mitglied-Verwaltern Anzeigenamen gemäß Teilen-Einstellungen | 1.4 | Dann Konto-ID statt Name (Rückfall vorhanden) |
| A4 | Image unter 400 MB komprimiert | 4 | nur Pull-Dauer |
| A5 | AIO plus Gameworld plus Welt braucht 2,5 bis 3 GB | 9 | Test lokal nicht machbar, VM nötig |
| A6 | Talk erlaubt einem Moderator, beliebige Konten der Instanz hinzuzufügen (keine Teilen-Einschränkung) | 8 | Lehrer könnten Kinder nicht in Räume holen, Abgleich als NC-Admin nötig |
| A7 | Dienstnutzer im Image braucht chown auf das Speicher-Volume | 3.2 | Start scheitert sichtbar im Setup-Check |
| A8 | Die Mitgliederliste einer Gruppe enthält auch deaktivierte Konten | 1.4 | Deaktivierte Konten behalten Zugang bis zum NC-Admin-Abgleich |

## Open Questions (RESOLVED)

1. **D-15 und Updates (wichtigster Punkt):** Option A (Container bei jedem Deaktivieren stoppen und entfernen; bei Updates kurze Trennung, Welten kommen von selbst wieder) oder B (Knopf vor Deinstallation, Welten laufen Updates durch)? Empfehlung A. RESOLVED: D-17
2. **NC-Versionsfenster:** min-version 32 lassen (EOL, aber installierbar) oder auf 33 heben? max-version 35 ist Pflicht. Empfehlung: min 32 lassen, getestet wird auf 34 und 35. RESOLVED: D-18
3. **Ex-Verwalter bleibt Talk-Owner:** nur Hinweis plus Knopf "Raum neu anlegen" (Verlauf weg) oder automatisch neu anlegen? Empfehlung: Knopf, weil Verlust des Verlaufs eine bewusste Entscheidung sein soll. RESOLVED: D-19
4. **AIO-Testort:** kurzlebige VM (Kosten wenige Euro) oder vorhandener Testserver des Owners? Lokal ist AIO wegen Domain/TLS und 6,2 GB VM-RAM unpraktisch. RESOLVED: D-20
5. **AR-23 (Pending Todo aus 03-SECURITY.md, Owner 20.10.: in Phase 6 mitnehmen):** Zugangsdatei und worldmods liegen im Luanti-schreibbaren Weltordner. Idee: Weltordner root-eigen mit Sticky-Bit und Gruppenschreibrecht für Luanti (root:30000, 1775), worldmods root-eigen 0755; Luanti kann eigene Dateien anlegen und umbenennen, aber fremde (root) weder löschen noch umbenennen. Ungeprüft [L]; braucht einen Spike mit echter Welt (Luanti schreibt map.sqlite, env_meta.txt per Umbenennen eigener Temp-Dateien). Als eigener kleiner Plan mit Spike oder bewusst auf nach 1.0 verschieben? RESOLVED: D-21
6. **Root oder Dienstnutzer im ExApp-Container:** Skeleton läuft als root; HaRP-Doku empfiehlt gosu. Empfehlung Dienstnutzer (Kindersicherheit, Security-Review), mit chown im Entrypoint. RESOLVED: D-22 (Owner 24.10.: USER 10001 fest, siehe W1)
7. **Spike-Routen im Store-info.xml:** `^/play/.*` und `^/api/my/play-ticket$` bleiben (antworten 404) oder für 1.0 entfernen? Empfehlung: bleiben, weil die Bauphase sie wieder braucht und ein Update keine Routen-Migration kennt; Test belegt 404. RESOLVED: D-23

## Environment Availability

| Abhängigkeit | Gebraucht für | Vorhanden | Version | Rückfall |
|---|---|---|---|---|
| Docker Desktop | Dev-HaRP, Image-Build lokal | ja | 29.5.2, VM 6,2 GB, 12 CPU | CI baut das Image |
| gh CLI | Workflow, Release, Paket-Sichtbarkeit | ja | angemeldet, Repo public | Web-UI |
| uv | Image-Stufe, Gates | ja | 0.11.7 | |
| Node | Frontend-Build | ja | 22.21.0 | |
| Python | Gates, Tests | ja | 3.13.1 | |
| openssl | Release-Signatur | in Git Bash üblich [L] | | im CI-Runner |
| App-Store-Zertifikat | Store-Upload | nein, PR #1364 offen | | Registry-Test per `--info-xml` (5.2) |
| AIO-Umgebung | R-02 | nein | | VM (Offene Frage 4) |

**Blockiert ohne Rückfall:** nur der echte Store-Upload (Zertifikat), wie in R-01 vorgesehen.

## Security Domain

| ASVS | Gilt | Kontrolle |
|---|---|---|
| V2 Authentifizierung | ja (geerbt) | AppAPIAuthMiddleware, Signatur; HaRP-Shared-Key nie im Repo |
| V4 Zugriffskontrolle | ja, Kern der Phase | `require_verwalter` als einzige Sperre nach Routenwechsel; `require_nc_admin` ohne Cache für Verwalter-Gruppen und Orphan-Löschen; Einladungs-Umfang nach NC-Sichtbarkeit; Strukturtest aller Routen |
| V5 Eingaben | ja | Gruppen-IDs (Länge, existiert), nc_user im Erwachsen-Schalter nur für bekannte Spielerzeilen, Orphan-Löschen nur für Namen mit `gameworld-`-Präfix bzw. Label |
| V6 Kryptografie | ja | Release-Signatur nur per openssl, privater Schlüssel nie im Repo/CI-Log (Owner signiert lokal oder Secret) |
| V10 Lieferkette | ja | Actions per SHA, frpc per SHA-256, Spiele per SHA256SUMS, Luanti per Digest, HaRP-start.sh als Kopie im Repo |
| V14 Konfiguration | ja | Proxy-Flags, kein Host-Port, Netz-Restrisiko dokumentiert |

| Bedrohung | STRIDE | Gegenmaßnahme |
|---|---|---|
| Kind ruft Verwaltungsroute nach Wegfall der AppAPI-ADMIN-Stufe | Elevation | require_verwalter auf jedem Router, Strukturtest, Negativtest je Route |
| Lehrer erweitert eigene Rechte (Verwalter-Gruppen setzen) | Elevation | require_nc_admin serverseitig, nie nur UI |
| Lehrer entfernt Zugänge durch 404-Abgleich | Tampering/DoS | Entfernen nur als bestätigter NC-Admin |
| Kind markiert sich als erwachsen | Elevation | Route nur im Verwalter-Router, kein USER-Pfad schreibt |
| Ex-Verwalter liest Talk-Raum weiter | Information Disclosure | Hinweis plus Neuanlage (Offene Frage 3) |
| Andere ExApp/Container im selben Netz nutzt den Proxy | Elevation | ehrlich dokumentiert, eigenes Netz empfohlen; ungelöst in v1 |
| Manipuliertes Image/Archiv | Tampering | Store- und AppAPI-Signaturprüfung, ghcr nur per CI |
| Unverwaltete Welten nach Deinstallation | Elevation (Kinderschutz) | Option A in 6.2 |

## Vorschlag Planschnitt (für den Planer, nicht bindend)

1. Rollen-Kern: Verwalter-Gruppen, Routen USER, Strukturtest, Schnappschuss je Gruppe, NC-Admin-Gating für purge/Entfernen, Einladungs-Umfang, Negativtests (Wave 1, höchste Sorgfalt)
2. Erwachsen-Schalter: Schema 8 (adults), Engine, API, UI (Einladen-Dialog, Spielerliste, Bestätigungsdialog), Negativtests (Wave 1, unabhängig von 1 bis auf Migration)
3. Talk-Übernahme: verwalter_seen, Reconciler-Prüfung, Sperrfall-Hinweis (Wave 2, nach 1)
4. Image und CI: Dockerfile, start.sh, healthcheck, image.yml, Multi-Arch, Lockstep-Prüfung, 1.0.0 (Wave 1, unabhängig)
5. Lebenszyklus: Disable-Aufräumen (nach Owner-Entscheid), Orphan-Liste in der App, Orphan-Skript, Setup-Check-Texte mit URLs (Wave 2)
6. Doku und Listing: info.xml EN/DE/FR, privacy.md/privacy.de.md, install.md EN + install.de.md, README, Screenshots per Playwright gemeinsam (Wave 3, Owner-Abnahme der Texte)
7. Abnahme: Dev-HaRP-Compose, acceptance-phase6.sh, Registry-Install auf Compose und AIO (Wave 3, seriell, RAM)
8. Store-Upload: Zertifikat holen, App registrieren, Release signieren und hochladen, 2x HTTP 201 (letzter Plan, nicht autonom, R-01)

UI-Arbeit (Admin-Abschnitt, Erwachsen-Schalter, Orphan-Liste, Lehrer-Hinweise) spricht für einen UI-SPEC-Schritt (config `ui_phase: true`).

## Sources

### Primär (HIGH)
- nextcloud/app_api main, stable32, stable35 (geklont 24.10.2026): `lib/Controller/ExAppsPageController.php` (uninstallApp), `lib/Command/ExApp/Update.php`, `lib/Command/ExApp/Unregister.php`, `lib/Service/AppAPIService.php` (disableExApp, getExAppUrl), `lib/Controller/ExAppProxyController.php` (ADMIN = isAdmin), `lib/DeployActions/DockerActions.php` (Envs, HaRP-Direktmodus, Volume), `lib/DeployActions/AIODockerActions.php`, `lib/Service/HarpService.php`, `lib/Fetcher/ExAppArchiveFetcher.php`, `lib/Command/Daemon/RegisterDaemon.php`, `lib/Command/ExApp/Register.php`, `lib/Service/ExAppSetupCheckService.php`
- https://raw.githubusercontent.com/nextcloud/HaRP/main/README.md , `exapps_dev/start.sh`, `Dockerfile` (frp 0.71.1)
- https://docs.nextcloud.com/server/latest/developer_manual/exapp_development/development_overview/ExAppHarpIntegration.html
- https://docs.nextcloud.com/server/latest/developer_manual/exapp_development/tech_details/Deployment.html
- https://docs.nextcloud.com/server/stable/admin_manual/exapps_management/AdvancedDeployOptions.html
- nextcloud/appstore: `nextcloudappstore/api/v1/release/info.xsd`, `pre-info.xslt`, `docs/developer.rst`, `docs/api/restapi.rst`
- https://nextcloudappstore.readthedocs.io/en/latest/developer.html
- nextcloud/server stable32 und stable35 provisioning_api: `appinfo/routes.php`, `UsersController.php`, `GroupsController.php`, `AUserDataOCSController.php`
- nextcloud/spreed main: `docs/participant.md`, `docs/conversation.md`, `lib/Listener/UserDeletedListener.php`, `lib/Manager.php`
- nextcloud/app-skeleton-python: `Dockerfile`, `healthcheck.sh`, `Makefile`, `.github/workflows/appstore-build-publish.yml`, `publish-docker-cpu.yml`
- https://api.github.com/repos/nextcloud/server/releases , https://github.com/nextcloud/server/wiki/Maintenance-and-Release-Schedule
- ghcr.io Manifeste `luanti-org/luanti:5.17.0` (Index-Digest = Gameworld-Pin), `nextcloud/nextcloud-appapi-harp:release`
- https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility
- nc_py_api 0.30.3 (lokal): `ex_app/uvicorn_fastapi.py`, `ex_app/occ_commands.py`, `users.py`, `users_groups.py`
- Eigener Code: access/roles.py, access/directory.py, access/service.py, playtime/engine.py, playtime/service.py, provisioner/time_mod.py, provisioner/spec.py, provisioner/setup_check.py, talk/service.py, talk/rooms.py, notify/loop.py, worlds/store.py, lifecycle.py, main.py, config.py, appinfo/info.xml, scripts/dev/*, tests/test_info_xml.py

### Sekundär (MEDIUM)
- nextcloud/all-in-one readme.md (Netz nextcloud-aio für Fremdcontainer, Windows-Hinweise), Containers-Liste (harp)
- https://help.nextcloud.com/t/harp-on-nextcloud-aio/246172 (harp_aio wird automatisch angelegt, Einzelbericht)

### Tertiär (LOW)
- Schätzungen zu Image-Größe und AIO-RAM; AR-23-Sticky-Bit-Idee

## Metadata

**Konfidenz:**
- Store-/AppAPI-Mechanik: HIGH, Quelltext der relevanten Branches gelesen
- Rollen/OCS: HIGH, Quelltext stable32/35 gelesen
- Talk: HIGH für API-Grenzen, MEDIUM für Übernahme-Ablauf
- Image/CI: MEDIUM, offizielles Skeleton als Vorlage, Gameworld-Details abgeleitet
- AIO-Test: MEDIUM bis LOW (nicht ausprobiert)

**Recherchedatum:** 24.10.2026
**Gültig bis:** etwa 14 Tage für HaRP/AppAPI (aktiv entwickelt, HaRP-README ändert Regeln je Release), 30 Tage für den Rest
