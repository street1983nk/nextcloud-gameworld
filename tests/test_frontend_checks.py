"""Runs every frontend check script (frontend/tests/*.check.mjs) as part of pytest.

The scripts are plain Node assertions without a test runner; before this test they only
ran when called by hand, so a broken check could go unnoticed. Skipped without node.
"""

from __future__ import annotations

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
