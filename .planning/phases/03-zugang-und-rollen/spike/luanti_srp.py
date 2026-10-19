"""SRP-6a wie Luanti 5.17.0 (src/util/srp.cpp, src/util/auth.cpp): SHA256, NG_2048, g=2."""

from __future__ import annotations

import base64
import hashlib
import secrets

N_HEX = (
    "AC6BDB41324A9A9BF166DE5E1389582FAF72B6651987EE07FC319294"
    "3DB56050A37329CBB4A099ED8193E0757767A13DD52312AB4B03310D"
    "CD7F48A9DA04FD50E8083969EDB767B0CF6095179A163AB3661A05FB"
    "D5FAAAE82918A9962F0B93B855F97993EC975EEAA80D740ADBF4FF74"
    "7359D041D5C33EA71D281E446B14773BCA97B43A23FB801676BD207A"
    "436C6481F1D2B9078717461A5B9D32E688F87748544523B524B0D57D"
    "5EA77A2775D2ECFA032CFBDBF52FB3786160279004E57AE6AF874E73"
    "03CE53299CCC041C7BC308D82A5698F3A8D0C38271AE35F8E9DBFBB6"
    "94B5C803D89F7AE435DE236D525F54759B65E372FCD68EF20FA7111F"
    "9E4AFF73"
)
N = int(N_HEX, 16)
G = 2
N_LEN = (N.bit_length() + 7) // 8


def _bin(n: int) -> bytes:
    # mpz_to_bin: big endian, minimale Länge (keine führenden Nullen)
    return n.to_bytes((n.bit_length() + 7) // 8, "big")


def _h(*parts: bytes) -> bytes:
    h = hashlib.sha256()
    for p in parts:
        h.update(p)
    return h.digest()


def _x(salt: bytes, name: str, password: str) -> int:
    inner = _h(name.lower().encode("utf-8"), b":", password.encode("utf-8"))
    return int.from_bytes(_h(salt, inner), "big")


def make_verifier(name: str, password: str, salt: bytes | None = None) -> str:
    salt = salt if salt is not None else secrets.token_bytes(16)
    v = pow(G, _x(salt, name, password), N)
    return "#1#" + base64.b64encode(salt).decode() + "#" + base64.b64encode(_bin(v)).decode()


def _h_nn(a: int, b: int) -> int:
    return int.from_bytes(_h(_bin(a).rjust(N_LEN, b"\0"), _bin(b).rjust(N_LEN, b"\0")), "big")


class SrpClient:
    def __init__(self, name: str, password: str) -> None:
        self.name = name  # usr->username (Original-Schreibweise) für M
        self.password = password
        self.a = secrets.randbits(256)
        self.A = pow(G, self.a, N)

    def bytes_A(self) -> bytes:
        return _bin(self.A)

    def process(self, salt: bytes, bytes_B: bytes) -> bytes:
        B = int.from_bytes(bytes_B, "big")
        u = _h_nn(self.A, B)
        x = _x(salt, self.name, self.password)
        k = _h_nn(N, G)
        S = pow((B - k * pow(G, x, N)) % N, self.a + u * x, N)
        K = _h(_bin(S))
        h_n = _h(_bin(N))
        h_g = _h(_bin(G))
        h_xor = bytes(i ^ j for i, j in zip(h_n, h_g, strict=True))
        h_i = _h(self.name.encode("utf-8"))
        return _h(h_xor, h_i, salt, _bin(self.A), _bin(B), K)
