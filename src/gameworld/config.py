"""Laufzeit-Einstellungen aus der Umgebung."""

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
    """Liest einen Bereich der Form ``<lo>-<hi>`` und prüft die Grenzen."""
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
    """Einstellungen aus der Umgebung; jede ungültige Umgebung wird zu ValueError.

    Aufrufer (Setup-Check, API) verlassen sich darauf, dass Konfigurationsfehler
    immer als ValueError mit deutscher Meldung ankommen, nie als roher OSError.
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
