# SPDX-License-Identifier: 0BSD
"""Named poll templates — the mechanism half of R-3.6, and R-3.9's reverse
direction (§3.9; screens 2 and 13, §6.5.2, §6.5.13).

A template carries only the tally mechanism and the ballot rules built around
it — never a title, a description, options or any date, which belong to
duplicating an existing poll directly (R-3.6), a separate and still-unbuilt
path (docs/spec-divergences.md #10).

Two writers here. ``save_as_template`` reads a poll's current configuration
into a new named row; it is callable in any poll state, since none of these
fields change once the poll leaves ``draft`` (INV-6) — there is nothing a
later edit could invalidate. ``rename`` and ``delete`` are screen 13's; there
is no "edit a template's mechanism" action, because there is no poll behind a
template for a form to validate against (R-3.1's date and ranking-consistency
checks all assume one).

``scalars`` is the read side "Nouveau scrutin" uses to seed a blank creation
from a chosen template — it writes nothing itself. The poll it seeds is still
created by ``elections.config.create_poll`` exactly as for a blank poll.
"""

from __future__ import annotations

from django.db import transaction
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.audit.models import Action
from apps.core.models import User

from .models import Poll, PollTemplate

#: The fields a template carries — the tally mechanism and the ballot rules
#: built around it. Never ``title_i18n``, ``description_i18n``, options or any
#: date (§3.9). ``languages`` is handled apart, exactly as
#: ``elections.config.SCALAR_FIELDS`` treats it: its shape is not one form
#: field either.
TEMPLATE_FIELDS: tuple[str, ...] = (
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
)


class DuplicateTemplateName(Exception):
    """Screen 2 or screen 13 tried to save or rename a template to a name
    already in use — unique per commune so the creation screen's list is
    unambiguous (§3.9)."""


@transaction.atomic
def save_as_template(poll: Poll, *, name: str, actor: User) -> PollTemplate:
    """Screen 2's *enregistrer comme modèle* (§3.9). No before/after payload,
    like ``config.create_poll``'s own event: the new row is a reference, and
    its full state lives on it, not copied onto the event (§10)."""
    if PollTemplate.objects.filter(name=name).exists():
        raise DuplicateTemplateName(_("Un modèle porte déjà ce nom."))
    template = PollTemplate.objects.create(
        name=name,
        languages=list(poll.languages),
        created_by=actor,
        **{field: getattr(poll, field) for field in TEMPLATE_FIELDS},
    )
    audit.record(
        action=Action.TEMPLATE_CREATED,
        poll=poll,
        actor=actor,
        object_ref=audit.ref(template),
    )
    return template


def scalars(template: PollTemplate) -> dict[str, object]:
    """A template's mechanism fields, shaped for ``config.ConfigDraft.scalars``
    — seeds "Nouveau scrutin" (§6.5) with everything but title, description
    and options, which a template never carries. Pure read; the poll it seeds
    is still created by ``elections.config.create_poll`` as normal."""
    return {field: getattr(template, field) for field in TEMPLATE_FIELDS}


@transaction.atomic
def rename(template: PollTemplate, *, name: str, actor: User) -> PollTemplate:
    """Screen 13's rename action. Logs which field moved, not the values
    (§10) — the same restraint ``config.save_configuration`` and
    ``mailsettings.save`` keep."""
    if template.name == name:
        return template
    if PollTemplate.objects.filter(name=name).exclude(pk=template.pk).exists():
        raise DuplicateTemplateName(_("Un modèle porte déjà ce nom."))
    template.name = name
    template.save(update_fields=["name"])
    audit.record(
        action=Action.TEMPLATE_RENAMED,
        poll=None,
        actor=actor,
        object_ref=audit.ref(template),
        after={"changed": ["name"]},
    )
    return template


@transaction.atomic
def delete(template: PollTemplate, *, actor: User) -> None:
    """Screen 13's delete action. Affects no poll ever created from this
    template: the fields were copied at creation time, not referenced (§3.9)."""
    ref = audit.ref(template)
    template.delete()
    audit.record(
        action=Action.TEMPLATE_DELETED,
        poll=None,
        actor=actor,
        object_ref=ref,
    )
