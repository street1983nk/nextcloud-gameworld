"""Abgeleitete Spielpasswörter, Spielernamen und das Geheimnis in Nextcloud (A2, A3)."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field

import pytest
from nc_py_api import NextcloudException

from gameworld.access.accounts import (
    PASSWORD_ALPHABET,
    PLAYER_NAME_MAX,
    derive_password,
    new_player_salt,
    suggest_player_name,
    validate_player_name,
)
from gameworld.access.secret import SECRET_KEY, PlayerSecret, SecretUnavailableError, fingerprint

SECRET = bytes(range(32))
PASSWORD_RE = re.compile(r"^[a-hj-km-np-z2-9]{4}-[a-hj-km-np-z2-9]{4}-[a-hj-km-np-z2-9]{4}$")
# Unabhängig per python -c (hmac, divmod über das Alphabet, erste Stelle = erster Rest) berechnet.
VECTOR_GW_KIND_0 = "nyd5-hh9q-u45t"
VECTOR_GW_KIND_1 = "updy-6kpg-2f23"


# Passwörter


def test_alphabet_has_no_confusable_characters() -> None:
    assert len(PASSWORD_ALPHABET) == 31
    assert not set("ilo01") & set(PASSWORD_ALPHABET)


def test_derive_password_matches_fixed_vector() -> None:
    assert derive_password(SECRET, "gw-kind", 0) == VECTOR_GW_KIND_0
    assert derive_password(SECRET, "gw-kind", 1) == VECTOR_GW_KIND_1


def test_derive_password_is_deterministic_and_well_formed() -> None:
    first = derive_password(SECRET, "gw-kind", 0)
    assert first == derive_password(SECRET, "gw-kind", 0)
    assert PASSWORD_RE.fullmatch(first)


def test_derive_password_changes_with_rotation_account_and_secret() -> None:
    base = derive_password(SECRET, "gw-kind", 0)
    assert derive_password(SECRET, "gw-kind", 1) != base
    assert derive_password(SECRET, "gw-anders", 0) != base
    assert derive_password(bytes(32), "gw-kind", 0) != base


# Zusatz je Spielerzeile (Schema 6). Vektor unabhängig berechnet: HMAC von Hand über
# sha256 (ipad/opad), Ziffern per wiederholtem Rest; derselbe Weg liefert VECTOR_GW_KIND_0.
SALT = "5a" * 16
VECTOR_GW_KIND_0_SALTED = "uq8x-t78x-7zyf"


def test_empty_salt_keeps_exact_previous_password() -> None:
    assert derive_password(SECRET, "gw-kind", 0, "") == VECTOR_GW_KIND_0
    assert derive_password(SECRET, "gw-kind", 1, "") == VECTOR_GW_KIND_1


def test_salt_changes_password_with_fixed_vector() -> None:
    assert derive_password(SECRET, "gw-kind", 0, SALT) == VECTOR_GW_KIND_0_SALTED
    assert derive_password(SECRET, "gw-kind", 0, SALT) != VECTOR_GW_KIND_0
    assert derive_password(SECRET, "gw-kind", 0, "6b" * 16) != VECTOR_GW_KIND_0_SALTED


def test_new_player_salt_is_random_hex() -> None:
    first, second = new_player_salt(), new_player_salt()
    assert re.fullmatch(r"[0-9a-f]{32}", first)
    assert first != second


# Spielernamen


def test_first_word_of_display_name() -> None:
    assert suggest_player_name("Mia Müller", "mia.m", set()) == "Mia"


@pytest.mark.parametrize(
    ("display", "expected"),
    [("Jörg", "Joerg"), ("Ölaf", "Oelaf"), ("Straße", "Strasse"), ("Ümit", "Uemit"), ("Renée", "Renee")],
)
def test_transliteration(display: str, expected: str) -> None:
    assert suggest_player_name(display, "x", set()) == expected


@pytest.mark.parametrize("display", ["", "   ", "!!!", "@@ ##"])
def test_fallback_name(display: str) -> None:
    assert suggest_player_name(display, "", set()) == "Spieler"


def test_uid_only_when_display_name_empty_and_only_before_separators() -> None:
    assert suggest_player_name("", "mia.mueller@example.org", set()) == "mia"
    assert suggest_player_name("", "leo@example.org", set()) == "leo"
    name = suggest_player_name("Kind (Dev)", "gw-kind", set())
    assert name == "Kind"


def test_collision_is_case_insensitive() -> None:
    assert suggest_player_name("Mia", "a", {"mia"}) == "Mia2"
    assert suggest_player_name("Mia", "a", {"mia", "mia2"}) == "Mia3"


def test_length_is_capped() -> None:
    name = suggest_player_name("Maximilianalexanderkonstantin", "x", set())
    assert len(name) <= PLAYER_NAME_MAX
    taken = {name.lower()} | {f"{name.lower()}{n}" for n in range(2, 12)}
    longer = suggest_player_name("Maximilianalexanderkonstantin", "x", taken)
    assert len(longer) <= PLAYER_NAME_MAX
    assert longer.lower() not in taken


@pytest.mark.parametrize("display", ["singleplayer", "SinglePlayer", "SINGLEPLAYER"])
def test_singleplayer_is_never_suggested(display: str) -> None:
    assert suggest_player_name(display, "x", set()).lower() != "singleplayer"


def test_names_are_always_valid_luanti_names() -> None:
    for display in ["Mia Müller", "李", "a.b@c", "-_-", "Ünal-Can", "x" * 40]:
        name = suggest_player_name(display, "konto.id@host", set())
        assert re.fullmatch(r"[A-Za-z0-9_-]{1,20}", name), display
        assert "." not in name
        assert "@" not in name


# Geheimnis


@dataclass
class FakeAppConfig:
    values: dict[str, str] = field(default_factory=dict)
    set_calls: list[tuple[str, bool | None]] = field(default_factory=list)
    get_error: Exception | None = None
    set_error: Exception | None = None
    # Was beim Rücklesen nach set_value herauskommt (None = wie gesetzt).
    read_back: str | None = None

    async def get_value(self, key: str, default: str | None = None) -> str | None:
        if self.get_error is not None:
            raise self.get_error
        return self.values.get(key, default)

    async def set_value(self, key: str, value: str, sensitive: bool | None = None) -> None:
        if self.set_error is not None:
            raise self.set_error
        self.set_calls.append((key, sensitive))
        self.values[key] = value if self.read_back is None else self.read_back


@dataclass
class FakeNc:
    appconfig_ex: FakeAppConfig


def _secret(config: FakeAppConfig) -> tuple[PlayerSecret, list[int]]:
    built: list[int] = []

    def factory() -> FakeNc:
        built.append(1)
        return FakeNc(config)

    return PlayerSecret(factory), built  # pyright: ignore[reportArgumentType]


async def test_existing_secret_is_loaded_and_cached() -> None:
    config = FakeAppConfig({SECRET_KEY: SECRET.hex()})
    secret, built = _secret(config)
    assert await secret.get() == SECRET
    assert await secret.get() == SECRET
    assert config.set_calls == []
    assert len(built) == 1


async def test_missing_secret_is_created_sensitive_and_read_back() -> None:
    config = FakeAppConfig()
    secret, _ = _secret(config)
    value = await secret.get()
    assert len(value) == 32
    assert config.set_calls == [(SECRET_KEY, True)]
    assert config.values[SECRET_KEY] == value.hex()


async def test_read_back_value_wins() -> None:
    # Ein paralleler Prozess hat zuerst geschrieben: Der zurückgelesene Wert gilt.
    config = FakeAppConfig(read_back=SECRET.hex())
    secret, _ = _secret(config)
    assert await secret.get() == SECRET


async def test_concurrent_first_use_creates_once() -> None:
    config = FakeAppConfig()
    secret, _ = _secret(config)
    values = await asyncio.gather(*(secret.get() for _ in range(5)))
    assert len(set(values)) == 1
    assert len(config.set_calls) == 1


@pytest.mark.parametrize("stored", ["zz", "abcd", SECRET.hex()[:-2], " " + SECRET.hex()])
async def test_unreadable_secret_is_never_overwritten(stored: str) -> None:
    config = FakeAppConfig({SECRET_KEY: stored})
    secret, _ = _secret(config)
    with pytest.raises(SecretUnavailableError):
        await secret.get()
    assert config.set_calls == []
    assert config.values[SECRET_KEY] == stored


async def test_nextcloud_error_on_read() -> None:
    config = FakeAppConfig(get_error=NextcloudException(500, "kaputt"))
    secret, _ = _secret(config)
    with pytest.raises(SecretUnavailableError):
        await secret.get()
    assert config.set_calls == []


async def test_nextcloud_error_on_write_is_not_cached() -> None:
    config = FakeAppConfig(set_error=NextcloudException(500, "kaputt"))
    secret, _ = _secret(config)
    with pytest.raises(SecretUnavailableError):
        await secret.get()
    config.set_error = None
    assert len(await secret.get()) == 32


async def test_error_message_never_contains_the_secret() -> None:
    stored = SECRET.hex()[:-2]
    config = FakeAppConfig({SECRET_KEY: stored})
    secret, _ = _secret(config)
    with pytest.raises(SecretUnavailableError) as info:
        await secret.get()
    assert stored not in str(info.value)


# Spielernamen von Hand (03-04) und Fingerabdruck des Geheimnisses

# Unabhängig per python -c (hmac.new(..., b"gameworld:fingerprint", sha256).hexdigest()[:16]) berechnet.
FINGERPRINT_VECTOR = "f9ddab6ceada0345"


@pytest.mark.parametrize("name", ["Mia_2", "a", "x" * 20, "Kind-Neu", "SinglePlayer2"])
def test_valid_player_names(name: str) -> None:
    assert validate_player_name(name) == name


@pytest.mark.parametrize(
    "name", ["", "singleplayer", "SinglePlayer", "x" * 21, "Müller", "Mia Neu", "Mia\n", "Mia.2", "Mia;x"]
)
def test_invalid_player_names(name: str) -> None:
    with pytest.raises(ValueError, match="1 bis 20 Zeichen"):
        validate_player_name(name)


def test_fingerprint_vector_and_independence_from_passwords() -> None:
    assert fingerprint(SECRET) == FINGERPRINT_VECTOR
    assert fingerprint(bytes(32)) != FINGERPRINT_VECTOR
    assert re.fullmatch("[0-9a-f]{16}", fingerprint(bytes(32)))
    # Der Fingerabdruck verrät weder Geheimnis noch ein Passwort.
    assert SECRET.hex()[:16] != FINGERPRINT_VECTOR
    assert FINGERPRINT_VECTOR not in VECTOR_GW_KIND_0.replace("-", "")
