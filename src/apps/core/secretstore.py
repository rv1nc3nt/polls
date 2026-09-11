# SPDX-License-Identifier: 0BSD
"""Reversible encryption for the few operational secrets the database has to
hold — the SMTP password of §6.5.12 today, nothing else so far.

Deliberately separate from ``crypto.py``: that module is §7's anonymity
scheme, one-way by design and "implemented exactly as specified" — mixing in
a *reversible* primitive there would blur a file that is meant to stay a
literal transcription of one section. A credential has to come back out in
plaintext to authenticate to a relay, which hashing cannot do; Fernet
(authenticated symmetric encryption, `cryptography`'s own recommended
building block) is the standard, unsurprising choice for that, in preference
to rolling anything out of ``hashlib``/``hmac``.

The key is derived from ``SECRET_KEY`` rather than stored separately: this is
deployment configuration already (§14 — rendered by Ansible, never in the
repository), rotating it is already a documented operational event, and a
second secret to provision would only be one more thing an adopting commune
can lose. It is run through SHA-256 with a fixed context label first, so this
key cannot collide with ``SECRET_KEY``'s other uses (session signing,
``ratelimit.py``'s address salting) even though the source material is
shared, and so that rotating ``SECRET_KEY`` has the honest consequence of
making every stored password unreadable — caught below as ``SecretUnreadable``
rather than surfacing as a confusing SMTP authentication failure.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

_CONTEXT = b"apps.core.secrets:mail-settings-password"


class SecretUnreadable(ValueError):
    """The stored ciphertext does not decrypt under the current SECRET_KEY —
    most likely SECRET_KEY was rotated since the value was saved."""


def _fernet() -> Fernet:
    key = hashlib.sha256(_CONTEXT + settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(plaintext: str) -> str:
    """Ciphertext as ASCII, safe to store in a ``TextField``."""
    return _fernet().encrypt(plaintext.encode()).decode("ascii")


def decrypt(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as bad:
        raise SecretUnreadable(
            "Stored secret does not decrypt under the current SECRET_KEY."
        ) from bad
