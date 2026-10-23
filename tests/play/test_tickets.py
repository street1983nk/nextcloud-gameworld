"""Ein-Mal-Tickets des Browser-Spikes: Zweck, Ablauf, UID-Bindung, Einmaligkeit (04.2-06)."""

from __future__ import annotations

import pytest

from gameworld.play.tickets import (
    MAX_OPEN_PER_UID,
    TICKET_SECONDS,
    TOKEN_MAX,
    Ticket,
    TicketError,
    TicketStore,
)

W1 = "aaaaaaaaaaa1"


class FakeClock:
    """Uhr zum Vorstellen ohne sleep."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class RecordingDict(dict[str, Ticket]):
    """Merkt jeden Schlüssel, mit dem das Ticket-Wörterbuch befragt wird."""

    def __init__(self) -> None:
        super().__init__()
        self.keys_seen: list[str] = []

    def pop(self, key: str, *args: object) -> object:  # type: ignore[override]
        self.keys_seen.append(key)
        return super().pop(key, *args)  # pyright: ignore[reportCallIssue, reportArgumentType]

    def get(self, key: str, *args: object) -> object:  # type: ignore[override]
        self.keys_seen.append(key)
        return super().get(key, *args)  # pyright: ignore[reportCallIssue, reportArgumentType]

    def __getitem__(self, key: str) -> Ticket:
        self.keys_seen.append(key)
        return super().__getitem__(key)

    def __contains__(self, key: object) -> bool:
        self.keys_seen.append(str(key))
        return super().__contains__(key)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def store(clock: FakeClock) -> TicketStore:
    return TicketStore(clock=clock)


def _issue(store: TicketStore, uid: str = "gw-kind", purpose: str = "launch") -> str:
    return store.issue(purpose, uid=uid, world_id=W1, player_name="Mia")  # type: ignore[arg-type]


def test_constants() -> None:
    assert TICKET_SECONDS == 60.0
    assert MAX_OPEN_PER_UID == 4
    assert TOKEN_MAX == 64


def test_pos_issue_and_redeem(store: TicketStore, clock: FakeClock) -> None:
    token = _issue(store)
    # secrets.token_urlsafe(16): 128 Bit als 22 Zeichen Base64url.
    assert len(token) == 22
    ticket = store.redeem(token, "launch", uid="gw-kind")
    assert ticket == Ticket(uid="gw-kind", world_id=W1, player_name="Mia", purpose="launch", issued_at=clock.now)


def test_tokens_differ(store: TicketStore) -> None:
    tokens = {_issue(store, uid=f"u{index}") for index in range(50)}
    assert len(tokens) == 50


def test_neg_second_redeem(store: TicketStore) -> None:
    token = _issue(store)
    store.redeem(token, "launch", uid="gw-kind")
    with pytest.raises(TicketError) as info:
        store.redeem(token, "launch", uid="gw-kind")
    assert info.value.reason == "used_or_unknown"


def test_neg_unknown_token(store: TicketStore) -> None:
    _issue(store)
    with pytest.raises(TicketError) as info:
        store.redeem("A" * 22, "launch", uid="gw-kind")
    assert info.value.reason == "used_or_unknown"


def test_pos_redeem_before_expiry(store: TicketStore, clock: FakeClock) -> None:
    token = _issue(store)
    clock.advance(59)
    assert store.redeem(token, "launch", uid="gw-kind").world_id == W1


def test_neg_redeem_after_expiry(store: TicketStore, clock: FakeClock) -> None:
    token = _issue(store)
    clock.advance(61)
    with pytest.raises(TicketError) as info:
        store.redeem(token, "launch", uid="gw-kind")
    assert info.value.reason == "expired"
    # Abgelaufen ist auch verbrannt.
    clock.advance(-61)
    with pytest.raises(TicketError) as again:
        store.redeem(token, "launch", uid="gw-kind")
    assert again.value.reason == "used_or_unknown"


def test_neg_wrong_purpose_burns(store: TicketStore) -> None:
    token = _issue(store)
    with pytest.raises(TicketError) as info:
        store.redeem(token, "ws", uid="gw-kind")
    assert info.value.reason == "purpose"
    with pytest.raises(TicketError) as again:
        store.redeem(token, "launch", uid="gw-kind")
    assert again.value.reason == "used_or_unknown"


def test_neg_ws_ticket_as_launch(store: TicketStore) -> None:
    token = _issue(store, purpose="ws")
    with pytest.raises(TicketError) as info:
        store.redeem(token, "launch", uid="gw-kind")
    assert info.value.reason == "purpose"


def test_neg_uid_mismatch_burns(store: TicketStore) -> None:
    token = _issue(store)
    with pytest.raises(TicketError) as info:
        store.redeem(token, "launch", uid="gw-kind2")
    assert info.value.reason == "uid_mismatch"
    # Positivkontrolle wäre jetzt gw-kind; das Ticket ist aber verbrannt.
    with pytest.raises(TicketError) as again:
        store.redeem(token, "launch", uid="gw-kind")
    assert again.value.reason == "used_or_unknown"


def test_pos_uid_none_skips_uid_check(store: TicketStore) -> None:
    token = _issue(store)
    assert store.redeem(token, "launch", uid=None).uid == "gw-kind"


@pytest.mark.parametrize("token", ["", "x" * (TOKEN_MAX + 1), "y" * 1000])
def test_neg_malformed_token_never_touches_dict(store: TicketStore, token: str) -> None:
    recording = RecordingDict()
    store._tickets = recording  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(TicketError) as info:
        store.redeem(token, "launch", uid="gw-kind")
    assert info.value.reason == "malformed"
    assert recording.keys_seen == []


def test_pos_recording_dict_sees_valid_length(store: TicketStore) -> None:
    """Positivkontrolle der Aufzeichnung: ein gültig langer Token erreicht das Wörterbuch."""
    recording = RecordingDict()
    store._tickets = recording  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(TicketError):
        store.redeem("z" * 22, "launch", uid="gw-kind")
    assert recording.keys_seen == ["z" * 22]


def test_neg_oldest_dropped_beyond_limit(store: TicketStore) -> None:
    tokens = [_issue(store) for _ in range(MAX_OPEN_PER_UID + 1)]
    with pytest.raises(TicketError) as info:
        store.redeem(tokens[0], "launch", uid="gw-kind")
    assert info.value.reason == "used_or_unknown"
    for token in tokens[1:]:
        assert store.redeem(token, "launch", uid="gw-kind").uid == "gw-kind"


def test_pos_limit_is_per_uid(store: TicketStore) -> None:
    mine = [_issue(store) for _ in range(MAX_OPEN_PER_UID)]
    other = _issue(store, uid="gw-kind2")
    for token in mine:
        store.redeem(token, "launch", uid="gw-kind")
    store.redeem(other, "launch", uid="gw-kind2")


def test_expired_cleaned_on_issue(store: TicketStore, clock: FakeClock) -> None:
    _issue(store)
    _issue(store, uid="gw-kind2")
    clock.advance(61)
    fresh = _issue(store)
    assert list(store._tickets) == [fresh]  # pyright: ignore[reportPrivateUsage]


def test_ticket_repr_has_no_token(store: TicketStore) -> None:
    token = _issue(store)
    ticket = store.redeem(token, "launch", uid="gw-kind")
    assert token not in repr(ticket)
