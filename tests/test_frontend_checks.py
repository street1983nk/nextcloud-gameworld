"""Runs every frontend check script (frontend/tests/*.check.mjs) as part of pytest.

The scripts are plain Node assertions without a test runner; before this test they only
ran when called by hand, so a broken check could go unnoticed. Skipped without node.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CHECKS = sorted((ROOT / "frontend" / "tests").glob("*.check.mjs"))
NODE = shutil.which("node")


def test_check_scripts_exist() -> None:
    assert len(CHECKS) >= 9, [path.name for path in CHECKS]


@pytest.mark.skipif(NODE is None, reason="node not installed")
@pytest.mark.parametrize("script", CHECKS, ids=[path.name for path in CHECKS])
def test_frontend_check_passes(script: Path) -> None:
    assert NODE is not None
    result = subprocess.run(  # noqa: S603 (fixed node binary, script from the repo)
        [NODE, str(script)], cwd=ROOT, capture_output=True, text=True, timeout=120, check=False
    )
    assert result.returncode == 0, f"{script.name} failed:\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}"


# Static checks of the dialog fixes from the full test 261102 (B1, B3).
COMPONENTS = ROOT / "frontend" / "src" / "components"


def _vue(name: str) -> str:
    return (COMPONENTS / name).read_text(encoding="utf-8")


def test_adult_chip_reads_the_switch_state() -> None:
    """B1: chip and switch read the same state, so they change and jump back together."""
    source = _vue("PlayerManager.vue")
    assert re.search(r'<NcChip\s+v-else-if="adultShown\[player\.nc_user\]"', source)
    assert 'v-else-if="player.adult"' not in source
    assert ':model-value="Boolean(adultShown[player.nc_user])"' in source


@pytest.mark.parametrize("name", ["InviteDialog.vue", "WorldWindowDialog.vue"])
def test_field_dialogs_close_on_escape(name: str) -> None:
    """B3: Escape from a field closes the dialog through its own close path (capture phase)."""
    source = _vue(name)
    assert '@keydown.capture="onKeydown"' in source
    assert "import { escapeShouldClose } from '../dialogKeys.js'" in source
    handler = source[source.index("function onKeydown(event) {") :]
    handler = handler[: handler.index("\n}\n")]
    assert "escapeShouldClose(event)" in handler
    assert "close()" in handler
    # The own close path keeps its lock while saving.
    close = source[source.index("function close() {") :]
    assert "if (!" in close[: close.index("\n}\n")]


def test_player_dialog_returns_focus_after_cancel() -> None:
    """B3: Cancel of New password and Rename puts the focus back on the opening button."""
    source = _vue("PlayerManager.vue")
    assert '@click="cancelRotate(player)"' in source
    assert '@click="cancelRename(player)"' in source
    assert "@click=\"rotating = ''\"" not in source
    assert "@click=\"renaming = ''\"" not in source
    for name, selector in (("cancelRotate", ".players__rotate"), ("cancelRename", ".players__rename-start")):
        body = source[source.index(f"function {name}(player) {{") :]
        body = body[: body.index("\n}\n")]
        assert f"focusRowButton(player.nc_user, '{selector}')" in body
    assert 'class="players__rotate"' in source
    assert 'class="players__rename-start"' in source


def test_player_dialog_closes_on_escape_from_fields() -> None:
    """B3: Escape from a switch or the name field closes the player dialog (capture phase)."""
    source = _vue("PlayerManager.vue")
    assert source.count('@keydown.capture="onKeydown"') == 1
    assert "import { escapeShouldClose } from '../dialogKeys.js'" in source
    handler = source[source.index("function onKeydown(event) {") :]
    handler = handler[: handler.index("\n}\n")]
    assert "escapeShouldClose(event)" in handler
    assert "emit('close')" in handler


def test_adult_confirmation_keeps_its_own_escape() -> None:
    """The nested confirmation closes only itself (NcModal path): the handler sits in the player dialog only."""
    source = _vue("PlayerManager.vue")
    confirmation = source.index("<!-- Confirmation on switching on (D-07)")
    assert source.index('@keydown.capture="onKeydown"') < confirmation
    assert "@keydown" not in source[confirmation : source.index("</template>\n\n<script setup>")]
    assert '@update:open="onConfirmOpen"' in source


def test_world_table_does_not_wait_for_own_worlds() -> None:
    """B2: refresh() shows the world table right after listWorlds; listMyWorlds follows, both behind the seq check."""
    source = (ROOT / "frontend" / "src" / "views" / "ParentView.vue").read_text(encoding="utf-8")
    body = source[source.index("async function refresh() {") :]
    body = body[: body.index("\n}\n")]
    assert body.index("await listWorlds()") < body.index("worlds.value = result") < body.index("await listMyWorlds()")
    assert body.index("loading.value = false") < body.index("await listMyWorlds()")
    assert body.count("seq === refreshSeq") == 3
    assert "myWorlds.value = mine" in body[body.index("await listMyWorlds()") :]
