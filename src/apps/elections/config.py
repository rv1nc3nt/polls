# SPDX-License-Identifier: 0BSD
"""Screen 2's write path — configuration du scrutin (§6.5.2, R-3.3).

The configuration screen is the one place a poll's configuration is edited, and
R-3.3 makes that legal only while the poll is ``draft``: on the transition to
``open`` the configuration freezes (INV-6), and the sole change still permitted
is the reasoned ``closes_at`` extension of R-3.4 — which is
``transitions.extend_closes_at``, not this module.

``Poll.save()`` and a database trigger already refuse a frozen-field change out
of ``draft`` (§5.1). The check here is the one that produces a message a
council member can act on, and it runs before any write, so a refused edit
leaves nothing half-applied.

This module assigns every configuration field of §3.1 **except**: ``state``,
which only ``transitions`` assigns (§5.1); ``token_salt``, generated once and
never edited; and ``is_sandbox``, fixed at creation (R-3.7) and so assigned by
``create_poll`` below, not ``save_configuration``.

``create_poll`` is the write path behind the "Nouveau scrutin" screen
(access.require_commune_admin — see its docstring, "crée les scrutins"): a
poll's initial configuration is the same shape ``PollConfigForm`` already
validates for screen 2, so creation reuses it rather than a second form for
the same fields. It grants the creating admin no role on the poll it makes —
that would bypass the audited grant §3.7 requires for every poll-scoped
screen — so ``poll_create`` in ``views.py`` sends the admin back to "Rôles par
scrutin" to grant one, themselves or someone else, as a separate, logged step.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.audit.models import Action
from apps.core.models import User

from .models import Poll, PollOption, PollState, TallyMethod

#: The scalar configuration fields screen 2 edits, in display order.
#: ``title_i18n``/``description_i18n``, ``languages`` and the option list are
#: handled apart: their shape is not one form field.
SCALAR_FIELDS: tuple[str, ...] = (
    "opens_at",
    "closes_at",
    "paper_entry_deadline",
    "timezone",
    "tally_method",
    "tally_method_version",
    "require_complete_ranking",
    "allow_ties_in_ballot",
    "tiebreak_rule",
    "paper_requires_signed_form",
    "paper_requires_countersign",
    "paper_requires_reconciliation",
    "allow_ballot_modification",
    "eligible_list_types",
    "show_live_participation",
)


def configuration_warnings(tally_method: str, *, allow_ties_in_ballot: bool) -> list[str]:
    """Legal-but-almost-certainly-wrong configuration, as codes for screen 2 (§8.2).

    These do not block a save or the opening — the tally resolves every one of
    them deterministically — so they are not ``opening_blockers`` (§4). They are
    the combinations where the *intent* is in doubt, and §8.2 puts the warning
    on the configuration screen rather than letting the tally act on a choice
    the operator may not have realised they made.

    Today there is one: ``plurality`` with ``allow_ties_in_ballot`` set. A
    ballot whose first group holds several options then hands one count to each
    (§8.2), which is hardly ever what a single-choice question wants.
    """
    warnings: list[str] = []
    if tally_method == TallyMethod.PLURALITY and allow_ties_in_ballot:
        warnings.append("plurality_allows_ties")
    return warnings


@transaction.atomic
def create_poll(draft: ConfigDraft, *, is_sandbox: bool, actor: User) -> Poll:
    """Create a new poll from a screen-2-shaped draft (R-3.1) and log it.

    ``draft.options`` is never ``None`` here — unlike a screen-2 edit, creation
    always carries the whole proposition list, and ``OptionFormSet`` already
    refused fewer than two before this is called. ``is_sandbox`` is taken apart
    from the rest of ``draft.scalars``: R-3.7 fixes it at creation, so it has no
    place in the set ``save_configuration`` may later change.
    """
    poll = Poll(
        languages=draft.languages,
        title_i18n=draft.title_i18n,
        description_i18n=draft.description_i18n,
        is_sandbox=is_sandbox,
        **draft.scalars,
    )
    poll.save()
    for position, row in enumerate(draft.options or []):
        PollOption.objects.create(
            poll=poll, option_id=row.option_id, label_i18n=row.labels, position=position
        )
    audit.record(
        action=Action.POLL_CREATED,
        poll=poll,
        actor=actor,
        object_ref=audit.ref(poll),
    )
    return poll


class ConfigurationLocked(Exception):
    """Screen 2 was asked to write to a poll that has left ``draft`` (R-3.3)."""


@dataclass
class OptionDraft:
    """One row of the proposition editor.

    ``pk`` is the existing ``PollOption`` id where the row edits one and empty
    where it adds one. ``labels`` is ``{language: text}`` over the poll's
    enabled languages; a language left blank is a gap the dashboard names as an
    opening blocker (§3.8), not an error to raise here.
    """

    option_id: str
    labels: dict[str, str]
    pk: str = ""


@dataclass
class ConfigDraft:
    """The validated configuration a screen-2 POST carries, ready to apply.

    ``options`` is ``None`` when the caller is not touching the proposition
    list, and a list — necessarily the whole list — when it is.
    """

    scalars: dict[str, Any]
    languages: list[str]
    title_i18n: dict[str, str]
    description_i18n: dict[str, str]
    options: list[OptionDraft] | None = None


@transaction.atomic
def save_configuration(poll: Poll, draft: ConfigDraft, *, actor: User) -> Poll:
    """Apply a screen-2 edit in one transaction and log what changed.

    Refuses unless the poll is still ``draft`` (R-3.3), before any write. The
    audit event names the fields that moved and nothing else: poll
    configuration carries no elector identity, and the list is enough to say
    what was done (§10).
    """
    poll = Poll.objects.select_for_update().get(pk=poll.pk)
    if poll.state != PollState.DRAFT:
        raise ConfigurationLocked(
            _("La configuration est figée : le scrutin n'est plus en brouillon.")
        )

    changed = _apply(poll, draft)
    if changed:
        audit.record(
            action=Action.POLL_CONFIG_CHANGED,
            poll=poll,
            actor=actor,
            object_ref=audit.ref(poll),
            after={"changed": sorted(changed)},
        )
    return poll


def _apply(poll: Poll, draft: ConfigDraft) -> set[str]:
    changed: set[str] = set()

    for name in SCALAR_FIELDS:
        if name in draft.scalars and getattr(poll, name) != draft.scalars[name]:
            setattr(poll, name, draft.scalars[name])
            changed.add(name)

    if poll.languages != draft.languages:
        poll.languages = draft.languages
        changed.add("languages")
    if poll.title_i18n != draft.title_i18n:
        poll.title_i18n = draft.title_i18n
        changed.add("title_i18n")
    if poll.description_i18n != draft.description_i18n:
        poll.description_i18n = draft.description_i18n
        changed.add("description_i18n")

    # A full save, not ``update_fields``: ``Poll.save()`` carries the R-3.3
    # guard, which is a no-op here (the poll is ``draft``) but is the layer
    # that would catch a caller reaching this module in the wrong state.
    poll.save()

    if draft.options is not None and _apply_options(poll, draft.options):
        changed.add("options")
    return changed


def _apply_options(poll: Poll, options: list[OptionDraft]) -> bool:
    """Reconcile the poll's propositions with the editor's rows (§3.1).

    Row order is the option order: ``position`` follows the list index.
    A stored option whose id no longer appears is deleted — in ``draft`` no
    ballot references it yet, so the deletion is clean.
    """
    existing = {str(option.pk): option for option in poll.options.all()}
    kept: set[str] = set()
    dirty = False

    for position, row in enumerate(options):
        current = existing.get(row.pk) if row.pk else None
        if current is None:
            PollOption.objects.create(
                poll=poll,
                option_id=row.option_id,
                label_i18n=row.labels,
                position=position,
            )
            dirty = True
            continue
        kept.add(row.pk)
        if (
            current.option_id != row.option_id
            or current.label_i18n != row.labels
            or current.position != position
        ):
            current.option_id = row.option_id
            current.label_i18n = row.labels
            current.position = position
            current.save(update_fields=["option_id", "label_i18n", "position"])
            dirty = True

    stale = set(existing) - kept
    if stale:
        poll.options.filter(pk__in=stale).delete()
        dirty = True
    return dirty
