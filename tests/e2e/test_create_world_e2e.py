"""Durchstich: HTTP-POST bis zum laufenden, gehärteten, privaten Luanti-Container."""

from __future__ import annotations

import io
import re
import tarfile
import time

import docker
import httpx
import pytest
from docker.models.containers import Container

from tests.conftest import appapi_headers, docker_url

pytestmark = [pytest.mark.docker, pytest.mark.usefixtures("docker_cleanup")]


def _wait_for_log(container: Container, needle: str, timeout: float = 30.0) -> str:
    deadline = time.monotonic() + timeout
    logs = ""
    while time.monotonic() < deadline:
        container.reload()
        logs = container.logs().decode("utf-8", errors="replace")
        if needle in logs:
            return logs
        if container.status == "exited":
            break
        time.sleep(0.5)
    pytest.fail(f"Container meldet nicht '{needle}'. Status {container.status}, Log:\n{logs}")


def _read_file(container: Container, path: str) -> tuple[tarfile.TarInfo, str]:
    stream, _ = container.get_archive(path)
    raw = b"".join(stream)
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as tar:
        member = tar.getmembers()[0]
        handle = tar.extractfile(member)
        assert handle is not None
        return member, handle.read().decode("utf-8")


async def test_create_world_runs_hardened_private_container(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/worlds", json={"name": "Testwelt"}, headers=appapi_headers())
    assert response.status_code == 201, response.text
    created = response.json()
    assert re.fullmatch(r"[0-9a-f]{12}", created["id"])
    assert 30015 <= created["port"] <= 30019
    assert created["world_key"]
    assert created["name"] == "Testwelt"

    api = docker.DockerClient(base_url=docker_url(), version="auto", timeout=60)
    try:
        matches = api.containers.list(all=True, filters={"label": [f"gameworld.world_id={created['id']}"]})
        assert len(matches) == 1
        container = matches[0]
        _wait_for_log(container, "listening on")
        assert container.status == "running"

        attrs = container.attrs
        host = attrs["HostConfig"]
        assert host["Memory"] == 536870912
        assert host["MemorySwap"] == 536870912
        assert host["PidsLimit"] == 128
        assert host["NanoCpus"] == 1_000_000_000
        assert host["CapDrop"] == ["ALL"]
        assert host["SecurityOpt"] == ["no-new-privileges:true"]
        assert host["ReadonlyRootfs"] is True
        assert host["Privileged"] is False
        assert host["RestartPolicy"]["Name"] == "no"
        assert attrs["Config"]["User"] == "30000:30000"
        assert attrs["Config"]["Image"].endswith(
            "@sha256:db682caec367977ac2661c81e3cdbd1f1dbbae596f6fa7d791c0031107d59947"
        )
        labels = attrs["Config"]["Labels"]
        assert labels["gameworld.managed"] == "true"
        assert labels["gameworld.port"] == str(created["port"])
        volume_mounts = [mount for mount in attrs["Mounts"] if mount["Type"] == "volume"]
        assert len(volume_mounts) == 1
        assert volume_mounts[0]["Name"] == container.name
        assert volume_mounts[0]["Destination"] == "/var/lib/minetest"

        member, conf = _read_file(container, "/var/lib/minetest/minetest.conf")
        assert member.uid == 0
        assert member.mode & 0o777 == 0o444
        lines = conf.splitlines()
        assert "server_announce = false" in lines
        assert f"default_password = {created['world_key']}" in lines
    finally:
        api.close()

    listing = await client.get("/api/worlds", headers=appapi_headers())
    assert listing.status_code == 200
    worlds = listing.json()["worlds"]
    mine = [world for world in worlds if world["id"] == created["id"]]
    assert len(mine) == 1
    assert mine[0]["docker_status"] == "running"
    assert "world_key" not in mine[0]
