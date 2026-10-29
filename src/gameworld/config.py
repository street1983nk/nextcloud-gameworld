"""Runtime settings from the environment."""

from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass

DEFAULT_DOCKER_URL = "tcp://gameworld-docker-proxy:2375"
DEFAULT_PORT_RANGE = "30000-30019"
DEV_STORAGE = ".dev/storage"
MAX_RANGE_WIDTH = 200
# Templates of configuration errors (D-25); they reach the setup check and 503 answers.
TEXT_PORT_RANGE_INVALID = (
    "GAMEWORLD_PORT_RANGE ist ungültig: '{raw}'. Erwartet wird '<von>-<bis>' mit "
    "1024 <= von <= bis <= 65535 und höchstens {max_width} Ports."
)
TEXT_STORAGE_UNUSABLE = (
    "APP_PERSISTENT_STORAGE ist nicht nutzbar: '{storage}' lässt sich nicht als Verzeichnis anlegen ({error})."
)


@dataclass(frozen=True)
class Settings:
    docker_url: str
    port_range: tuple[int, int]
    storage_dir: pathlib.Path


def parse_port_range(raw: str) -> tuple[int, int]:
    """Read a range of the form ``<lo>-<hi>`` and check its bounds."""
    message = TEXT_PORT_RANGE_INVALID.format(raw=raw, max_width=MAX_RANGE_WIDTH)
    parts = raw.strip().split("-")
    if len(parts) != 2:
        raise ValueError(message)
    try:
        low, high = int(parts[0]), int(parts[1])
    except ValueError:
        raise ValueError(message) from None
    if not (1024 <= low <= high <= 65535) or high - low >= MAX_RANGE_WIDTH:
        raise ValueError(message)
    return low, high


def load_settings() -> Settings:
    """Settings from the environment; every invalid environment becomes a ValueError.

    Callers (setup check, API) rely on configuration errors always arriving
    as a ValueError with a message (German source text, D-25), never as a raw OSError.
    """
    storage = pathlib.Path(os.environ.get("APP_PERSISTENT_STORAGE") or DEV_STORAGE)
    try:
        storage.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(TEXT_STORAGE_UNUSABLE.format(storage=storage, error=exc)) from exc
    return Settings(
        docker_url=os.environ.get("GAMEWORLD_DOCKER_URL") or DEFAULT_DOCKER_URL,
        port_range=parse_port_range(os.environ.get("GAMEWORLD_PORT_RANGE") or DEFAULT_PORT_RANGE),
        storage_dir=storage,
    )
