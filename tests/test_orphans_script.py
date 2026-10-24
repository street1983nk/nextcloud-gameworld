"""Host-Skript scripts/gameworld-orphans.sh (06-08, T-06-36) gegen eine docker-Attrappe.

Die Attrappe protokolliert jeden Aufruf und gibt feste Listen aus, darunter
einen Container ohne managed-Label (als hätte docker den Filter ignoriert) und
Volumes, die nur ähnlich heißen. Der PATH enthält nur die Attrappe und die
Werkzeuge der Shell; der Test prüft vorher, dass "docker" wirklich die Attrappe ist.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "gameworld-orphans.sh"
SH = shutil.which("sh")

pytestmark = pytest.mark.skipif(SH is None, reason="keine POSIX-Shell (sh) verfügbar")

FOREIGN = "gameworld-deadbeef-000000000002"
PS_LINES = (
    f"c0ffee000001\t{FOREIGN}\ttrue\tdeadbeef\tExited (0) 2 days ago\n"
    # Ohne managed-Label: darf trotz Namens nie erscheinen oder entfernt werden.
    "c0ffee000002\tgameworld-dev-app-1\t\t\tUp 4 hours\n"
)
VOLUME_LINES = f"{FOREIGN}\ngameworld-dev_nextcloud\ngameworldx-fremd\nnc_data\n"

FAKE_DOCKER = """#!/bin/sh
printf '%s\\n' "$*" >> "$DOCKER_LOG"
case "$1" in
ps)
	case "$*" in
	*name=nc_app_gameworld*)
		[ -n "${FAKE_EXAPP:-}" ] && printf '%s\\n' "$FAKE_EXAPP"
		exit 0
		;;
	esac
	cat "$FAKE_PS"
	;;
volume)
	if [ "$2" = "ls" ]; then
		cat "$FAKE_VOLUMES"
	fi
	;;
esac
exit 0
"""


@dataclass
class Run:
    code: int
    out: str
    err: str
    calls: list[str]


@dataclass
class Host:
    bin_dir: Path
    log: Path
    ps: Path
    volumes: Path
    env: dict[str, str]

    def run(self, *args: str, stdin: str = "") -> Run:
        self.log.write_text("", encoding="utf-8")
        assert SH is not None
        # Bytes statt Text: Unter Windows würde text=True jeden Zeilenumbruch zu CRLF machen.
        done = subprocess.run(  # noqa: S603
            [SH, SCRIPT.as_posix(), *args],
            input=stdin.encode(),
            capture_output=True,
            env=self.env,
            timeout=30,
            check=False,
        )
        calls = [line for line in self.log.read_text(encoding="utf-8").splitlines() if line]
        return Run(done.returncode, done.stdout.decode(), done.stderr.decode(), calls)


def _shell_path() -> str:
    """Nur das Verzeichnis der Shell-Werkzeuge, ohne ein echtes docker."""
    assert SH is not None
    dirs: list[str] = []
    for tool in ("sh", "grep", "wc", "tr", "cut", "sed", "cat"):
        found = shutil.which(tool)
        if found is None:
            continue
        folder = str(Path(found).parent)
        if folder not in dirs and not (Path(folder) / "docker").exists() and not (Path(folder) / "docker.exe").exists():
            dirs.append(folder)
    return os.pathsep.join(dirs)


@pytest.fixture
def host(tmp_path: Path) -> Host:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER, encoding="utf-8", newline="\n")
    docker.chmod(0o755)
    ps = tmp_path / "ps.txt"
    ps.write_text(PS_LINES, encoding="utf-8", newline="\n")
    volumes = tmp_path / "volumes.txt"
    volumes.write_text(VOLUME_LINES, encoding="utf-8", newline="\n")
    log = tmp_path / "docker.log"
    env = {
        "PATH": os.pathsep.join([str(bin_dir), _shell_path()]),
        "DOCKER_LOG": log.as_posix(),
        "FAKE_PS": ps.as_posix(),
        "FAKE_VOLUMES": volumes.as_posix(),
    }
    for key in ("SYSTEMROOT", "TEMP", "TMP"):
        if key in os.environ:
            env[key] = os.environ[key]
    result = Host(bin_dir, log, ps, volumes, env)
    # Sicherung: "docker" muss die Attrappe sein, nie der echte Daemon.
    assert SH is not None
    probe = subprocess.run(  # noqa: S603
        [SH, "-c", "command -v docker"], capture_output=True, text=True, env=env, timeout=30, check=False
    )
    resolved = probe.stdout.strip()
    assert resolved.endswith("/bin/docker"), resolved
    assert tmp_path.name in resolved, resolved
    return result


def _removals(calls: list[str]) -> list[str]:
    return [call for call in calls if call.startswith(("rm", "volume rm"))]


def test_default_run_never_removes(host: Host) -> None:
    """Standardlauf ruft nie rm auf."""
    run = host.run()
    assert run.code == 0, run.err
    assert _removals(run.calls) == []
    assert any(call.startswith("ps -a --filter label=gameworld.managed=true") for call in run.calls)
    assert FOREIGN in run.out
    assert "instance=deadbeef" in run.out
    assert "Nothing was changed" in run.out


def test_lookalikes_never_appear(host: Host) -> None:
    run = host.run()
    assert "gameworld-dev-app-1" not in run.out
    assert "gameworld-dev_nextcloud" not in run.out
    assert "gameworldx-fremd" not in run.out
    assert "nc_data" not in run.out


def test_no_leftovers(host: Host) -> None:
    host.ps.write_text("c0ffee000002\tgameworld-dev-app-1\t\t\tUp\n", encoding="utf-8", newline="\n")
    host.volumes.write_text("gameworld-dev_nextcloud\ngameworldx-fremd\n", encoding="utf-8", newline="\n")
    run = host.run("--remove-containers", "--remove-volumes", "--yes")
    assert run.code == 0, run.err
    assert run.out.strip() == "No Gameworld leftovers found."
    assert _removals(run.calls) == []


def test_remove_containers_after_yes(host: Host) -> None:
    run = host.run("--remove-containers", stdin="yes\n")
    assert run.code == 0, run.err
    assert "Remove 1 Gameworld containers? Type yes:" in run.out
    assert _removals(run.calls) == ["rm -f c0ffee000001"]


@pytest.mark.parametrize("answer", ["", "no\n", "y\n", "YES\n"])
def test_remove_containers_needs_exact_yes(host: Host, answer: str) -> None:
    run = host.run("--remove-containers", stdin=answer)
    assert run.code == 0, run.err
    assert _removals(run.calls) == []
    assert "Containers kept." in run.out


def test_yes_flag_skips_container_question(host: Host) -> None:
    run = host.run("--remove-containers", "--yes")
    assert run.code == 0, run.err
    assert "Type yes" not in run.out
    assert _removals(run.calls) == ["rm -f c0ffee000001"]


@pytest.mark.parametrize("answer", ["", "yes\n", "y\n", "DELETE\n"])
def test_yes_never_deletes_volumes_without_delete(host: Host, answer: str) -> None:
    """--yes löscht keine Volumes ohne delete."""
    run = host.run("--remove-volumes", "--yes", stdin=answer)
    assert run.code == 0, run.err
    assert "This deletes the game worlds stored in 1 volumes permanently. Type delete:" in run.out
    assert _removals(run.calls) == []
    assert "Volumes kept." in run.out


def test_remove_volumes_after_delete_only_touches_scheme(host: Host) -> None:
    run = host.run("--remove-volumes", stdin="delete\n")
    assert run.code == 0, run.err
    assert _removals(run.calls) == [f"volume rm {FOREIGN}"]


def test_both_flags_remove_containers_first(host: Host) -> None:
    run = host.run("--remove-containers", "--remove-volumes", stdin="yes\ndelete\n")
    assert run.code == 0, run.err
    assert _removals(run.calls) == ["rm -f c0ffee000001", f"volume rm {FOREIGN}"]


def test_warns_when_app_container_still_exists(host: Host) -> None:
    host.env["FAKE_EXAPP"] = "abc123"
    run = host.run()
    assert "still exists" in run.out


def test_help_and_unknown_option(host: Host) -> None:
    helped = host.run("--help")
    assert helped.code == 0
    assert "Usage: gameworld-orphans.sh" in helped.out
    assert helped.calls == []
    unknown = host.run("--force")
    assert unknown.code == 2
    assert "Unknown option: --force" in unknown.err
    assert unknown.calls == []


def test_without_docker_cli(host: Host) -> None:
    (host.bin_dir / "docker").unlink()
    host.env["PATH"] = _shell_path()
    run = host.run()
    assert run.code == 1
    assert "docker CLI not found" in run.err
