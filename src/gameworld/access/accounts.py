"""Spielernamen und abgeleitete Spielpasswörter (Owner-Entscheide A2 und A3).

Ein Kind hat einen Luanti-Namen und ein Passwort für alle Welten (A2).
Gespeichert wird das Passwort nirgends (A3): Es folgt jedes Mal neu aus
HMAC-SHA256(Geheimnis, "<Nextcloud-Konto>:<Rotation>"). Das Geheimnis liegt
nur in der Nextcloud-Konfiguration (access/secret.py). Rein, nur stdlib.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import unicodedata

# Ohne die verwechselbaren i, l, o, 0 und 1; nur Kleinbuchstaben, damit auf
# Tablet-Tastaturen keine Groß-/Kleinschreibung stört.
PASSWORD_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # noqa: S105 (Alphabet, kein Passwort)
PASSWORD_GROUPS = 3
GROUP_LENGTH = 4

# Luanti: 1 bis 20 Zeichen aus [A-Za-z0-9_-] (src/player.h, PLAYERNAME_SIZE).
PLAYER_NAME_MAX = 20
# Platz für eine angehängte Ziffer bei Namensgleichheit.
SUGGEST_MAX = 18
FALLBACK_NAME = "Spieler"
_FORBIDDEN_NAME = "singleplayer"
_NOT_ALLOWED = re.compile(r"[^A-Za-z0-9_-]")
# Umlaute als Escapes (Owner-Regel: keine Umlaute im Code).
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
# Konto-IDs können Punkte, @ und Leerzeichen enthalten; nur der Teil davor taugt als Name.
_UID_SEPARATORS = re.compile(r"[.@ ]")


def derive_password(secret: bytes, nc_user: str, rotation: int) -> str:
    """Spielpasswort eines Kontos, etwa ``k7mp-q3xa-9tre``.

    Zwölf Zeichen aus 31 ergeben 12 x log2(31) = 59,4 Bit. Das ist nötig, weil
    die SRP-Verifier im Welt-Volume und später in Backups liegen: Wer eines
    davon erbeutet, kann offline raten. Wortkombinationen mit 22 bis 30 Bit
    wären in Stunden gefunden, 59 Bit nicht. Online begrenzt zusätzlich die
    Sperre des Welt-Mods (5 Fehlversuche, 10 Minuten).
    """
    mac = hmac.new(secret, f"{nc_user}:{rotation}".encode(), hashlib.sha256).digest()
    number = int.from_bytes(mac, "big")
    chars: list[str] = []
    for _ in range(PASSWORD_GROUPS * GROUP_LENGTH):
        number, index = divmod(number, len(PASSWORD_ALPHABET))
        chars.append(PASSWORD_ALPHABET[index])
    groups = ("".join(chars[i : i + GROUP_LENGTH]) for i in range(0, len(chars), GROUP_LENGTH))
    return "-".join(groups)


def _ascii_name(text: str) -> str:
    """Umlaute umschreiben, Rest per NFKD auf ASCII, unerlaubte Zeichen entfernen."""
    text = unicodedata.normalize("NFC", text).translate(_TRANSLITERATION)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return _NOT_ALLOWED.sub("", text)


def _base_name(display_name: str, uid: str) -> str:
    words = display_name.split()
    base = _ascii_name(words[0]) if words else ""
    if not base and not display_name.strip():
        # Konto-ID nur ohne Anzeigenamen, und nur der Teil vor Punkt, @ oder Leerzeichen.
        base = _ascii_name(_UID_SEPARATORS.split(uid.strip(), maxsplit=1)[0])
    base = base[:SUGGEST_MAX]
    if not base or base.lower() == _FORBIDDEN_NAME:
        return FALLBACK_NAME
    return base


def suggest_player_name(display_name: str, uid: str, taken: set[str]) -> str:
    """Kindgerechter Luanti-Name aus dem ersten Wort des Anzeigenamens.

    ``taken`` enthält vergebene Namen kleingeschrieben. Bei Gleichheit ohne
    Rücksicht auf Groß-/Kleinschreibung wird eine Ziffer angehängt (``Mia2``),
    weil Luanti Konten, die sich nur darin unterscheiden, ablehnt.
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
