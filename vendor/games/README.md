# Mitgelieferte Spiele

| Datei | Quelle | Release | Lizenz |
|-------|--------|---------|--------|
| `minetest_game-38214.zip` | ContentDB, Paket `Luanti/minetest_game` (https://content.luanti.org/packages/Luanti/minetest_game/) | 38214 vom 17.08.2026 | Code LGPL-2.1-or-later, Medien CC-BY-SA-3.0 |
| `mineclone2-39534.zip` (VoxeLibre 0.92.4) | ContentDB, Paket `Wuzzy/mineclone2` (https://content.luanti.org/packages/Wuzzy/mineclone2/) | 39534 vom 18.10.2026 | Code GPL-3.0-or-later, Medien CC-BY-SA-4.0 |

- Die Prüfsumme steht in `SHA256SUMS`. Gameworld prüft sie vor jeder Nutzung im Code gegen die Konstante im Preset (`src/gameworld/provisioner/presets.py`, Prüfung in `archive.py`) und bricht bei Abweichung ab.
- Gameworld lädt zur Laufzeit nie etwas von ContentDB nach. Es gibt keine externen Aufrufe, das Spiel kommt ausschließlich aus dieser Datei.
- Die vollständigen Lizenztexte liegen im jeweiligen Zip unter `minetest_game/LICENSE.txt` bzw. `mineclone2/LICENSE.txt`.
- Ein Update ist eine bewusste Entscheidung: neue Datei mit neuer Release-Nummer ablegen, `SHA256SUMS` und die Konstante im Code gemeinsam ändern.

## VoxeLibre (nicht im Git)

`mineclone2-39534.zip` ist rund 84 MB groß und liegt deshalb nicht im Git (`.gitignore`). Abruf mit `sh scripts/fetch-games.sh`; das Skript legt die Datei nur ab, wenn die Prüfsumme aus `SHA256SUMS` stimmt, und `scripts/dev/register-exapp.sh` ruft es automatisch auf. Die Prüfsumme steht in `SHA256SUMS` und als Konstante im Code. Ein Update ist eine bewusste Entscheidung: neue Release-Nummer, `SHA256SUMS` und die Konstante in `src/gameworld/provisioner/presets.py` gemeinsam ändern.
