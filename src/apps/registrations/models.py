# SPDX-License-Identifier: 0BSD
"""``Registration`` (§3.3).

This module must never import ``apps.ballots`` and that module must never
import this one: INV-1 has no schema expression — the models simply share no
foreign key — so the enforcement is that a join has no natural place to be
written. ``tests/integration/test_inv1_separation.py`` asserts it over the model
metadata and over the import graph.

Voting status lives here, in ``channel``, and nowhere else (INV-5). Counting
ballots to discover whether someone has voted is not available and must not be
made available: for an online ballot no link to the voter exists.
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class RegistrationState(models.TextChoices):
    PENDING_EMAIL = "pending_email", _("en attente de confirmation")
    PENDING_REVIEW = "pending_review", _("en attente d'examen")
    ACTIVE = "active", _("active")
    REJECTED = "rejected", _("rejetée")


class Channel(models.TextChoices):
    """R-9.1. ``none`` until a ballot exists; one voter, one live ballot."""

    NONE = "none", _("aucun")
    ONLINE = "online", _("en ligne")
    PAPER = "paper", _("papier")


class Registration(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    poll = models.ForeignKey(
        "elections.Poll", on_delete=models.CASCADE, related_name="registrations"
    )

    # Identity, deleted by the retention job two months after closure (§11).
    nne = models.CharField(max_length=9)
    last_name = models.CharField(max_length=200)
    first_names = models.CharField(max_length=200)
    email = models.EmailField()
    email_canonical = models.EmailField(
        help_text=_("Adresse en minuscules, sans autre normalisation (§3.3).")
    )
    declared_on_honour = models.BooleanField(default=False)

    state = models.CharField(
        max_length=20, choices=RegistrationState.choices, default=RegistrationState.PENDING_EMAIL
    )
    # Prose written by an operator lives here, on the row the purge deletes —
    # never on an audit event, whose ``reason`` is a code (§10).
    review_reason = models.TextField(blank=True)

    # SHA256("voter" || poll.token_salt || token) (§7). The token itself is
    # never stored; losing it is unrecoverable by anyone, administrators
    # included (R-7.6).
    voter_hash = models.BinaryField(max_length=32, null=True, blank=True)

    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.NONE)
    language = models.CharField(max_length=10, default="fr")

    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    reminder_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("inscription")
        verbose_name_plural = _("inscriptions")
        constraints = [
            # INV-4 (R-5.9) and INV-10 (§6.2), as database constraints.
            models.UniqueConstraint(fields=["poll", "nne"], name="uniq_registration_poll_nne"),
            models.UniqueConstraint(
                fields=["poll", "email_canonical"], name="uniq_registration_poll_email"
            ),
        ]
        indexes = [
            models.Index(fields=["poll", "state"]),
            models.Index(fields=["poll", "voter_hash"]),
        ]

    def __str__(self) -> str:
        return f"{self.last_name} {self.first_names}"

    @property
    def has_voted(self) -> bool:
        """Turnout reads this, never a ballot count (INV-5)."""
        return self.channel != Channel.NONE


class DuplicateAttempt(models.Model):
    """A refused registration on an already-registered NNE (R-5.9).

    Flagged to the poll admin while the poll is open. It references the
    *existing* registration and records nothing about the attempter (§10): the
    flag is worthless after closure, so the identity dying with that row is the
    intended outcome.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    poll = models.ForeignKey(
        "elections.Poll", on_delete=models.CASCADE, related_name="duplicate_attempts"
    )
    existing_registration = models.ForeignKey(
        Registration, on_delete=models.CASCADE, related_name="duplicate_attempts"
    )
    at = models.DateTimeField(auto_now_add=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"doublon NNE sur {self.existing_registration_id}"
