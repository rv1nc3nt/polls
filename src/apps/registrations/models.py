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

    # The snapshot entry this registration is bound to (§3.3, R-5.9). Set when a
    # single unambiguous match is found (→ ``pending_email``) or when a poll
    # admin resolves a review; null while ``pending_review`` is unresolved and
    # for ``rejected``. ``SET_NULL`` because the retention purge deletes the
    # roll snapshot and a registration must never be cascaded away with it.
    roll_entry = models.ForeignKey(
        "elections.RollEntry",
        on_delete=models.SET_NULL,
        related_name="registrations",
        null=True,
        blank=True,
    )

    # What the person typed, kept for the review queue and deleted by the
    # retention job two months after closure (§11). Not the roll's own values —
    # the match against the roll is via ``roll_entry``.
    declared_last_name = models.CharField(max_length=200)
    declared_first_names = models.CharField(max_length=200)
    declared_dob = models.CharField(max_length=40, blank=True)
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
            # INV-4 (R-5.9): one roll entry, one registration per poll — a
            # partial constraint over the rows that are actually bound and not
            # rejected, so it does not touch the still-unbound ``pending_review``
            # rows. INV-10 (§6.2) is the address one.
            models.UniqueConstraint(
                fields=["poll", "roll_entry"],
                condition=models.Q(roll_entry__isnull=False)
                & ~models.Q(state=RegistrationState.REJECTED),
                name="uniq_registration_poll_roll_entry",
            ),
            models.UniqueConstraint(
                fields=["poll", "email_canonical"], name="uniq_registration_poll_email"
            ),
        ]
        indexes = [
            models.Index(fields=["poll", "state"]),
            models.Index(fields=["poll", "voter_hash"]),
        ]

    def __str__(self) -> str:
        return f"{self.declared_last_name} {self.declared_first_names}"

    @property
    def has_voted(self) -> bool:
        """Turnout reads this, never a ballot count (INV-5)."""
        return self.channel != Channel.NONE


class DuplicateAttempt(models.Model):
    """A refused registration against an already-registered roll entry (R-5.9).

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
        return f"tentative de doublon sur {self.existing_registration_id}"
