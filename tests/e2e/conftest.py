"""Gemeinsame e2e-Fixtures.

Die ``relay``-Fixture (echter uvicorn-Server der ExApp im Modus dev) ist in
test_play_proxy_e2e.py definiert; hier wird sie fuer alle e2e-Tests verfuegbar gemacht,
ohne sie zu kopieren (04.2-09). Ein Testmodul ueberschreibt sie bei Bedarf lokal.
"""

from __future__ import annotations

from tests.e2e.test_play_proxy_e2e import relay

__all__ = ["relay"]
