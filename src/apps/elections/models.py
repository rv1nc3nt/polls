# SPDX-License-Identifier: 0BSD
"""``Poll``, its options and the frozen roll snapshot (§3.1, §3.2).

Note what is absent and must stay absent: nothing here links a ballot to a
voter, and ``RollEntry`` is reachable from ``Registration`` only (INV-1, INV-5).
"""

from __future__ import annotations

import uuid
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.crypto import new_token_salt


class PollState(models.TextChoices):
    DRAFT = "draft", _("brouillon")
    OPEN = "open", _("ouvert")
    CLOSED = "closed", _("clos")
    PUBLISHED = "published", _("publié")


class ListType(models.TextChoices):
    """The electoral-list types an elector may appear on (R-4.7).

    An elector on the European complementary list only has no standing on a
    municipal question; ``Poll.eligible_list_types`` is what each poll accepts.
    """

    PRINCIPALE = "principale", _("liste principale")
    COMPLEMENTAIRE_MUNICIPALE = "complementaire_municipale", _("liste complémentaire municipale")
    COMPLEMENTAIRE_EUROPEENNE = "complementaire_europeenne", _("liste complémentaire européenne")


def default_eligible_list_types() -> list[str]:
    """A municipal question takes the main list and the municipal complement
    (R-4.7, §3.1). Deferred configuration (§13): a callable, not a constant."""
    return [ListType.PRINCIPALE, ListType.COMPLEMENTAIRE_MUNICIPALE]


class TallyMethod(models.TextChoices):
    SCHULZE = "schulze", _("Schulze")
    PLURALITY = "plurality", _("majoritaire")
    APPROVAL = "approval", _("par assentiment")


class TiebreakRule(models.TextChoices):
    COMPUTED = "computed", _("tirage au sort calculé")
    PHYSICAL = "physical", _("tirage au sort physique")


#: Configuration fields frozen once the poll leaves ``draft`` (INV-6, R-3.3).
#: ``closes_at`` and ``paper_entry_deadline`` are absent: they move together
#: through the reasoned extension action of R-3.4. ``state``, ``opening_seed``
#: and ``closure_hash`` are lifecycle fields, not configuration.
FROZEN_CONFIG_FIELDS: frozenset[str] = frozenset(
    {
        "title_i18n",
        "description_i18n",
        "opens_at",
        "tally_method",
        "tally_method_version",
        "require_complete_ranking",
        "allow_ties_in_ballot",
        "tiebreak_rule",
        "token_salt",
        "paper_requires_signed_form",
        "paper_requires_countersign",
        "paper_requires_reconciliation",
        "allow_ballot_modification",
        "eligible_list_types",
        "languages",
        "show_live_participation",
        "is_sandbox",
        "timezone",
    }
)


class Poll(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # §3.8: poll content is per-poll data, stored as {language_code: text}.
    # The first entry of ``languages`` is the default and the fallback.
    title_i18n = models.JSONField(_("titre"), default=dict)
    description_i18n = models.JSONField(_("description"), default=dict)
    languages = models.JSONField(default=list)

    opens_at = models.DateTimeField(_("ouverture"))
    closes_at = models.DateTimeField(_("clôture"))
    paper_entry_deadline = models.DateTimeField(
        _("fin de saisie des bulletins papier"),
        help_text=_("≥ clôture ; par défaut égale à elle (§6.4)."),
    )
    timezone = models.CharField(max_length=64, default="Europe/Paris")

    tally_method = models.CharField(
        max_length=20, choices=TallyMethod.choices, default=TallyMethod.SCHULZE
    )
    tally_method_version = models.CharField(max_length=20, default="1")
    require_complete_ranking = models.BooleanField(default=True)
    allow_ties_in_ballot = models.BooleanField(default=False)
    tiebreak_rule = models.CharField(
        max_length=20, choices=TiebreakRule.choices, default=TiebreakRule.COMPUTED
    )

    opening_seed = models.BinaryField(max_length=32, null=True, blank=True)
    # Never published, never logged, and in the backups — which is why backup
    # permissions are part of the ballot-secrecy boundary (§14, §15).
    token_salt = models.BinaryField(max_length=32, default=new_token_salt)

    paper_requires_signed_form = models.BooleanField(default=False)
    paper_requires_countersign = models.BooleanField(default=False)
    paper_requires_reconciliation = models.BooleanField(default=False)
    allow_ballot_modification = models.BooleanField(default=True)
    # R-4.7: the electoral-list types conferring the right to register and vote
    # in this poll. Frozen configuration (INV-6); a list of ``ListType`` values.
    eligible_list_types = models.JSONField(default=default_eligible_list_types)
    show_live_participation = models.BooleanField(default=False)
    is_sandbox = models.BooleanField(default=False)

    state = models.CharField(max_length=20, choices=PollState.choices, default=PollState.DRAFT)
    closure_hash = models.BinaryField(max_length=32, null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    # §9: frozen on entry to ``closed`` and never re-derived, since the
    # registrations they count are deleted by the retention job (§11).
    frozen_counts = models.JSONField(default=dict, blank=True)
    closure_override_reason = models.CharField(max_length=100, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("scrutin")
        verbose_name_plural = _("scrutins")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(closes_at__gt=models.F("opens_at")),
                name="poll_closes_after_opens",
            ),
            models.CheckConstraint(
                condition=models.Q(paper_entry_deadline__gte=models.F("closes_at")),
                name="poll_paper_deadline_after_closes",
            ),
        ]

    def __str__(self) -> str:
        return self.title() or str(self.id)

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Configuration immutability (R-3.3, INV-6), enforced in the model.

        Backed by a database trigger, since ``save()`` is bypassed by
        ``update()``, ``bulk_update()`` and raw SQL (§5.1). This check is the
        one that produces a decent error message; the trigger is the one that
        actually holds.
        """
        if not self._state.adding:
            previous = Poll.objects.filter(pk=self.pk).first()
            if previous is not None and previous.state != PollState.DRAFT:
                changed = [
                    field
                    for field in FROZEN_CONFIG_FIELDS
                    if getattr(previous, field) != getattr(self, field)
                ]
                if changed:
                    raise ValidationError(
                        _("Configuration figée hors brouillon : %(fields)s")
                        % {"fields": ", ".join(sorted(changed))}
                    )
        super().save(*args, **kwargs)

    @property
    def default_language(self) -> str:
        """First enabled language (§3.8); French unless configured otherwise."""
        return self.languages[0] if self.languages else "fr"

    def title(self, language: str | None = None) -> str:
        return self.translate(self.title_i18n, language)

    def description(self, language: str | None = None) -> str:
        return self.translate(self.description_i18n, language)

    def translate(self, mapping: dict[str, str], language: str | None = None) -> str:
        """A missing translation falls back to the default language, never to
        the empty string (§3.8, T-46)."""
        if language and mapping.get(language):
            return mapping[language]
        return mapping.get(self.default_language, "")

    def missing_translations(self) -> list[str]:
        """Gaps that stop the poll leaving ``draft`` (§3.8, T-22, T-53).

        Named on the dashboard while the poll is still in ``draft`` rather than
        discovered by ``open_poll`` at an hour when nobody is watching (§4).
        """
        gaps: list[str] = []
        for language in self.languages:
            if not self.title_i18n.get(language):
                gaps.append(f"title:{language}")
            if not self.description_i18n.get(language):
                gaps.append(f"description:{language}")
        for option in self.options.all():
            for language in self.languages:
                if not option.label_i18n.get(language):
                    gaps.append(f"option:{option.option_id}:{language}")
        return gaps


class PollOption(models.Model):
    """One proposition. ``option_id`` is what rankings, hashes and the published
    CSV carry; labels are a lookup table beside them (§3.8), so correcting a
    translation after publication moves neither the hash nor the result (T-23).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name="options")
    option_id = models.SlugField(max_length=50)
    label_i18n = models.JSONField(default=dict)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "option_id"]
        constraints = [
            models.UniqueConstraint(fields=["poll", "option_id"], name="uniq_poll_option_id")
        ]

    def __str__(self) -> str:
        return self.label()

    def label(self, language: str | None = None) -> str:
        return self.poll.translate(self.label_i18n, language)


class RollEntryFields(models.Model):
    """The fields R-4.2 imports, shared by the working roll and the snapshot.

    Identity is stored **in clear, not hashed** (R-4.4): the review queue
    (§6.2), the operator search at paper entry (R-8.3) and R-4.4's auditor
    access all read it. The retention purge (§11) is what bounds the exposure.
    """

    birth_name = models.CharField(_("nom de naissance"), max_length=200)
    # Often blank (R-5.3); a married name, say. A registration match tries the
    # declared surname against both this and ``birth_name``.
    usual_name = models.CharField(_("nom d'usage"), max_length=200, blank=True)
    first_names = models.CharField(_("prénoms"), max_length=200)
    # Kept verbatim as the export gave it (R-4.9). ``date_of_birth_parsed`` is
    # the value §6.1 derives and is null exactly when ``date_uncertain`` is set;
    # an uncertain entry never matches a registration automatically.
    date_of_birth = models.CharField(_("date de naissance"), max_length=40, blank=True)
    date_of_birth_parsed = models.DateField(null=True, blank=True)
    date_uncertain = models.BooleanField(default=False)
    # The set of electoral-list types this elector appears on (R-4.6, R-4.7):
    # one entry per elector, not one per list. A list of ``ListType`` values.
    list_types = models.JSONField(default=list)

    class Meta:
        abstract = True

    def __str__(self) -> str:
        return f"{self.birth_name} {self.first_names}"


class RollEntry(RollEntryFields):
    """The frozen snapshot taken at ``draft → open`` (§3.2, R-4.3).

    Immutable thereafter: INV-7's trigger refuses every ``UPDATE`` outright and
    permits ``DELETE`` only once the poll is ``closed`` or ``published``, which
    is the retention purge (§11) — anchored on closure, so a poll that never
    publishes still purges. A snapshot is frozen, not immortal.

    There is **no natural unique key** (R-4.8): the roll's order number is
    neither unique nor stable, and there is no national identifier. Apparent
    duplicates that survive import are separated, if at all, by a human in the
    review queue (§6.2), not by a constraint.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name="roll_entries")

    class Meta:
        verbose_name = _("électeur inscrit")
        verbose_name_plural = _("liste électorale figée")
        indexes = [models.Index(fields=["poll", "birth_name"])]


class WorkingRollEntry(RollEntryFields):
    """The current roll, as imported (§6.1).

    Distinct from ``RollEntry``: a new import replaces this table entirely and
    does not touch the snapshot of an already-open poll (T-26). Commune-wide,
    not poll-scoped (§3.2).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    imported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["birth_name"])]


class RollImport(models.Model):
    """Provenance of each import: filename, SHA-256, row count, operator (§6.1)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    filename = models.CharField(max_length=255)
    file_sha256 = models.BinaryField(max_length=32)
    row_count = models.PositiveIntegerField()
    imported_by = models.ForeignKey("core.User", on_delete=models.PROTECT)
    imported_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.filename} ({self.row_count})"
