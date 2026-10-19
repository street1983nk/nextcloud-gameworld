# Mitgelieferte Spiele

| Datei | Quelle | Release | Lizenz |
|-------|--------|---------|--------|
| `minetest_game-38214.zip` | ContentDB, Paket `Luanti/minetest_game` (https://content.luanti.org/packages/Luanti/minetest_game/) | 38214 vom 17.08.2026 | Code LGPL-2.1-or-later, Medien CC-BY-SA-3.0 |

- Die Prüfsumme steht in `SHA256SUMS`. Gameworld prüft sie vor jeder Nutzung im Code (`src/gameworld/provisioner/archive.py`) und bricht bei Abweichung ab.
- Gameworld lädt zur Laufzeit nie etwas von ContentDB nach. Es gibt keine externen Aufrufe, das Spiel kommt ausschließlich aus dieser Datei.
- Die vollständigen Lizenztexte liegen im Zip unter `minetest_game/LICENSE.txt`.
- Ein Update ist eine bewusste Entscheidung: neue Datei mit neuer Release-Nummer ablegen, `SHA256SUMS` und die Konstante im Code gemeinsam ändern.
