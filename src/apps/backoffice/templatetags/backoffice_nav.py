# SPDX-License-Identifier: 0BSD
"""The espace mairie navigation (§6.5).

One menu, defined here once, on every back-office page. It replaces the
``{% block pollnav %}`` each screen used to carry — those listed a different
subset of links, in a different order, sometimes under a different name, so the
navigation changed shape as the operator moved through it.

The menu has two parts, and the first never changes:

* the **global** links — « Scrutins », plus « Comptes opérateurs » and « Rôles
  par scrutin » for a commune admin — sit under the wordmark on every screen, in
  the same order, whether or not a poll is in scope;
* the **poll** groups — prepare the poll, key the paper, tally, then the
  read-only trail — are *added* below when a poll is open, headed by its title
  and state. Leaving a poll removes that block; it never rearranges the part
  above it.

The rules this keeps:

* an entry the operator's role does not open is **absent**, not greyed — nothing
  carries meaning by colour or state alone (R-14.1);
* the active entry is marked, and the breadcrumb leaf is the *same* label
  (``bo_current_label``), so the menu and the breadcrumb cannot disagree;
* a screen reached from within a section but not itself in the menu — the roll
  import review, a single paper ballot, the registration decision — lights its
  parent entry (``owns``).

The menu is data, not markup: ``_GLOBAL_ITEMS`` and ``_POLL_MENU`` below are the
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

#: Sentinel role for a global entry that needs the commune-admin flag (§3.7),
#: which is not one of the per-poll roles.
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


#: Always under the wordmark, in this order, on every screen. « Scrutins » is
#: open to any signed-in operator; the other two need the commune-admin flag.
_GLOBAL_ITEMS: tuple[_Item, ...] = (
    _Item(_("Scrutins"), "poll_index"),
    _Item(_("Comptes opérateurs"), "account_admin", (_COMMUNE,)),
    _Item(_("Rôles par scrutin"), "role_admin", (_COMMUNE,)),
)

#: Added below the global links when a poll is in scope, grouped in the order the
#: work is done: prepare the poll, key the paper, tally, then the read-only trail.
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

_Resolved = tuple[list[dict[str, object]], list[dict[str, object]], "Promise | str"]


def _resolve(context: template.Context) -> _Resolved:
    """``(global_items, poll_groups, current_label)`` for the current request.

    Returns empties for anyone not signed in, so the tag renders the wordmark
    alone on the login and first-run screens. The active screen comes from
    ``request.resolver_match``; ``poll_index`` deliberately yields no breadcrumb
    leaf — the root crumb is already "Scrutins".
    """
    request = context["request"]
    user = request.user
    if not (user.is_authenticated and user.is_active):
        return [], [], ""

    match = getattr(request, "resolver_match", None)
    url_name = match.url_name if match is not None else ""
    poll = context.get("poll")
    poll = poll if isinstance(poll, Poll) else None

    current_label: Promise | str = ""

    commune_admin = is_commune_admin(user)
    global_items: list[dict[str, object]] = []
    for item in _GLOBAL_ITEMS:
        if _COMMUNE in item.roles and not commune_admin:
            continue
        active = item.lit_by(url_name)
        if active and item.url_name != "poll_index":
            current_label = item.label
        global_items.append(
            {"label": item.label, "url": reverse(f"backoffice:{item.url_name}"), "current": active}
        )

    poll_groups: list[dict[str, object]] = []
    if poll is not None:
        roles = poll_roles(user, poll)
        for group in _POLL_MENU:
            entries = []
            for item in group.items:
                if item.needs_countersign and not poll.paper_requires_countersign:
                    continue
                if item.roles and not (roles & set(item.roles)):
                    continue
                active = item.lit_by(url_name)
                if active:
                    current_label = item.label
                entries.append(
                    {
                        "label": item.label,
                        "url": reverse(f"backoffice:{item.url_name}", args=[poll.pk]),
                        "current": active,
                    }
                )
            if entries:
                poll_groups.append({"label": group.label, "items": entries})

    return global_items, poll_groups, current_label


@register.inclusion_tag("backoffice/_nav.html", takes_context=True)
def bo_nav(context: template.Context) -> dict[str, object]:
    """The left-column menu: the global links always, the poll groups when a
    poll is in scope."""
    global_items, poll_groups, _label = _resolve(context)
    poll = context.get("poll")
    return {
        "global_items": global_items,
        "poll_groups": poll_groups,
        "poll": poll if isinstance(poll, Poll) else None,
        "poll_index_url": reverse("backoffice:poll_index"),
    }


@register.simple_tag(takes_context=True)
def bo_current_label(context: template.Context) -> Promise | str:
    """The active menu entry's label, for the breadcrumb leaf. Empty on the poll
    index and anywhere the current screen is not in the menu at all."""
    _global, _poll, label = _resolve(context)
    return label
