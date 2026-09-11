# SPDX-License-Identifier: 0BSD
"""``apps.core.secretstore`` — reversible encryption for the SMTP password of
screen 12 (§6.5.12). Pure and DB-free, like the rest of ``tests/unit``.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.core.secretstore import SecretUnreadable, decrypt, encrypt


def test_round_trip() -> None:
    ciphertext = encrypt("un-mot-de-passe-secret")
    assert ciphertext != "un-mot-de-passe-secret"
    assert decrypt(ciphertext) == "un-mot-de-passe-secret"


def test_two_encryptions_of_the_same_secret_differ() -> None:
    """Fernet includes a fresh nonce and timestamp each call; two ciphertexts
    of the same plaintext must not be comparable to each other or to the
    plaintext by inspecting the stored column."""
    assert encrypt("même secret") != encrypt("même secret")


def test_a_secret_key_rotation_makes_the_stored_value_unreadable() -> None:
    """Rotating SECRET_KEY (§14, a documented operational event) has the
    honest consequence of losing the password rather than silently deriving
    a wrong one — caught here, not surfacing as a confusing SMTP auth error."""
    ciphertext = encrypt("un-mot-de-passe-secret")
    with patch("django.conf.settings.SECRET_KEY", "une-autre-cle"):
        with pytest.raises(SecretUnreadable):
            decrypt(ciphertext)
