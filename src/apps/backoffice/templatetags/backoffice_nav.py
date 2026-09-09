# SPDX-License-Identifier: 0BSD
"""The espace mairie navigation (§6.5).

One menu, defined here once and built per request from the poll and the
operator's per-poll roles (§3.7). It replaces the ``{% block pollnav %}`` that
each screen used to carry: those listed a different subset of links, in a
different order, sometimes under a different name, so the navigation changed
shape as the operator moved through it.

The rules this keeps:

* an entry the operator's role does not open is **absent**, not greyed — nothing
  carries meaning by colour or state alone (R-14.1);
* the active entry is marked, and the breadcrumb leaf is the *same* label
  (``bo_current_label``), so the menu and the breadcrumb cannot disagree;
* a screen reached from within a section but not itself in the menu — the roll
  import review, a single paper ballot, the registration decision — lights its
  parent entry (``owns``).

The menu is data, not markup: ``_POLL_MENU`` and ``_COMMUNE_MENU`` below are the
whole of it, and ``backoffice/_nav.html`` only renders what the resolver returns.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django import template
from django.urls import reverse
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _

from apps.core.models import Role
from apps.elections.models import Poll

from ..access import is_commune_admin, poll_roles

register = template.Library()

_POLL_ADMIN = str(Role.POLL_ADMIN)
_ENTRY_OPERATOR = str(Role.ENTRY_OPERATOR)
_AUDITOR = str(Role.AUDITOR)

#: Sentinel role for the commune-level menu: the entry needs the commune-admin
#: flag (§3.7), which is not one of the per-poll roles.
_COMMUNE = "__commune__"


@dataclass(frozen=True)
class _Item:
    """One menu entry. ``roles`` is any-of; empty means every operator who has a
    role on the poll at all (the dashboard). ``owns`` lists further url names
    that should light this entry — screens reached from it but not in the menu
    themselves. ``needs_countersign`` hides the entry where the poll is not
    configured for a second signature (R-8.7)."""

    label: Promise
    url_name: str
    roles: tuple[str, ...] = ()
    owns: tuple[str, ...] = ()
    needs_countersign: bool = False

    def lit_by(self, url_name: str) -> bool:
        return url_name == self.url_name or url_name in self.owns


@dataclass(frozen=True)
class _Group:
    label: Promise
    items: tuple[_Item, ...] = field(default_factory=tuple)


#: Poll-scoped screens, grouped in the order the work is done: prepare the poll,
#: key the paper, tally, then the read-only trail.
_POLL_MENU: tuple[_Group, ...] = (
    _Group(
        _("Scrutin"),
        (
            _Item(_("Tableau de bord"), "dashboard"),
            _Item(_("Configuration"), "poll_config", (_POLL_ADMIN,)),
            _Item(
                _("Liste électorale"), "roll_import", (_POLL_ADMIN,), owns=("roll_import_review",)
            ),
            _Item(
                _("Inscriptions"),
                "registration_queue",
                (_POLL_ADMIN,),
                owns=("registration_decide",),
            ),
        ),
    ),
    _Group(
        _("Bulletins papier"),
        (
            _Item(_("Saisie"), "paper_entry", (_ENTRY_OPERATOR,), owns=("paper_receipt",)),
            _Item(
                _("Bulletins papier"),
                "paper_ballot_list",
                (_ENTRY_OPERATOR, _POLL_ADMIN),
                owns=("paper_ballot",),
            ),
            _Item(
                _("Contreseing"),
                "countersign_queue",
                (_ENTRY_OPERATOR,),
                needs_countersign=True,
            ),
        ),
    ),
    _Group(_("Résultats"), (_Item(_("Dépouillement"), "results_publish", (_POLL_ADMIN,)),)),
    _Group(_("Suivi"), (_Item(_("Journal d'audit"), "audit_log", (_AUDITOR, _POLL_ADMIN)),)),
)

#: Commune-level screens (§6.5.10). "Scrutins" is open to any signed-in
#: operator; the other two need the commune-admin flag.
_COMMUNE_MENU: tuple[_Group, ...] = (
    _Group(
        _("Commune"),
        (
            _Item(_("Scrutins"), "poll_index"),
            _Item(_("Comptes opérateurs"), "account_admin", (_COMMUNE,)),
            _Item(_("Rôles par scrutin"), "role_admin", (_COMMUNE,)),
        ),
    ),
)


def _resolve(context: template.Context) -> tuple[list[dict[str, object]], Promise | str]:
    """The groups to render and the active entry's label.

    ``poll`` in the template context marks a poll-scoped screen; its absence a
    commune-level one. The active screen comes from ``request.resolver_match``;
    ``poll_index`` deliberately yields no breadcrumb leaf — the root crumb is
    already "Scrutins".
    """
    request = context["request"]
    match = getattr(request, "resolver_match", None)
    url_name = match.url_name if match is not None else ""

    poll = context.get("poll")
    if isinstance(poll, Poll):
        roles = poll_roles(request.user, poll)
        source = _POLL_MENU

        def visible(item: _Item) -> bool:
            if item.needs_countersign and not poll.paper_requires_countersign:
                return False
            return not item.roles or bool(roles & set(item.roles))

        def href(item: _Item) -> str:
            return reverse(f"backoffice:{item.url_name}", args=[poll.pk])

    else:
        commune_admin = is_commune_admin(request.user)
        source = _COMMUNE_MENU

        def visible(item: _Item) -> bool:
            return _COMMUNE not in item.roles or commune_admin

        def href(item: _Item) -> str:
            return reverse(f"backoffice:{item.url_name}")

    groups: list[dict[str, object]] = []
    current_label: Promise | str = ""
    for group in source:
        entries = []
        for item in group.items:
            if not visible(item):
                continue
            active = item.lit_by(url_name)
            if active and item.url_name != "poll_index":
                current_label = item.label
            entries.append({"label": item.label, "url": href(item), "current": active})
        if entries:
            groups.append({"label": group.label, "items": entries})
    return groups, current_label


@register.inclusion_tag("backoffice/_nav.html", takes_context=True)
def bo_nav(context: template.Context) -> dict[str, object]:
    """The left-column menu for the current screen."""
    groups, _label = _resolve(context)
    return {
        "groups": groups,
        "poll": context.get("poll"),
        "poll_index_url": reverse("backoffice:poll_index"),
    }


@register.simple_tag(takes_context=True)
def bo_current_label(context: template.Context) -> Promise | str:
    """The active menu entry's label, for the breadcrumb leaf. Empty on the poll
    index and anywhere the current screen is not in the menu at all."""
    _groups, label = _resolve(context)
    return label
