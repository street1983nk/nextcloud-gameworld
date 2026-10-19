"""Spielernamen aus der Status-Datei und RAM-Formel aus docker stats, ohne Docker."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import docker
import pytest
import requests.exceptions

from gameworld.provisioner.client import DockerProvisioner, MemoryUsage, WorldNotFoundError, memory_from_stats
from gameworld.provisioner.status_mod import MAX_PLAYERS, parse_players

# parse_players


def test_parse_players_plain() -> None:
    assert parse_players(b"Leo\nMia\n") == ["Leo", "Mia"]


def test_parse_players_empty() -> None:
    assert parse_players(b"") == []


@pytest.mark.parametrize(
    "line",
    [
        "Leo Mia",
        "Jürgen",
        "<script>",
        "a" * 21,
        "192.168.0.5",
        "::1",
        " Leo",
        "",
    ],
)
def test_parse_players_drops_invalid_lines(line: str) -> None:
    assert parse_players(f"Mia\n{line}\nLeo".encode()) == ["Mia", "Leo"]


def test_parse_players_accepts_allowed_charset() -> None:
    assert parse_players(b"a_b-C9\n" + b"x" * 20) == ["a_b-C9", "x" * 20]


def test_parse_players_removes_duplicates_keeps_order() -> None:
    assert parse_players(b"Mia\nLeo\nMia\nLeo") == ["Mia", "Leo"]


def test_parse_players_caps_count() -> None:
    content = "\n".join(f"p{index}" for index in range(MAX_PLAYERS + 10)).encode()
    names = parse_players(content)
    assert len(names) == MAX_PLAYERS
    assert names[0] == "p0"


def test_parse_players_survives_invalid_utf8() -> None:
    assert parse_players(b"Leo\n\xff\xfe\nMia\r\n") == ["Leo", "Mia"]


# memory_from_stats

LIMIT = 536870912


def test_memory_cgroup_v2() -> None:
    stats = {"memory_stats": {"usage": 34500000, "limit": LIMIT, "stats": {"inactive_file": 15300000}}}
    assert memory_from_stats(stats) == (19200000, LIMIT)


def test_memory_cgroup_v1_fallback() -> None:
    stats = {"memory_stats": {"usage": 34500000, "limit": LIMIT, "stats": {"total_inactive_file": 15300000}}}
    assert memory_from_stats(stats) == (19200000, LIMIT)


def test_memory_without_inactive_counts_usage() -> None:
    assert memory_from_stats({"memory_stats": {"usage": 1000, "limit": LIMIT, "stats": {}}}) == (1000, LIMIT)


@pytest.mark.parametrize(
    "stats",
    [
        {},
        {"memory_stats": {}},
        {"memory_stats": {"limit": LIMIT}},
        {"memory_stats": {"usage": 1000}},
        {"memory_stats": {"usage": "viel", "limit": LIMIT}},
        {"memory_stats": {"usage": 1000, "limit": 0}},
    ],
)
def test_memory_missing_fields_is_none(stats: dict[str, Any]) -> None:
    assert memory_from_stats(stats) is None


def test_memory_usage_below_inactive_is_zero() -> None:
    stats = {"memory_stats": {"usage": 100, "limit": LIMIT, "stats": {"inactive_file": 500}}}
    assert memory_from_stats(stats) == (0, LIMIT)


# memory_bytes

INSTANCE = "ab12cd34"
WORLD = "0123456789ab"
STATS = {"memory_stats": {"usage": 34500000, "limit": LIMIT, "stats": {"inactive_file": 15300000}}}


class StatsContainer:
    def __init__(self, status: str = "running", instance: str = INSTANCE) -> None:
        self.status = status
        self.labels = {
            "gameworld.managed": "true",
            "gameworld.instance": instance,
            "gameworld.world_id": WORLD,
        }
        self.calls: list[dict[str, object]] = []

    def stats(self, **kwargs: object) -> dict[str, Any]:
        self.calls.append(kwargs)
        return STATS


class Listing:
    def __init__(self, containers: list[StatsContainer], errors: list[BaseException] | None = None) -> None:
        self.containers = containers
        self.errors = errors or []
        self.calls = 0

    def __call__(self, *args: object, **kwargs: object) -> list[StatsContainer]:
        del args, kwargs
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return self.containers


def _prov(monkeypatch: pytest.MonkeyPatch, listing: Listing) -> DockerProvisioner:
    fake = SimpleNamespace(containers=SimpleNamespace(list=listing))
    provisioner = DockerProvisioner("tcp://127.0.0.1:23750", INSTANCE)
    provisioner._client = cast("docker.DockerClient", fake)
    monkeypatch.setattr(provisioner, "_docker", lambda: fake)
    return provisioner


def test_memory_bytes_running_uses_one_shot(monkeypatch: pytest.MonkeyPatch) -> None:
    container = StatsContainer()
    prov = _prov(monkeypatch, Listing([container]))
    assert prov.memory_bytes(WORLD) == MemoryUsage(used=19200000, limit=LIMIT)
    assert container.calls == [{"stream": False, "one_shot": True}]


@pytest.mark.parametrize("status", ["exited", "created", "restarting"])
def test_memory_bytes_not_running_is_none(monkeypatch: pytest.MonkeyPatch, status: str) -> None:
    container = StatsContainer(status=status)
    prov = _prov(monkeypatch, Listing([container]))
    assert prov.memory_bytes(WORLD) is None
    assert container.calls == []


def test_memory_bytes_foreign_container_is_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    container = StatsContainer(instance="fremd000")
    prov = _prov(monkeypatch, Listing([container]))
    with pytest.raises(WorldNotFoundError):
        prov.memory_bytes(WORLD)
    assert container.calls == []


def test_memory_bytes_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    listing = Listing([StatsContainer()], [requests.exceptions.ConnectionError("weg")])
    prov = _prov(monkeypatch, listing)
    assert prov.memory_bytes(WORLD) == MemoryUsage(used=19200000, limit=LIMIT)
    assert listing.calls == 2
