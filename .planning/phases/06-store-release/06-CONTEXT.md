# Phase 6: Store-Release - Context

**Gathered:** 2026-10-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Jede Familie und jede Schule mit Nextcloud kann Gameworld direkt aus dem Nextcloud App Store installieren, mit ehrlicher Erklärung der Zusatz-Privilegien. Dazu gehören: Store-Installierbarkeit (PLATT-01, AppAPI/HaRP, NC 32+), zusätzliche Verwalter-Gruppen (ROLLE-03), der Erwachsen-Schalter (ROLLE-04), aufräumende Deinstallation samt Orphan-Kommando, ehrliches Listing plus privacy.md und die Übernahme verwaister Talk-Räume. Die 7 Success Criteria stehen in der ROADMAP (Phase 6), drei Owner-Entscheide vom 22.10.2026 sind dort bereits eingearbeitet.

</domain>

<decisions>
## Implementation Decisions

### Verwalter-Gruppen (ROLLE-03)
- **D-01:** Ein Gruppen-Verwalter (Nicht-NC-Admin) lädt nur Konten aus Gruppen ein, in denen er selbst Mitglied oder Subadmin ist. Die App nutzt die Nextcloud-Sichtbarkeitsregeln wie vorgesehen (keine Lookups mit App-Systemrechten, keine Privacy-Umgehung); die Grenze wird in der UI verständlich erklärt. Harte Folge aus dem Research: Kontenabgleich und purge_missing_accounts dürfen NIE im Namen eines Nicht-Admin-Verwalters laufen (404-Falle, sonst würden Konten fälschlich vergessen).
- **D-02:** Die zusätzlichen Verwalter-Gruppen stellt der NC-Admin in einem eigenen Admin-Abschnitt der Gameworld-UI ein; der Abschnitt ist nur für echte NC-Admins sichtbar. Default bleibt die Gruppe admin.
- **D-03:** Alle Verwalter sehen alle Welten (heutiges Familienmodell bleibt; worlds bekommt KEIN owner_uid). Das Besitzer-Modell je Lehrkraft kommt erst im Schul-Meilenstein (v2, siehe SCHULEN.md). Sicherungen bleiben je Verwalter getrennt (D-13 aus Phase 5).
- **D-04:** Globale Einstellungen (Pause für alle, Ferien, Zeitzone, Spieler-Adresse) dürfen alle Verwalter bedienen, nicht nur NC-Admins.

### Erwachsen-Schalter (ROLLE-04)
- **D-05:** "Erwachsen" gilt global je Konto, nicht je Welt-Einladung. Ein Zustand pro Person.
- **D-06:** Der Schalter sitzt im Einladen-Dialog UND in der Spielerliste (nachträglich änderbar). Nur Verwalter können ihn setzen.
- **D-07:** Einschalten verlangt einen Bestätigungsdialog, der die Folgen in Klartext nennt ("<Name> spielt dann ohne Pause, Zeitfenster und Spielzeitregeln"). Ausschalten geht ohne Dialog.
- **D-08:** Das Umschalten wirkt sofort, auch mitten im Spiel (Muster wie der Einladungs-Widerruf): Erwachsen hebt Pause/Zeitfenster/Limits sofort auf, zurück auf Kind greifen die Regeln sofort wieder. Erwachsene erscheinen nicht im Tagesrückblick und bekommen nie Verwaltungs- oder Luanti-Adminrechte.

### Store-Auftritt
- **D-09:** Store-Listing dreisprachig: Englisch, Deutsch, Französisch (wie Findling 1.5.1). Stil: Faktenliste, kein Marketing (bestehende Owner-Regel); Entwurf vor dem Release zur Owner-Abnahme.
- **D-10:** Voller Screenshot-Satz 5-6 Bilder (Weltliste, Einladen, Kinder-Ansicht, Sicherungen, Spielzeit-Dialog, Handy-Ansicht), gemeinsam per Playwright aufgenommen, versionierte Dateinamen (-v1; Spiegel refetcht nie).
- **D-11:** Die Zusatz-Privilegien (Docker-Socket-Proxy, UDP-Ports) bekommen einen eigenen Abschnitt OBEN im Listing ("Was diese App darf und warum") plus ausführliche privacy.md im Repo. Ehrlichkeit als Verkaufsargument (Roadmap-Kriterium 4).
- **D-12:** privacy.md und öffentliche Repo-Doku auf Englisch als Hauptfassung, deutsche Fassung daneben verlinkt (privacy.de.md; Findling-Muster hardening/privacy).

### Release-Mechanik
- **D-13:** Store-Version 1.0.0 (v1 ist nach dieser Phase feature-komplett, 27/27 Requirements).
- **D-14:** ExApp-Image auf ghcr.io am Repo street1983nk/nextcloud-gameworld, Build per GitHub Actions, Tag je Release.
- **D-15:** Deinstallation: Welt-Container werden gestoppt und entfernt, Spielstand-Volumes und Sicherungen in den Files BLEIBEN (kein stiller Datenverlust). Das Orphan-Kommando listet Reste auf und löscht sie gezielt; das Verhalten wird im Listing ehrlich beschrieben.
- **D-16:** Verwaiste Talk-Räume (Besitzer gelöscht oder kein Verwalter mehr) gehen an den dienstältesten bestätigten Verwalter; der Reconciler prüft das regelmäßig. Kein Raum bleibt ohne handlungsfähigen Besitzer (talk_rooms.owner_uid).

- **D-24 (Owner 24.10., nachgereicht):** GitHub-README dreisprachig: README.md auf Englisch als Standard, README.de.md und README.fr.md verlinkt (Sprachverweis oben). Gut strukturiert mit: Badges (CI-Status, Release/Store-Version, Lizenz AGPL-3.0-or-later, Nextcloud-Versionsfenster), Kurzbeschreibung, Funktionsliste, Architektur-Diagramm (Mermaid, von GitHub nativ gerendert: Nextcloud/AppAPI/HaRP, ExApp, docker-socket-proxy, Welt-Container, Sicherungen in Files), Screenshot-Abschnitt (die 6 Store-Screenshots -v1 aus 06-13, bis dahin Platzhalter), Installation, Doku-Links, Lizenz. Ton bleibt Faktenliste (bestehende Owner-Regel), kein Marketing.

### Nachentscheide waehrend der Abnahme (Owner 24.10. abends, BINDEND, Release-Gate)
- **D-25:** ERST UEBERSETZEN, DANN RELEASEN. Die App-Oberflaeche wird vor dem Store-Upload mehrsprachig: Deutsch, Englisch, Franzoesisch. Die UI-Sprache folgt der Nextcloud-Kontosprache des Nutzers. Das Listing-Feld "Interface: German" wird entsprechend ersetzt (German/English/French), README-Screenshots je Sprachfassung passend (EN-README mit englischer UI).
- **D-26:** Quellcode-Kommentare und Docstrings komplett auf ENGLISCH, auch der Bestand (Uebersetzungs-Pass ueber das ganze Repo). Nutzersichtbare Strings sind davon getrennt (i18n).
- **D-29 (Owner 24.10., Nachtrag zu D-26):** Auch Log-Meldungen (LOG.*) werden Englisch; betroffene Log-Tests mit anpassen. Gehoert in den Kommentar-Pass (Welle 13).
- **D-27:** Auch die Texte IM Spiel (Chat-Hinweise, Pausen-/Kick-Texte, Spielzeit-Warnungen der Mods) werden uebersetzt, PRO WELT einstellbar; Standard ist die Sprache des anlegenden Verwalters. Alle Kinder einer Welt sehen dieselben Texte.
- Folge: Die Plaene 06-13 (Screenshots/Abnahme), 06-11-Anteile (Listing-Interface-Zeile) und 06-16 verschieben sich hinter die neuen i18n-Plaene. Die am 24.10. aufgenommenen deutschen Screenshots bleiben fuer die DE-Fassung verwendbar, sofern sich die UI nicht aendert.

- **D-28 (Owner 24.10., Store-Strategie):** info.xml bekommt einen discussion-Link auf einen eigenen Gameworld-Thread im Nextcloud-Forum (Thread-Entwurf vorbereiten, Owner postet/gibt GO vor dem Store-Upload). Die Store-Beschreibung bekommt je Sprache einen Cross-Promo-Satz auf die Schwester-Apps (Findling Search, MCP Connector) im Fakten-Ton. Summaries sind schon dreisprachig (D-09).

### Rahmenbedingungen
- **R-01:** Die Store-Zertifikatsanfrage läuft (nextcloud/app-certificate-requests PR #1364, offen seit 21.10.2026). Owner-Vorgabe: NICHT nachhaken, einfach warten. Der eigentliche Store-Upload (Signieren + Submit) ist der letzte Plan der Phase, NICHT autonom und hängt am gemergten Zertifikat; alle anderen Pläne sind davon unabhängig.
- **R-02:** Test der Store-Installation auf AIO und Standard-Compose (Roadmap-Kriterium 1) gehört in die Phasenabnahme.

### Nachentscheide aus dem Research (Owner 24.10., auf Researcher-Fragen)
- **D-17:** Deinstallation/Updates: Option A. Welt-Container werden bei JEDEM Deaktivieren gestoppt und entfernt (Volumes bleiben), der Boot-Abgleich baut sie neu. Folge bewusst akzeptiert: Bei App-Updates werden spielende Kinder kurz getrennt. Dazu Orphan-Skript auf dem Host plus Liste in der App.
- **D-18:** info.xml: min-version 32 bleibt, max-version 35 (Pflicht); getestet wird auf NC 34 und 35.
- **D-19:** Ex-Verwalter mit existierendem Konto bleibt technisch Talk-Raum-Owner: Hinweis plus Knopf "Raum neu anlegen" (Verlust des Verlaufs ist eine bewusste Entscheidung, kein Automatismus).
- **D-20:** AIO-Test auf einer kurzlebigen Cloud-VM (wenige Euro, Wegwerf-Domain, danach löschen).
- **D-21:** AR-23 (Weltordner-Härtung, offener Punkt aus Phase 3) kommt als eigener kleiner Plan MIT Spike in Phase 6: erst belegen, dass Luanti mit root:30000/1775 und root-eigenem worldmods sauber schreibt, dann härten.
- **D-22:** ExApp-Container läuft fest als USER 10001:10001 (Connector-Muster, kein chown/gosu, kein root-Moment; Entrypoint bricht klar ab, wenn das Volume nicht beschreibbar ist). Owner-Bestätigung 24.10. nach HaRP-Messung.
- **D-23:** Die Browser-Spike-Routen bleiben im Store-info.xml (antworten 404, Feature-Flag aus); ein Test belegt das. AppAPI kennt keine Routen-Migration.

### Claude's Discretion
- Technische Umsetzung des Gruppen-Lookups (OCS-Endpunkte, Caching) und der sofortigen Wirkung des Erwachsen-Schalters.
- Form des Orphan-Kommandos (occ-Subcommand vs. API+UI), solange Roadmap-Kriterium 3 erfüllt ist.
- Setup-Check-Texte und AIO-Testaufbau.
- Kategorie und Schlagworte im Store (naheliegend: Games/Tools).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Rollen und Schulen
- `.planning/research/SCHULEN.md` , Harter Befund zu ROLLE-03 (OCS-Sichtbarkeit: Admins/delegierte Admins/Subadmins/Gruppenmitglieder; Lehrkraft ohne Rechte sieht fremde Konten als 404), Schul-Meilenstein ist v2, Einladungs-Umfang über Mitgliedschaft/Subadmin.
- `.planning/REQUIREMENTS.md` , ROLLE-03, ROLLE-04 (vollständiger Wortlaut mit Owner-Entscheiden 20./22.10.2026), PLATT-01.
- `.planning/ROADMAP.md` §Phase 6 , 7 Success Criteria inkl. 404-Warnung zu purge_missing_accounts (dabe0c0) und talk_rooms.owner_uid.

### Bestehender Code (Integrationspunkte)
- `src/gameworld/access/roles.py` , ADMIN_GROUP="admin" hart codiert; hier setzt ROLLE-03 an.
- `src/gameworld/api/me.py`, `src/gameworld/playtime/engine.py` , Pause/Zeitfenster/Limits; hier setzt der Erwachsen-Schalter an.
- `appinfo/info.xml` , docker-install, Proxy-Beschreibung, Grundlage fürs Store-Paket.
- `docs/install.md` , Eltern-Doku inkl. Abschnitt 11 Sicherungen; Muster für Listing-Tonlage.

### Store-Erfahrung (Findling, aus Memory/Owner-Regeln)
- Faktenliste statt Marketing, Entwurf vor Release zeigen, versionierte Screenshot-Namen, Submit-Muster 2x HTTP 201.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `require_verwalter`-Dependency (routerweit) , Erweiterung um konfigurierte Gruppen statt hart "admin".
- Einladen-Dialog und Spielerliste (ParentView/Spieler-Dialog) , Anbauort für den Erwachsen-Schalter.
- Reconciler (worlds/reconciler.py) , Anbauort für die Talk-Raum-Übernahmeprüfung.
- Abnahmeskript-Muster acceptance-phase5.sh , Vorlage für die Phase-6-Abnahme.

### Established Patterns
- Bestätigungsdialoge mit Klartext-Folgen (Backup/Restore, Phase 5) , gleiches Muster für den Erwachsen-Dialog.
- Schema-Migrationen nummeriert (zuletzt Schema 7) , neue Spalte/Tabelle für Erwachsen-Flag und Verwalter-Gruppen-Konfig.
- Negativtests als Pflicht (Owner-Regel): Kind kann sich nicht selbst freistellen; Nicht-Admin-Verwalter löst nie Kontenabgleich aus.

### Integration Points
- OCS-Konten-/Gruppenabfragen laufen heute im Namen des handelnden Verwalters (nc.py) , ROLLE-03 muss dort die Sichtbarkeitsgrenzen respektieren.
- Zeit-/Pause-Durchsetzung läuft über Zeit-Mod und Engine , Erwachsen-Ausnahme muss beide Wege abdecken.

</code_context>

<specifics>
## Specific Ideas

- Listing-Sprachen ausdrücklich EN+DE+FR (Owner-Antwort in der Discussion, Muster Findling 1.5.1 Namen en/de/fr).
- Zertifikat: warten, nicht nachhaken (Owner 24.10.2026).

</specifics>

<deferred>
## Deferred Ideas

- Besitzer-Modell je Welt (jede Lehrkraft sieht nur eigene Welten) , Schul-Meilenstein v2 (SCHULEN.md, Bedingungen: Store-Release stabil, Pilotpartner, Lasttest 30 Spieler).
- Weitere Listing-Sprachen über EN/DE/FR hinaus , nach Nachfrage.

</deferred>

---

*Phase: 6-Store-Release*
*Context gathered: 2026-10-24*
