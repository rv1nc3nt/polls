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
    """``draft → [announced] → open → closed → published`` (R-3.2).

    ``announced`` is an optional waypoint, not a required one (R-3.10): a poll
    may go straight ``draft → open`` as before, or pause at ``announced`` —
    publicly visible, configuration already frozen (INV-6 already reads
    ``state != draft``, so this falls out of the existing rule without a
    change to it) — for as long as the poll admin likes before opening it.

    ``withdrawn`` is a fifth, terminal state, reachable only from
    ``announced``, ``open``, ``closed`` or ``published`` (R-3.11) — never from
    ``draft``, which has ``delete`` for that. No transition leaves it, same as
    ``published``.
    """

    DRAFT = "draft", _("brouillon")
    ANNOUNCED = "announced", _("annoncé")
    OPEN = "open", _("ouvert")
    CLOSED = "closed", _("clos")
    PUBLISHED = "published", _("publié")
    WITHDRAWN = "withdrawn", _("retiré")


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
    # R-3.11: set once, on withdrawal. The retention anchor of R-13.3 for a
    # poll withdrawn before ever reaching ``closed`` — see ``retention.py``.
    withdrawn_at = models.DateTimeField(null=True, blank=True)

    # §9: frozen on entry to ``closed`` and never re-derived, since the
    # registrations they count are deleted by the retention job (§11).
    frozen_counts = models.JSONField(default=dict, blank=True)
    closure_override_reason = models.CharField(max_length=100, blank=True)
    # §8.3: where the tally reports a tie and ``tiebreak_rule`` is ``physical``,
    # the poll admin enters the outcome of the physical draw on screen 9 and it
    # is logged. An ordering of the tied option ids; empty until entered. A
    # lifecycle field, not configuration — set once, after closure.
    physical_tiebreak_order = models.JSONField(default=list, blank=True)

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

    def display_title(self, language: str | None = None) -> str:
        """``title()``, with a placeholder where that would be empty.

        R-3.6 lets a poll sit in ``draft`` with no title yet: it is entered
        after creation, and neither ``announce_poll`` nor ``open_poll`` lets
        the poll leave ``draft`` with the gap still open (``missing_translations``,
        R-3.10, §3.8). The back-office screens that list every poll an
        operator holds a role on (the landing page, the breadcrumb, "Rôles par
        scrutin") name the poll by this, not ``title()``, since those lists
        include ``draft`` polls: an untitled poll rendered as an ``<a>`` with
        no text is present in the markup but invisible and unclickable in the
        browser — indistinguishable from not being listed at all.
        """
        return self.title(language) or str(_("(scrutin sans titre)"))

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
    CSV carry; labels are a lookup table beside them (§3.8), so the hash and the
    result are independent of the labels (R-10.7, T-23). Labels are frozen with
    the rest of the configuration when the poll opens (R-3.3, INV-6): the
    ``inv6_option_*_frozen`` triggers refuse every write outside ``draft``.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name="options")
    option_id = models.SlugField(max_length=50)
    label_i18n = models.JSONField(default=dict)
    # R-3.12, §3.1 bis: an optional enrichment on top of the label above, never
    # a translation gate the way title/description/label are (§3.8) — a
    # language missing this shows the poll's default-language text instead,
    # or nothing where that is absent too (Poll.translate). Raw Markdown;
    # apps.elections.optioncontent renders it to sanitised HTML at *display*
    # time, never at save time, so a fix to that pipeline reaches every poll's
    # content immediately, past and present. Sits on this same row, so it is
    # already covered by the ``inv6_option_*_frozen`` triggers below — no
    # trigger change needed for this field, only for ``OptionImage``.
    details_i18n = models.JSONField(default=dict, blank=True)
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

    def details(self, language: str | None = None) -> str:
        return self.poll.translate(self.details_i18n, language)


def _option_image_extension(content_type: str) -> str:
    return {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
    }[content_type]


def option_image_path(instance: OptionImage, filename: str) -> str:
    """Content-addressed (R-3.12, §3.1 bis): named after the SHA-256 digest of
    the bytes themselves, not the upload's own filename, so a re-upload of
    edited content can never land at the path a frozen ``details_i18n``
    reference already points to — it gets a new digest, a new path and a new
    row instead (apps.elections.optionimages).

    ``instance.option_id`` here is the ``option`` foreign key's own
    Django-generated attribute — the referenced ``PollOption``'s primary key
    — not that unrelated model's own ``option_id`` slug field, which is
    unique only within its poll and would collide across polls.
    """
    ext = _option_image_extension(instance.content_type)
    return f"option-images/{instance.option_id}/{instance.content_hash}{ext}"


class OptionImage(models.Model):
    """An image usable from one option's extended description (R-3.12).

    Frozen alongside its option once the poll leaves ``draft``, for the same
    reason as the option itself (INV-6, §5.1): the ``inv6_optionimage_*_frozen``
    triggers of migration 0008 refuse every write once the owning poll is not
    ``draft``, since a new or changed image after freeze would let a public
    page change under a viewer's eyes exactly as an edited label would (R-3.3,
    R-3.10). Re-uploading identical bytes is a no-op at the service layer
    (``apps.elections.optionimages.add_option_image``), and the unique
    constraint below is the layer under that.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    option = models.ForeignKey(PollOption, on_delete=models.CASCADE, related_name="images")
    file = models.FileField(upload_to=option_image_path)
    #: A sniffed MIME type — ``image/png`` and friends — never the upload's own
    #: claim, checked before this row exists (§14, the same reasoning §6.1
    #: gives for not trusting a CSV's declared encoding).
    content_type = models.CharField(max_length=40)
    content_hash = models.CharField(max_length=64)
    alt_text = models.CharField(_("texte alternatif"), max_length=300, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["uploaded_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["option", "content_hash"], name="uniq_option_image_content"
            )
        ]

    def __str__(self) -> str:
        return f"{self.option_id}:{self.content_hash[:8]}"


class PollTemplate(models.Model):
    """A named, reusable set of tally and ballot rules (R-3.6, R-3.9, §3.9).

    Deliberately not a ``Poll`` with fields nulled out: it carries only the
    tally mechanism and the ballot rules built around it — never a title, a
    description, options or any date. Duplicating those belongs to
    duplicating an existing poll directly (R-3.6), a separate and still-unbuilt
    path (docs/spec-divergences.md #10). Commune-level, one catalogue rather
    than one per poll, like ``MailSettings`` — but many rows, not one, so
    there is no ``pk=1`` singleton constraint here.

    ``apps.elections.polltemplates`` is the one writer: ``save_as_template``
    creates a row from a poll's current configuration (any state — none of
    these fields change after ``draft``, INV-6), and screen 13 renames or
    deletes one. Nothing edits the mechanism fields of a template once saved;
    there being no live poll behind it, there is no "screen 2" for a template
    to have.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_("nom"), max_length=200, unique=True)

    tally_method = models.CharField(
        max_length=20, choices=TallyMethod.choices, default=TallyMethod.SCHULZE
    )
    tally_method_version = models.CharField(max_length=20, default="1")
    require_complete_ranking = models.BooleanField(default=True)
    allow_ties_in_ballot = models.BooleanField(default=False)
    tiebreak_rule = models.CharField(
        max_length=20, choices=TiebreakRule.choices, default=TiebreakRule.COMPUTED
    )
    paper_requires_signed_form = models.BooleanField(default=False)
    paper_requires_countersign = models.BooleanField(default=False)
    paper_requires_reconciliation = models.BooleanField(default=False)
    allow_ballot_modification = models.BooleanField(default=True)
    eligible_list_types = models.JSONField(default=default_eligible_list_types)
    languages = models.JSONField(default=list)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        "core.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="poll_templates",
    )

    class Meta:
        verbose_name = _("modèle de scrutin")
        verbose_name_plural = _("modèles de scrutin")
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


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
