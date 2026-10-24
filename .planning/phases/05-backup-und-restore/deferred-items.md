# Phase 05: zurückgestellte Punkte

## Aus 05-09 (Abnahmelauf 23.10.2026, 21:10 bis 21:50)

`sh scripts/dev/acceptance-phase5.sh` (mit der Grundlinien-Anpassung der Rest-Container-Prüfung):
Phase 5 selbst 96 von 96 grün (K1 bis K3, Aufräumen). Die Regression scheitert an drei
Prüfungen älterer Abnahmen, die nicht von Phase 5 kommen. Gesamtergebnis 99 von 103, Exit 1.
Phase 1 (84 von 84) und Phase 2 (104 von 104) sind grün.

ERLEDIGT am 24.10.2026 (Owner-Entscheid "Prüfungen anpassen", Umsetzung in 05-09):

1. ~~**acceptance-phase4_1.sh K2 "Text nennt Fremder1 und eine Uhrzeit"**~~: Regex auf den
   Text seit da2ad56 umgestellt (`um [0-9]{1,2}:[0-9]{2} beitreten` statt `H:MM Uhr`).
2. ~~**acceptance-phase3.sh K5 "Tabelle players hat genau nc_user, player_name, rotation"**~~:
   Prüfung tolerant gegenüber Zusatzspalten (seit dabe0c0 gibt es `salt`): Pflichtspalten
   nc_user, player_name, rotation müssen da sein, keine Spalte darf "pass" enthalten.
   Die Absicht (keine Passwortspalte) bleibt.
3. ~~**acceptance-phase3.sh K3 "genau die Abnahme-Welt in der Liste"**~~: Grundlinie der
   Kind-Sicht vor dem Lauf (`/my/worlds` von gw-kind), K3 zählt nur neu hinzugekommene Welten;
   alle `.worlds[0]`-Zugriffe filtern jetzt auf die Abnahme-Welt (gleiches Muster wie die
   Container-Grundlinie aus 19ffbc4). Owner-Spike-Welten stören den Lauf nicht mehr.

Fremde Welt-Container (nur gemeldet, nicht angefasst):

- `gameworld-788fff30-*` (2): die beiden Spike-Welten der Dev-Instanz, laufen seit etwa 10 Stunden.
- `gameworld-b7b6f1af-*` (2): Testreste einer anderen Instanz (Port 30016), laufen seit etwa 2 Stunden.
  Sie ließen die Prüfung "keine Welt-Container übrig" in Phase 3, 4 und 4.1 scheitern; seit 19ffbc4
  zählt diese Prüfung nur Container, die beim Start des Laufs noch nicht da waren.

## Aus 05-09 (Gesamtläufe 24.10.2026 früh, nach den Prüfungs-Anpassungen)

Lauf 1 (04:53 bis 05:34): 100 von 103, Exit 1. Phase-5-Teil 96 von 96 grün. Die drei
angepassten Prüfungen sind grün (Phase 1 84/84, Phase 2 104/104, Phase 3 75/75 inklusive
K3-Grundlinie und K5-Spalten; die 4.1-eigenen Prüfungen inklusive K2-Text liefen durch).
Einzige verbliebene Ursache: Die Phase-4-Stabilitätsprüfung zählte 17 AppAPI-Verbindungsfehler
("Backend ungeplant weg"). Zeitlich fallen alle 17 exakt in die geplanten Backend-Neustarts
der Regression (05:06 bis 05:34); Quelle war die noch offene Browser-Sitzung der
Owner-Playwright-Abnahme, deren 5-s-Polling (/api/worlds, /api/pause, /api/talk) in den
Neustart-Lücken cURL error 7 im Nextcloud-Log erzeugte. Umgebung, kein Produktfehler;
die Prüfung selbst bleibt unverändert (sie ist als Wächter gegen echte Abstürze wertvoll).
Daraus folgten die 3 gezählten Fehlschläge (4.1 nicht Exit 0, Erfolgs-Marker 4.1, Marker
"109 von 109").

Lauf 2 (Bestätigungslauf nach Ende der Browser-Sitzung): Phase-5-Teil erneut 96 von 96 grün
inklusive Aufräumen; die Regression wurde von der Claude-Code-Speicherüberwachung beim Start
abgebrochen (Systemspeicher knapp, kein Fehler des Laufs). Gemäß Hinweis nicht neu gestartet.

ERLEDIGT am 24.10.2026 (Lauf 3, 06:10 bis 06:50, nach den Review-Fixes WR-01 bis WR-03):

- ~~**Voller Bestätigungslauf 103/103**~~: `sh scripts/dev/acceptance-phase5.sh` Exit 0,
  "103 von 103 Prüfungen bestanden", Regression komplett grün (4.1: 133/133 inkl. Marker
  84/84, 104/104, 75/75, 109/109). Browser-Sitzung war zu, nichts lief parallel. Der Lauf
  belegt zugleich den neuen Temp+MOVE-Upload-Pfad (WR-03) live am echten Nextcloud.
- ~~Reste des abgebrochenen Laufs 2~~: vom Lauf selbst weggeräumt; geprüft am 24.10.:
  Konto gw-abnahme41 "user not found", keine Abnahme-Container mehr, admin sieht nur noch
  die beiden Spike-Welten.

Offen: nichts mehr aus 05-09. Die Info-Findings IN-01 bis IN-07 stehen in 05-REVIEW.md
(nicht fixpflichtig, Owner-Entscheid war nur WR-01 bis WR-03).
