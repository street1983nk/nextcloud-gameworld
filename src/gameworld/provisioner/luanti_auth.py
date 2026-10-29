"""Password verifier for Luanti accounts (SRP-6a), pure and with the standard library only.

Luanti stores passwords as ``#1#<base64 salt>#<base64 v>``: SRP-6a with
SHA-256, the 2048-bit group from RFC 5054 and ``g = 2``. It holds
``x = SHA256(salt || SHA256(lower(name) ":" password))`` and ``v = g^x mod N``,
``v`` as big-endian without leading zeros. Sources: luanti-org/luanti, tag 5.17.0,
``src/util/auth.cpp`` (gen_srp_v) and ``src/util/srp.cpp`` (calculate_x,
srp_create_salted_verification_key, NG_2048). Secured by a golden
vector that a real Luanti 5.17.0 server accepted on an SRP login.

Only the verifier reaches the world volume, never a plaintext password: the ExApp
computes it itself, the world mod sets it via ``core.set_player_password``.
"""

from __future__ import annotations

import base64
import hashlib
import secrets

N = int(
    "AC6BDB41324A9A9BF166DE5E1389582FAF72B6651987EE07FC3192943DB56050A37329CBB4A099ED8193E0757767A13DD52312AB4B03310D"
    "CD7F48A9DA04FD50E8083969EDB767B0CF6095179A163AB3661A05FBD5FAAAE82918A9962F0B93B855F97993EC975EEAA80D740ADBF4FF74"
    "7359D041D5C33EA71D281E446B14773BCA97B43A23FB801676BD207A436C6481F1D2B9078717461A5B9D32E688F87748544523B524B0D57D"
    "5EA77A2775D2ECFA032CFBDBF52FB3786160279004E57AE6AF874E7303CE53299CCC041C7BC308D82A5698F3A8D0C38271AE35F8E9DBFBB6"
    "94B5C803D89F7AE435DE236D525F54759B65E372FCD68EF20FA7111F9E4AFF73",
    16,
)
G = 2
# Luanti generates 16 bytes of random salt per verifier.
SALT_BYTES = 16


def _bin(n: int) -> bytes:
    """Like mpz_to_bin in srp.cpp: big-endian, minimal length, without leading zeros."""
    return n.to_bytes((n.bit_length() + 7) // 8, "big")


def make_verifier(name: str, password: str, salt: bytes | None = None) -> str:
    """Verifier in the Luanti format ``#1#<salt>#<v>``; without a salt with a fresh random salt.

    The name enters lower-cased: ``Mia`` and ``mia`` yield the same verifier
    with the same salt, as in Luanti.
    """
    salt = secrets.token_bytes(SALT_BYTES) if salt is None else salt
    inner = hashlib.sha256(name.lower().encode("utf-8") + b":" + password.encode("utf-8")).digest()
    x = int.from_bytes(hashlib.sha256(salt + inner).digest(), "big")
    v = pow(G, x, N)
    return f"#1#{base64.b64encode(salt).decode('ascii')}#{base64.b64encode(_bin(v)).decode('ascii')}"
