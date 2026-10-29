"""Player names and derived game passwords (owner decisions A2 and A3).

A child has one Luanti name and one password for all worlds (A2).
The password is stored nowhere (A3): it is derived anew every time from
HMAC-SHA256(secret, "<nextcloud-account>:<rotation>[:<salt>]"). The secret lives
only in the Nextcloud configuration (access/secret.py). Pure, stdlib only.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import unicodedata

# Without the easily confused i, l, o, 0 and 1; lower case only, so that
# upper/lower case does not get in the way on tablet keyboards.
PASSWORD_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # noqa: S105 (alphabet, not a password)
PASSWORD_GROUPS = 3
GROUP_LENGTH = 4

# Luanti: 1 to 20 characters from [A-Za-z0-9_-] (src/player.h, PLAYERNAME_SIZE).
PLAYER_NAME_MAX = 20
# Room for an appended digit on a name collision.
SUGGEST_MAX = 18
FALLBACK_NAME = "Spieler"
_FORBIDDEN_NAME = "singleplayer"
_NOT_ALLOWED = re.compile(r"[^A-Za-z0-9_-]")
# Umlauts as escapes (owner rule: no umlauts in code).
_TRANSLITERATION = str.maketrans(
    {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "Ä": "Ae",
        "Ö": "Oe",
        "Ü": "Ue",
        "ß": "ss",
    }
)
# Account IDs may contain dots, @ and spaces; only the part before them works as a name.
_UID_SEPARATORS = re.compile(r"[.@ ]")


_VALID_NAME = re.compile(rf"[A-Za-z0-9_-]{{1,{PLAYER_NAME_MAX}}}")
MSG_INVALID_NAME = "Der Spielername darf 1 bis 20 Zeichen haben: Buchstaben ohne Umlaute, Ziffern, _ und -."


def validate_player_name(raw: str) -> str:
    """Player name assigned by a manager; ValueError with a message (German source text).

    Same rule as Luanti (1 to 20 characters from [A-Za-z0-9_-]), plus never
    ``singleplayer`` (T-03-28). No silent correction: the name appears in the game as is.
    """
    if not _VALID_NAME.fullmatch(raw) or raw.lower() == _FORBIDDEN_NAME:
        raise ValueError(MSG_INVALID_NAME)
    return raw


def new_player_salt() -> str:
    """Random salt per newly created player row (128 bit, hex)."""
    return secrets.token_hex(16)


def derive_password(secret: bytes, nc_user: str, rotation: int, salt: str = "") -> str:
    """Game password of an account, e.g. ``k7mp-q3xa-9tre``.

    Twelve characters from 31 give 12 x log2(31) = 59.4 bits. This is necessary because
    the SRP verifiers live in the world volume and later in backups: whoever
    captures one of them can guess offline. Word combinations with 22 to 30 bits
    would be found within hours, 59 bits would not. Online, the lock of the
    world mod additionally limits attempts (5 failed attempts, 10 minutes).

    ``salt`` comes from the player row (schema 6). Empty means: row from the time
    before, the password stays exactly the previous one. With a salt, an account
    created later under the same account ID never gets the password of the
    deleted account, even if the rotation starts at 0 again.
    """
    message = f"{nc_user}:{rotation}" if not salt else f"{nc_user}:{rotation}:{salt}"
    mac = hmac.new(secret, message.encode(), hashlib.sha256).digest()
    number = int.from_bytes(mac, "big")
    chars: list[str] = []
    for _ in range(PASSWORD_GROUPS * GROUP_LENGTH):
        number, index = divmod(number, len(PASSWORD_ALPHABET))
        chars.append(PASSWORD_ALPHABET[index])
    groups = ("".join(chars[i : i + GROUP_LENGTH]) for i in range(0, len(chars), GROUP_LENGTH))
    return "-".join(groups)


def _ascii_name(text: str) -> str:
    """Transliterate umlauts, reduce the rest to ASCII via NFKD, drop disallowed characters."""
    text = unicodedata.normalize("NFC", text).translate(_TRANSLITERATION)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return _NOT_ALLOWED.sub("", text)


def _base_name(display_name: str, uid: str) -> str:
    words = display_name.split()
    base = _ascii_name(words[0]) if words else ""
    if not base and not display_name.strip():
        # Account ID without display name only, and only the part before a dot, @ or space.
        base = _ascii_name(_UID_SEPARATORS.split(uid.strip(), maxsplit=1)[0])
    base = base[:SUGGEST_MAX]
    if not base or base.lower() == _FORBIDDEN_NAME:
        return FALLBACK_NAME
    return base


def suggest_player_name(display_name: str, uid: str, taken: set[str]) -> str:
    """Child-friendly Luanti name from the first word of the display name.

    ``taken`` contains assigned names in lower case. On a match ignoring
    case, a digit is appended (``Mia2``),
    because Luanti rejects accounts that differ only in that.
    """
    base = _base_name(display_name, uid)
    taken_lower = {name.lower() for name in taken}
    if base.lower() not in taken_lower:
        return base
    counter = 2
    while True:
        suffix = str(counter)
        candidate = base[: PLAYER_NAME_MAX - len(suffix)] + suffix
        if candidate.lower() not in taken_lower and candidate.lower() != _FORBIDDEN_NAME:
            return candidate
        counter += 1
