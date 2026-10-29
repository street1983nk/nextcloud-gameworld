"""Sessions of the WebSocket proxy: passcode, limits, expiry and counter log (04.2-07)."""

from __future__ import annotations

import dataclasses
import logging
import re

import pytest

from gameworld.play.sessions import BIND_LIMIT, UNBOUND_SECONDS, SessionError, SessionRegistry
from tests.play.test_tickets import FakeClock

W1 = "aaaaaaaaaaa1"
W2 = "aaaaaaaaaaa2"
TARGET = ("127.0.0.1", 30015)
TARGET2 = ("127.0.0.1", 30016)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def registry(clock: FakeClock) -> SessionRegistry:
    return SessionRegistry(clock=clock)


def _reason(excinfo: pytest.ExceptionInfo[SessionError]) -> str:
    return excinfo.value.reason


def test_pos_create_passcode(registry: SessionRegistry) -> None:
    session = registry.create("gw-kind", W1, "Mia", TARGET)
    # 16 bytes from secrets.token_urlsafe give 22 characters, URL-safe.
    assert re.fullmatch(r"[A-Za-z0-9_-]{22}", session.passcode)
    assert (session.uid, session.world_id, session.player_name, session.target) == ("gw-kind", W1, "Mia", TARGET)
    other = registry.create("gw-kind2", W1, "Leo", TARGET)
    assert other.passcode != session.passcode


def test_neg_create_busy_same_uid_and_world(registry: SessionRegistry) -> None:
    registry.create("gw-kind", W1, "Mia", TARGET)
    with pytest.raises(SessionError) as excinfo:
        registry.create("gw-kind", W1, "Mia", TARGET)
    assert _reason(excinfo) == "busy"
    # Positive controls: another child same world, same child another world.
    registry.create("gw-kind2", W1, "Leo", TARGET)
    registry.create("gw-kind", W2, "Mia", TARGET2)


def test_pos_bind_counts(registry: SessionRegistry) -> None:
    session = registry.create("gw-kind", W1, "Mia", TARGET)
    bound = registry.bind(session.passcode)
    assert bound is session
    registry.bind(session.passcode, uid="gw-kind")
    assert session.binds == 2
    assert session.active_binds == 2


def test_neg_fifth_bind(registry: SessionRegistry) -> None:
    session = registry.create("gw-kind", W1, "Mia", TARGET)
    for _ in range(BIND_LIMIT):
        registry.bind(session.passcode)
    with pytest.raises(SessionError) as excinfo:
        registry.bind(session.passcode)
    assert _reason(excinfo) == "too_many_binds"
    assert session.binds == BIND_LIMIT


def test_neg_bind_unknown_passcode(registry: SessionRegistry) -> None:
    session = registry.create("gw-kind", W1, "Mia", TARGET)
    with pytest.raises(SessionError) as excinfo:
        registry.bind("A" * 22)
    assert _reason(excinfo) == "unknown"
    # Positive control: the real passcode.
    assert registry.bind(session.passcode) is session


def test_neg_bind_uid_mismatch(registry: SessionRegistry) -> None:
    session = registry.create("gw-kind", W1, "Mia", TARGET)
    with pytest.raises(SessionError) as excinfo:
        registry.bind(session.passcode, uid="gw-kind2")
    assert _reason(excinfo) == "uid_mismatch"
    assert session.binds == 0
    # Positive control: same identity.
    assert registry.bind(session.passcode, uid="gw-kind") is session


def test_neg_unbound_session_expires(registry: SessionRegistry, clock: FakeClock) -> None:
    session = registry.create("gw-kind", W1, "Mia", TARGET)
    clock.advance(UNBOUND_SECONDS)
    with pytest.raises(SessionError) as excinfo:
        registry.bind(session.passcode)
    assert _reason(excinfo) == "unknown"
    # Expiry frees (uid, world_id).
    registry.create("gw-kind", W1, "Mia", TARGET)


def test_pos_unbound_session_before_expiry(registry: SessionRegistry, clock: FakeClock) -> None:
    session = registry.create("gw-kind", W1, "Mia", TARGET)
    clock.advance(UNBOUND_SECONDS - 1)
    assert registry.bind(session.passcode) is session
    # Once bound it does not expire by the clock (the idle timeout in the relay handles that).
    clock.advance(UNBOUND_SECONDS * 10)
    with pytest.raises(SessionError):
        registry.create("gw-kind", W1, "Mia", TARGET)


def test_pos_release_after_last_unbind(registry: SessionRegistry) -> None:
    session = registry.create("gw-kind", W1, "Mia", TARGET)
    registry.bind(session.passcode)
    registry.bind(session.passcode)
    registry.unbind(session.passcode)
    # A BIND is still running: still occupied.
    with pytest.raises(SessionError):
        registry.create("gw-kind", W1, "Mia", TARGET)
    registry.unbind(session.passcode)
    again = registry.create("gw-kind", W1, "Mia", TARGET)
    assert again.passcode != session.passcode
    # The old passcode is worthless afterwards.
    with pytest.raises(SessionError) as excinfo:
        registry.bind(session.passcode)
    assert _reason(excinfo) == "unknown"


def test_neg_target_immutable(registry: SessionRegistry) -> None:
    session = registry.create("gw-kind", W1, "Mia", TARGET)
    with pytest.raises(AttributeError):
        session.target = ("192.168.0.1", 53)  # pyright: ignore[reportAttributeAccessIssue]
    with pytest.raises(dataclasses.FrozenInstanceError):
        session.key.target = ("192.168.0.1", 53)  # pyright: ignore[reportAttributeAccessIssue]
    assert session.target == TARGET
    assert not any(name.startswith("set") for name in dir(session))


def test_neg_bind_after_guard_end(registry: SessionRegistry) -> None:
    session = registry.create("gw-kind", W1, "Mia", TARGET)
    registry.bind(session.passcode)
    session.guard.ended = True
    with pytest.raises(SessionError) as excinfo:
        registry.bind(session.passcode)
    assert _reason(excinfo) == "ended"


def test_pos_guard_per_session_uses_ticket_name(registry: SessionRegistry) -> None:
    session = registry.create("gw-kind", W1, "Mia", TARGET)
    assert session.guard.expected_name == "Mia"
    # Two BINDs share the same guard.
    assert registry.bind(session.passcode).guard is registry.bind(session.passcode).guard


def test_pos_end_log_counts_only(registry: SessionRegistry, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="gameworld.play.sessions")
    session = registry.create("gw-kind", W1, "Mia", TARGET)
    registry.bind(session.passcode)
    registry.bind(session.passcode)
    registry.unbind(session.passcode)
    registry.unbind(session.passcode)
    lines = [record.getMessage() for record in caplog.records if "play session end" in record.getMessage()]
    assert lines == ["play session end binds=2 newaddr=1"]
    everything = caplog.text + " ".join(repr(record.args) for record in caplog.records)
    for secret in ("gw-kind", "Mia", session.passcode, W1):
        assert secret not in everything


def test_pos_end_log_newaddr_counts_per_uid_world(
    registry: SessionRegistry, clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="gameworld.play.sessions")
    registry.create("gw-kind", W1, "Mia", TARGET)
    with pytest.raises(SessionError):
        registry.create("gw-kind", W1, "Mia", TARGET)
    registry.create("gw-kind2", W1, "Leo", TARGET)
    # Expiry without BIND writes the line as well, at the next call.
    clock.advance(UNBOUND_SECONDS)
    session = registry.create("gw-kind", W1, "Mia", TARGET)
    registry.bind(session.passcode)
    registry.unbind(session.passcode)
    lines = [record.getMessage() for record in caplog.records if "play session end" in record.getMessage()]
    assert sorted(lines) == sorted(
        [
            "play session end binds=0 newaddr=2",  # gw-kind, expired (two create calls until then)
            "play session end binds=0 newaddr=1",  # gw-kind2, expired
            "play session end binds=1 newaddr=3",  # gw-kind, third create
        ]
    )


def test_neg_unbind_unknown_is_harmless(registry: SessionRegistry) -> None:
    registry.unbind("A" * 22)
    session = registry.create("gw-kind", W1, "Mia", TARGET)
    registry.bind(session.passcode)
    registry.unbind(session.passcode)
    # Double unbind does not count into the negative and frees nothing foreign.
    registry.unbind(session.passcode)
    other = registry.create("gw-kind2", W1, "Leo", TARGET)
    registry.unbind(session.passcode)
    assert registry.bind(other.passcode) is other
