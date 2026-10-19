"""SRP-Verifier nach Luanti 5.17.0: Golden Vector aus dem Live-Spike (03-RESEARCH.md Pattern 2)."""

from __future__ import annotations

import base64
import re

from gameworld.provisioner.luanti_auth import G, N, make_verifier

# Wörtlich aus 03-RESEARCH.md Pattern 2; Luanti 5.17.0 hat ihn per echtem SRP-Login akzeptiert.
GOLDEN = "#1#AAECAwQFBgcICQoLDA0ODw==#pCyNep+1Ug3he9xjpqMCK1MBx7OOe2SLVkX1lvyHmIf8bATbrA6zgiJ/+xEmx+MaV+IllHKn1rqJHViRuv9ysMGPSDxm5xWmTyhasxEQtfWJI1EiyABU/v15UncRaqWEr+OvrPXxcsb3QCsQrZ8cYd1vgRaJByW7QmW75Le8VriHfR+/xNSE2hHnmFd60n0eOlufj7UBtmfTmFOIO/uHbnvA74UHr3LnoeimBaOXvo4OR9NorNAjcVYraZ0i9HvO98VoRCKxvFsYXrbnfHJGE+3VWpsAPqmcGXzfFTkrzrfPY78b7lOjUMReiUf2zchmlwcNc12S46iQOEHkiFsdhw=="  # noqa: E501
VERIFIER_FORM = re.compile(r"^#1#[A-Za-z0-9+/=]+#[A-Za-z0-9+/=]+$")
SALT = bytes(range(16))


def test_golden_vector_from_live_spike() -> None:
    assert make_verifier("Mia", "Sonne-Baum-42", SALT) == GOLDEN


def test_name_is_case_insensitive() -> None:
    assert make_verifier("mia", "Sonne-Baum-42", SALT) == make_verifier("Mia", "Sonne-Baum-42", SALT)


def test_other_name_gives_other_verifier() -> None:
    assert make_verifier("Leo", "Sonne-Baum-42", SALT) != GOLDEN


def test_random_salt_differs_and_has_luanti_form() -> None:
    first = make_verifier("Mia", "Sonne-Baum-42")
    second = make_verifier("Mia", "Sonne-Baum-42")
    assert first != second
    for verifier in (first, second):
        assert VERIFIER_FORM.fullmatch(verifier)
        salt = base64.b64decode(verifier.split("#")[2])
        assert len(salt) == 16


def test_group_constants() -> None:
    assert G == 2
    assert N.bit_length() == 2048
