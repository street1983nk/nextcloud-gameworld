# Bundled games

| File | Source | Release | License |
|-------|--------|---------|--------|
| `minetest_game-38214.zip` | ContentDB, Paket `Luanti/minetest_game` (https://content.luanti.org/packages/Luanti/minetest_game/) | 38214 vom 17.08.2026 | Code LGPL-2.1-or-later, Medien CC-BY-SA-3.0 |
| `mineclone2-39534.zip` (VoxeLibre 0.92.4) | ContentDB, Paket `Wuzzy/mineclone2` (https://content.luanti.org/packages/Wuzzy/mineclone2/) | 39534 vom 18.10.2026 | Code GPL-3.0-or-later, Medien CC-BY-SA-4.0 |

- The checksum is in `SHA256SUMS`. Before every use, Gameworld checks it in code against the constant in the preset (`src/gameworld/provisioner/presets.py`, check in `archive.py`) and aborts on a mismatch.
- Gameworld never downloads anything from ContentDB at runtime. There are no external calls, the game comes exclusively from this file.
- The full license texts are in the respective zip under `minetest_game/LICENSE.txt` and `mineclone2/LICENSE.txt`.
- An update is a deliberate decision: add a new file with a new release number, change `SHA256SUMS` and the constant in the code together.

## VoxeLibre (not in Git)

`mineclone2-39534.zip` is about 84 MB and therefore is not in Git (`.gitignore`). Fetch it with `sh scripts/fetch-games.sh`; the script stores the file only if the checksum from `SHA256SUMS` matches, and `scripts/dev/register-exapp.sh` calls it automatically. The checksum is in `SHA256SUMS` and as a constant in the code. An update is a deliberate decision: change the new release number, `SHA256SUMS` and the constant in `src/gameworld/provisioner/presets.py` together.
