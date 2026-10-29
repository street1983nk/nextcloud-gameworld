"""CLI of the session prober without network: --rejoin-after for the rejoin block (acceptance K6)."""

from __future__ import annotations

import json

import pytest

from tests.e2e import luanti_probe


def test_rejoin_after_runs_both_steps_in_one_process(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[str] = []

    def fake_session(
        host: str, port: int, name: str, password: str, hold: float, timeout: float = 8.0
    ) -> dict[str, object]:
        del host, port, name, password, timeout
        calls.append(f"session {hold}")
        return {"result": "held"}

    def fake_join(
        host: str, port: int, name: str, password: str | None = None, timeout: float = 6.0
    ) -> dict[str, object]:
        del host, port, name, password, timeout
        calls.append("join")
        return {"result": "denied", "code": "CUSTOM_STRING", "reason": "Bitte einen Moment warten"}

    monkeypatch.setattr(luanti_probe, "session", fake_session)
    monkeypatch.setattr(luanti_probe, "join", fake_join)
    assert luanti_probe.main(["127.0.0.1", "30000", "Mia", "pw", "--hold", "2", "--rejoin-after", "0.05"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert calls == ["session 2.0", "join"]
    assert out["result"] == "held"
    assert out["rejoin"]["result"] == "denied"
    # The measured gap is close to the requested one, with no process start in between.
    assert 0.05 <= out["gap_s"] < 1.0


def test_rejoin_after_needs_hold() -> None:
    with pytest.raises(SystemExit):
        luanti_probe.main(["127.0.0.1", "30000", "Mia", "pw", "--rejoin-after", "0.2"])
