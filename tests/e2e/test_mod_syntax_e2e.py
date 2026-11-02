"""Lua 5.1 syntax check of the generated world mods in a pinned helper image (06-26, D-26).

The comments in the generated init.lua files were translated; this test parses the
generated source of every mod and language with ``luac -p`` and never executes it.
Luanti runs mods on LuaJIT, whose syntax is Lua 5.1, so the check uses a Lua 5.1
compiler. The pinned Luanti image brings no Lua compiler, hence a small helper image
(LUA51_IMAGE) that is only a test dependency and never part of the ExApp image.
The helper container runs without network, as an unprivileged user, and is always
removed. A deliberately broken line proves the check can fail.
"""

from __future__ import annotations

import io
import tarfile
from collections.abc import Callable, Iterator

import docker
import docker.errors
import pytest
from docker.models.containers import Container

from gameworld.provisioner import access_mod, status_mod, time_mod
from tests.conftest import docker_url

pytestmark = [pytest.mark.docker]

LANGUAGES = ("de", "en", "fr")
# Helper image with the reference compiler of Lua 5.1.5 (PUC-Rio), checked 02.11.2026:
# Docker Hub nickblah/lua, built by github.com/GUI/lua-docker (MIT) from
# https://www.lua.org/ftp/lua-5.1.5.tar.gz with SHA-1 check (see docker history);
# Alpine 3.12, linux/amd64, no volumes, no entrypoint, "luac -v" = "Lua 5.1.5".
# The 5.1 tags are no longer rebuilt, so the digest stays stable. Tag and digest
# are both pinned; the digest decides.
LUA51_REPOSITORY = "nickblah/lua"
LUA51_TAG = "5.1.5-alpine"
LUA51_DIGEST = "sha256:4d1e728ab63affad53db672f363ec2f416d83decbfd4c9741ee1055e112485c8"
LUA51_IMAGE = f"{LUA51_REPOSITORY}:{LUA51_TAG}@{LUA51_DIGEST}"
# Parse only: luac -p writes no output file and executes nothing.
PARSE_COMMAND = "luac -p /tmp/init.lua"
# Unprivileged user (like the Luanti worlds); /tmp is writable for every user in the image.
HELPER_USER = "30000"


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


@pytest.fixture(scope="module")
def helper_image(client: docker.DockerClient) -> str:
    """The pinned helper image; pulled by digest if missing. A failed pull fails the test (no skip)."""
    try:
        client.images.get(LUA51_IMAGE)
    except docker.errors.ImageNotFound:
        client.images.pull(f"{LUA51_REPOSITORY}@{LUA51_DIGEST}")
    image = client.images.get(LUA51_IMAGE)
    digests = image.attrs.get("RepoDigests") or []
    assert f"{LUA51_REPOSITORY}@{LUA51_DIGEST}" in digests, digests
    # No anonymous volumes for the throwaway containers.
    assert not (image.attrs.get("Config") or {}).get("Volumes"), image.attrs.get("Config")
    return LUA51_IMAGE


def _run(client: docker.DockerClient, image: str, command: str, lua: str | None) -> tuple[int, str]:
    """Run ``sh -c command`` in a throwaway helper container; optional /tmp/init.lua."""
    container: Container = client.containers.create(
        image, entrypoint=["sh"], command=["-c", command], network_disabled=True, user=HELPER_USER
    )
    try:
        if lua is not None:
            container.put_archive("/tmp", _tar_with(lua))  # noqa: S108
        container.start()
        result = container.wait(timeout=60)
        output = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")
        return int(result["StatusCode"]), output
    finally:
        container.remove(force=True)


@pytest.fixture(scope="module")
def parse(client: docker.DockerClient, helper_image: str) -> Callable[[str], tuple[int, str]]:
    """Parse function: luac -p of Lua 5.1 on the given source."""

    def run(lua: str) -> tuple[int, str]:
        return _run(client, helper_image, PARSE_COMMAND, lua)

    return run


def test_helper_compiler_is_lua_51(client: docker.DockerClient, helper_image: str) -> None:
    code, output = _run(client, helper_image, "luac -v", None)
    assert code == 0, output
    assert output.startswith("Lua 5.1"), output


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


def test_lua52_goto_is_rejected(parse: Callable[[str], tuple[int, str]]) -> None:
    """The grammar really is Lua 5.1: goto and labels (Lua 5.2, a LuaJIT extension) fail; never laxer than Luanti."""
    code, _output = parse("goto done\n::done::\n")
    assert code != 0
