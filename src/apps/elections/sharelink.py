# SPDX-License-Identifier: 0BSD
"""The unguessable share link of a poll (R-3.10 bis, R-3.7).

One link, two uses: the preview of a ``draft`` (any poll) and the way into a
sandbox poll in every state. It is generated, regenerated or revoked by the
poll admin, needs no reason, and is never written to the audit log — only the
fact that it changed (INV-3, §10).
"""

from __future__ import annotations

from apps.audit import services as audit
from apps.audit.models import Action
from apps.core.crypto import new_token
from apps.core.models import User

from .models import Poll


def generate(poll: Poll, *, actor: User) -> None:
    """Replace the link with a fresh one; the previous one stops working at once.

    ``.reveal()``: ``preview_token`` is a plain, persisted CharField, not a §7
    voter token — holding the redacting ``Token`` wrapper would only make
    ``poll.preview_token`` awkward to use.
    """
    poll.preview_token = new_token().reveal()
    poll.save(update_fields=["preview_token"])
    audit.record(
        action=Action.PREVIEW_LINK_GENERATED,
        poll=poll,
        actor=actor,
        object_ref=audit.ref(poll),
    )


def revoke(poll: Poll, *, actor: User) -> None:
    """Remove the link. Browsers admitted through it lose access to a sandbox
    poll at once (``sandbox.link_granted`` compares against the current value)."""
    poll.preview_token = ""
    poll.save(update_fields=["preview_token"])
    audit.record(
        action=Action.PREVIEW_LINK_REVOKED,
        poll=poll,
        actor=actor,
        object_ref=audit.ref(poll),
    )
