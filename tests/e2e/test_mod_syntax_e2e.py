"""Lua syntax check of the generated world mods in the pinned Luanti image (06-26, D-26).

The comments in the generated init.lua files were translated; this test parses the
generated source of every mod and language with a Lua compiler from the pinned image and
never executes it. The compiler is looked up in the image first (luac, luac5.1, luajit);
if the image brings none, the test skips with a reason, and the existing world-start tests
(test_time_mod_e2e.py, test_access_e2e.py) are the equivalent check, because a syntax error
aborts the world start there. A deliberately broken line proves the check can fail.
"""

from __future__ import annotations

import io
import tarfile
from collections.abc import Callable, Iterator

import docker
import pytest
from docker.models.containers import Container

from gameworld.provisioner import access_mod, status_mod, time_mod
from gameworld.provisioner.spec import LUANTI_IMAGE
from tests.conftest import docker_url

pytestmark = [pytest.mark.docker]

LANGUAGES = ("de", "en", "fr")
# Compiler candidates in the image, in order of preference.
COMPILERS = ("luac", "luac5.1", "luajit")
# Parse only: luac -p lists nothing and executes nothing, luajit -bl lists bytecode.
PARSE_COMMANDS = {
    "luac": "luac -p /tmp/init.lua",
    "luac5.1": "luac5.1 -p /tmp/init.lua",
    "luajit": "luajit -bl /tmp/init.lua > /dev/null",
}


def _sources() -> list[tuple[str, str]]:
    sources: list[tuple[str, str]] = [("status", status_mod.MOD_INIT_LUA)]
    for language in LANGUAGES:
        sources.append((f"access-{language}", access_mod.mod_init_lua(language)))
        sources.append((f"time-{language}", time_mod.mod_init_lua(language)))
    return sources


def _tar_with(text: str) -> bytes:
    buffer = io.BytesIO()
    payload = text.encode("ascii")
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        info = tarfile.TarInfo("init.lua")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


@pytest.fixture(scope="module")
def client() -> Iterator[docker.DockerClient]:
    docker_client = docker.DockerClient(base_url=docker_url())
    try:
        yield docker_client
    finally:
        docker_client.close()


def _run(client: docker.DockerClient, command: str, lua: str | None) -> tuple[int, str]:
    """Run ``sh -c command`` in a throwaway container of the pinned image; optional /tmp/init.lua."""
    container: Container = client.containers.create(
        LUANTI_IMAGE, entrypoint=["sh"], command=["-c", command], network_disabled=True, user="30000"
    )
    try:
        if lua is not None:
            # /tmp is writable for every user in the image; the file lands in /tmp/init.lua.
            container.put_archive("/tmp", _tar_with(lua))  # noqa: S108
        container.start()
        result = container.wait(timeout=60)
        output = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")
        return int(result["StatusCode"]), output
    finally:
        container.remove(force=True)


@pytest.fixture(scope="module")
def parse(client: docker.DockerClient) -> Callable[[str], tuple[int, str]]:
    """Parse function of the first compiler the image brings; skips if there is none."""
    _code, output = _run(client, "command -v " + " ".join(COMPILERS) + " || true", None)
    found = [line.rsplit("/", 1)[-1] for line in output.split() if line.startswith("/")]
    compiler = next((name for name in COMPILERS if name in found), None)
    if compiler is None:
        pytest.skip(
            "The pinned Luanti image brings no Lua compiler (luac, luac5.1, luajit); "
            "test_time_mod_e2e.py and test_access_e2e.py are the equivalent check (world start parses init.lua)."
        )
    command = PARSE_COMMANDS[compiler]

    def run(lua: str) -> tuple[int, str]:
        return _run(client, command, lua)

    return run


@pytest.mark.parametrize(("label", "source"), _sources(), ids=[label for label, _ in _sources()])
def test_generated_init_lua_parses(parse: Callable[[str], tuple[int, str]], label: str, source: str) -> None:
    code, output = parse(source)
    assert code == 0, f"{label}: {output}"


def test_broken_line_is_rejected(parse: Callable[[str], tuple[int, str]]) -> None:
    """Positive control: the same check fails on a deliberately broken line."""
    code, _output = parse("if then\n")
    assert code != 0
    # And an intact file passes through the very same path.
    ok_code, ok_output = parse("local x = 1\n")
    assert ok_code == 0, ok_output
