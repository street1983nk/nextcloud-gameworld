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
