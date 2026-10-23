# Phase 05: zurückgestellte Punkte

## Aus 05-09 (Abnahmelauf 23.10.2026, 21:10 bis 21:50)

`sh scripts/dev/acceptance-phase5.sh` (mit der Grundlinien-Anpassung der Rest-Container-Prüfung):
Phase 5 selbst 96 von 96 grün (K1 bis K3, Aufräumen). Die Regression scheitert an drei
Prüfungen älterer Abnahmen, die nicht von Phase 5 kommen. Gesamtergebnis 99 von 103, Exit 1.
Phase 1 (84 von 84) und Phase 2 (104 von 104) sind grün.

Nicht behoben (Scope-Grenze, ältere Abnahmen, Owner-Entscheid):

1. **acceptance-phase4_1.sh K2 "Text nennt Fremder1 und eine Uhrzeit"**: Die Prüfung erwartet
   `H:MM Uhr`. Seit da2ad56 (Owner-Entscheid 22.10., "Uhr" nur bei vollen Stunden) heißt der Text
   "Fremder1 wollte um 21:42 beitreten." Die Prüfung ist veraltet. Vorschlag: Regex auf
   `um [0-9]{1,2}:[0-9]{2} beitreten` ändern.
2. **acceptance-phase3.sh K5 "Tabelle players hat genau nc_user, player_name, rotation"**:
   Seit dabe0c0 (22.10., gelöschte Konten vollständig vergessen) hat `players` die Spalte `salt`.
   Die Prüfung ist veraltet. Vorschlag: Erwartung auf `nc_user,player_name,rotation,salt`,
   die Absicht (keine Passwortspalte) bleibt.
3. **acceptance-phase3.sh K3 "genau die Abnahme-Welt in der Liste"**: Die Dev-Instanz hat zwei
   Owner-Welten "Browser Minetest" und "Browser VoxeLibre" (Spike 04.2), in die gw-kind ("Kind")
   eingeladen ist; /my/worlds von gw-kind listet sie mit. Umgebung, kein Produktfehler. Wege:
   Spike-Welten entfernen (Owner) oder die Prüfung auf die Welten vor dem Lauf als Grundlinie
   umstellen (dann auch die `.worlds[0]`-Zugriffe in K3 auf die Abnahme-Welt filtern).

Fremde Welt-Container (nur gemeldet, nicht angefasst):

- `gameworld-788fff30-*` (2): die beiden Spike-Welten der Dev-Instanz, laufen seit etwa 10 Stunden.
- `gameworld-b7b6f1af-*` (2): Testreste einer anderen Instanz (Port 30016), laufen seit etwa 2 Stunden.
  Sie ließen die Prüfung "keine Welt-Container übrig" in Phase 3, 4 und 4.1 scheitern; seit 19ffbc4
  zählt diese Prüfung nur Container, die beim Start des Laufs noch nicht da waren.
