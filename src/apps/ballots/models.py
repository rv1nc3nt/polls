# SPDX-License-Identifier: 0BSD
"""``Ballot`` and ``PaperBallotLink`` (§3.4, §3.5).

``Ballot`` carries no voter, registration or roll-entry reference and must never
acquire one: adding one to satisfy INV-5 would destroy INV-1 (§5). It does not
import ``apps.registrations`` either. The only association that exists is
``PaperBallotLink``, deliberately (R-8.2 bis) — it points at the snapshot entry
the operator confirmed at keying — and the retention job deletes it.

Append-only. A modification inserts ``version + 1`` and marks the prior row
``superseded``; a trigger refuses every ``UPDATE`` on a row that is already
superseded or deleted (INV-3, T-24).

An elector who has already voted online cannot also be keyed a paper ballot:
``enter_paper`` refuses, per R-9.3, because §7 makes the online ballot
unlocatable from the registration, so a paper entry could neither replace it nor
be counted beside it without double-counting the voter — see
``docs/specification-decision-log.md`` #5 for why the requirements were amended to this
flat refusal rather than the reasoned override R-9.3 first called for.
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class BallotSource(models.TextChoices):
    """The channel a ballot came in by. Decides its window (INV-2:
    ``closes_at`` for online, ``paper_entry_deadline`` for paper) and whether
    a ``PaperBallotLink`` exists."""

    ONLINE = "online", _("en ligne")
    PAPER = "paper", _("papier")


class BallotStatus(models.TextChoices):
    """A ballot version's status (§3.4), written only by ``services``:

    * online: created ``live``; a modification marks it ``superseded`` and
      inserts the next version ``live``;
    * paper: created ``pending_countersign`` where the poll requires a
      countersignature, else ``live``; ``countersign`` takes it to ``live``;
      a correction supersedes it with a new version (back to
      ``pending_countersign`` where countersignature is required); a deletion
      marks it ``deleted``.

    ``superseded`` and ``deleted`` are terminal (INV-3 trigger). Only ``live``
    is tallied, hashed and published.
    """

    LIVE = "live", _("courant")
    SUPERSEDED = "superseded", _("remplacé")
    DELETED = "deleted", _("supprimé")
    PENDING_COUNTERSIGN = "pending_countersign", _("en attente de contreseing")


class LiveBallotManager(models.Manager["Ballot"]):
    """The live set, and nothing else.

    §3.4: what the tally counts, what the closure hash covers and what is
    published are exactly the rows with ``status = live``. Having one manager
    say so is what keeps the three in step.
    """

    def get_queryset(self) -> models.QuerySet[Ballot]:
        return super().get_queryset().filter(status=BallotStatus.LIVE)


class Ballot(models.Model):
    """One version of one ballot. A chain of versions shares a
    ``tracking_code``; at most one of them is in force (``live`` or
    ``pending_countersign``). Anonymous by construction: see the module
    docstring for what must never be added here.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    poll = models.ForeignKey("elections.Poll", on_delete=models.CASCADE, related_name="ballots")

    # SHA256("ballot" || poll.token_salt || token) (§7). Null for paper
    # ballots, which are reached through PaperBallotLink, and null for every
    # ballot of a poll with allow_ballot_modification off — where nothing
    # whatever connects a cast ballot to the token that cast it (T-48).
    ballot_hash = models.BinaryField(max_length=32, null=True, blank=True)

    # Issued at cast, never at registration (§6.2), and stable across versions
    # of the same ballot.
    tracking_code = models.CharField(max_length=10)
    version = models.PositiveIntegerField(default=1)

    # Ordered list of groups of option ids; a strict ranking is a list of
    # one-element groups. Ids only — never labels (§3.8).
    ranking = models.JSONField(default=list)

    source = models.CharField(max_length=10, choices=BallotSource.choices)
    status = models.CharField(
        max_length=20, choices=BallotStatus.choices, default=BallotStatus.LIVE
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = models.Manager()
    live = LiveBallotManager()

    class Meta:
        verbose_name = _("bulletin")
        verbose_name_plural = _("bulletins")
        constraints = [
            # INV-11: the canonical serialisation sorts on the tracking code and
            # the published CSV is keyed on it, so a collision would make the
            # closure hash ambiguous. A modification keeps the code across
            # versions (R-7.2), so the uniqueness is over the *current* row of a
            # chain — every status but ``superseded``: at any instant that is
            # exactly one row per code (one live or pending, or a terminal
            # deleted, plus a not-in-force collision record on its own code).
            models.UniqueConstraint(
                fields=["poll", "tracking_code"],
                condition=~models.Q(status="superseded"),
                name="uniq_ballot_poll_tracking_code",
            ),
            models.UniqueConstraint(
                fields=["poll", "tracking_code", "version"], name="uniq_ballot_version"
            ),
        ]
        indexes = [
            models.Index(fields=["poll", "status"]),
            models.Index(fields=["poll", "ballot_hash"]),
        ]

    def __str__(self) -> str:
        return f"{self.tracking_code} v{self.version}"


class PaperBallotLink(models.Model):
    """Paper ballots stay linked to the voter, deliberately (R-8.2 bis).

    Traceability and deletion-on-request require it. Deleted at retention
    (R-13.3), which is what anonymises the paper channel in the end.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    poll = models.ForeignKey("elections.Poll", on_delete=models.CASCADE, related_name="paper_links")
    ballot = models.OneToOneField(Ballot, on_delete=models.CASCADE, related_name="paper_link")
    # The snapshot entry the operator confirmed at entry (§3.5, §6.4). SET_NULL
    # because the retention purge deletes the roll snapshot and a paper link
    # must not be cascaded away before its own scheduled deletion.
    roll_entry = models.ForeignKey(
        "elections.RollEntry",
        on_delete=models.SET_NULL,
        related_name="paper_links",
        null=True,
        blank=True,
    )
    operator = models.ForeignKey(
        "core.User", on_delete=models.PROTECT, related_name="keyed_ballots"
    )
    countersigned_by = models.ForeignKey(
        "core.User",
        on_delete=models.PROTECT,
        related_name="countersigned_ballots",
        null=True,
        blank=True,
    )
    # Operator prose about this entry — the collision-override circumstances
    # (R-9.3), a keying-error note (R-8.5). It lives here, on the row the
    # retention purge deletes, never on an audit event whose ``reason`` is a
    # code (§10).
    note = models.TextField(blank=True)
    # The language the operator keyed in; the receipt (R-8.4) is rendered in it,
    # falling back to the poll default (§3.8).
    language = models.CharField(max_length=10, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["poll", "roll_entry"])]

    def __str__(self) -> str:
        return f"bulletin papier {self.ballot_id}"


class ReconciliationRecord(models.Model):
    """The formal reconciliation of R-8.6, where ``Poll.paper_requires_reconciliation``
    is set.

    One per poll: the paper forms retained by the commune, counted by an
    operator and checked against the paper ballots the system actually holds
    at that moment — exactly the set the tally and the closure hash will count
    (§3.4), frozen here rather than recomputed later for the same reason
    ``Poll.frozen_counts`` is (§9). Signed by a named operator and kept here
    rather than folded into the audit log, whose ``reason`` may hold no prose
    (§10) — a discrepancy note is exactly the kind of thing that belongs on a
    referenced row, not on an event. ``apps.elections.transitions`` refuses
    ``close_poll`` until this row exists wherever the flag is set; R-8.6 offers
    no override for a missing one, unlike R-8.7 bis's countersignature guard.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    poll = models.OneToOneField(
        "elections.Poll", on_delete=models.CASCADE, related_name="reconciliation_record"
    )
    forms_retained_count = models.PositiveIntegerField()
    # The live paper ballots recorded at the instant of signing (§3.4) — an
    # operator has no other way to know this number is right, so it is
    # computed, never entered.
    recorded_ballots_count = models.PositiveIntegerField()
    note = models.TextField(blank=True)
    signed_by = models.ForeignKey(
        "core.User", on_delete=models.PROTECT, related_name="signed_reconciliations"
    )
    signed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("procès-verbal de rapprochement")
        verbose_name_plural = _("procès-verbaux de rapprochement")

    def __str__(self) -> str:
        return f"rapprochement {self.poll_id}"

    @property
    def discrepancy(self) -> int:
        """Forms counted minus ballots recorded; negative means more ballots
        than forms."""
        return self.forms_retained_count - self.recorded_ballots_count
