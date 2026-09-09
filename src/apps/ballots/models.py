# SPDX-License-Identifier: 0BSD
"""``Ballot`` and ``PaperBallotLink`` (§3.4, §3.5).

``Ballot`` carries no voter, registration or roll-entry reference and must never
acquire one: adding one to satisfy INV-5 would destroy INV-1 (§5). It does not
import ``apps.registrations`` either. The only association that exists is
``PaperBallotLink``, deliberately (R-8.2 bis) — it points at the snapshot entry
the operator confirmed at keying — and the retention job deletes it.

Append-only. A modification inserts ``version + 1`` and marks the prior row
``superseded``; a trigger refuses every ``UPDATE`` on a row that is already
superseded, deleted or not-in-force (INV-3, T-24).

``not_in_force_collision`` is the one status that is not part of a version
chain: a paper ballot keyed under the R-9.3 override for an elector who has
already voted online is recorded — with its ``PaperBallotLink`` for
traceability — but never counted, because §7 makes the online ballot
unlocatable from the registration and so it cannot be superseded. Such a row is
``version = 1`` with nothing above it, and it is immutable from birth.
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class BallotSource(models.TextChoices):
    ONLINE = "online", _("en ligne")
    PAPER = "paper", _("papier")


class BallotStatus(models.TextChoices):
    LIVE = "live", _("courant")
    SUPERSEDED = "superseded", _("remplacé")
    DELETED = "deleted", _("supprimé")
    PENDING_COUNTERSIGN = "pending_countersign", _("en attente de contreseing")
    # R-9.3 override: a paper entry for an elector who already voted online.
    # Recorded, linked, never counted; the online ballot stands (§6.4, D4).
    NOT_IN_FORCE_COLLISION = (
        "not_in_force_collision",
        _("non retenu : vote en ligne déjà enregistré"),
    )


class LiveBallotManager(models.Manager["Ballot"]):
    """The live set, and nothing else.

    §3.4: what the tally counts, what the closure hash covers and what is
    published are exactly the rows with ``status = live``. Having one manager
    say so is what keeps the three in step.
    """

    def get_queryset(self) -> models.QuerySet[Ballot]:
        return super().get_queryset().filter(status=BallotStatus.LIVE)


class Ballot(models.Model):
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
        max_length=24, choices=BallotStatus.choices, default=BallotStatus.LIVE
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
