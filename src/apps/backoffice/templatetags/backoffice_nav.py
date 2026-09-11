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
  carries meaning by colour or state alone (R-14.1). The one exception is the
  commune admin, who assigns the per-poll roles anyway (§3.7): they see every
  poll entry, and the ones they do not yet hold a role for point at the
  role-assignment screen instead of 403-ing. The flag still opens no screen on
  its own (access.py);
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
    #: Name of a ``<symbol>`` in the sprite at the top of ``backoffice/_nav.html``.
    icon: str = ""

    def lit_by(self, url_name: str) -> bool:
        return url_name == self.url_name or url_name in self.owns


@dataclass(frozen=True)
class _Group:
    label: Promise
    items: tuple[_Item, ...] = field(default_factory=tuple)


#: Always under the wordmark, in this order, on every screen. « Scrutins » is
#: open to any signed-in operator; the other two need the commune-admin flag.
_GLOBAL_ITEMS: tuple[_Item, ...] = (
    _Item(_("Scrutins"), "poll_index", icon="polls"),
    _Item(_("Nouveau scrutin"), "poll_create", (_COMMUNE,), icon="new"),
    # R-2.1: importing the roll is the commune administrator's, not a poll's —
    # WorkingRollEntry is commune-wide (§3.2), so this lives here and never in
    # a poll submenu (docs/spec-divergences.md #11). A poll's own menu shows a
    # read-only entry instead — see ``_POLL_MENU``'s "Liste électorale".
    _Item(
        _("Liste électorale"),
        "roll_import",
        (_COMMUNE,),
        owns=("roll_import_review",),
        icon="roll",
    ),
    _Item(_("Comptes opérateurs"), "account_admin", (_COMMUNE,), icon="accounts"),
    _Item(_("Rôles par scrutin"), "role_admin", (_COMMUNE,), icon="roles"),
    _Item(_("Messagerie"), "mail_settings", (_COMMUNE,), icon="mail"),
)

#: Added below the global links when a poll is in scope, grouped in the order the
#: work is done: prepare the poll, key the paper, tally, then the read-only trail.
_POLL_MENU: tuple[_Group, ...] = (
    _Group(
        _("Scrutin"),
        (
            _Item(_("Tableau de bord"), "dashboard", icon="dashboard"),
            _Item(_("Configuration"), "poll_config", (_POLL_ADMIN,), icon="config"),
            # Read-only (§3.2, R-2.1): what is imported and when, never an
            # import action — that is the general "Liste électorale" above,
            # not something a poll submenu offers (docs/spec-divergences.md
            # #11).
            _Item(_("Liste électorale"), "roll_status", (_POLL_ADMIN,), icon="roll"),
            _Item(
                _("Inscriptions"),
                "registration_queue",
                (_POLL_ADMIN,),
                owns=("registration_decide",),
                icon="registrations",
            ),
        ),
    ),
    _Group(
        _("Bulletins papier"),
        (
            _Item(
                _("Saisie"),
                "paper_entry",
                (_ENTRY_OPERATOR,),
                owns=("paper_receipt",),
                icon="entry",
            ),
            _Item(
                _("Bulletins papier"),
                "paper_ballot_list",
                (_ENTRY_OPERATOR, _POLL_ADMIN),
                owns=("paper_ballot",),
                icon="paper",
            ),
            _Item(
                _("Contreseing"),
                "countersign_queue",
                (_ENTRY_OPERATOR,),
                needs_countersign=True,
                icon="countersign",
            ),
        ),
    ),
    _Group(
        _("Résultats"),
        (_Item(_("Dépouillement"), "results_publish", (_POLL_ADMIN,), icon="tally"),),
    ),
    _Group(
        _("Suivi"),
        (_Item(_("Journal d'audit"), "audit_log", (_AUDITOR, _POLL_ADMIN), icon="audit"),),
    ),
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
            {
                "label": item.label,
                "url": reverse(f"backoffice:{item.url_name}"),
                "current": active,
                "icon": item.icon,
            }
        )

    poll_groups: list[dict[str, object]] = []
    if poll is not None:
        roles = poll_roles(user, poll)
        # A commune admin assigns the per-poll roles (§3.7), so hiding an entry
        # from them is pointless — they would just grant themselves the role.
        # They see every entry; the ones they do not yet hold a role for lead to
        # the role-assignment screen for this poll rather than to a 403. The flag
        # still opens nothing on its own: reaching a screen that shows a voter
        # beside a ballot follows the audited grant, never the flag (see
        # access.py). Every other role sees only what its grant opens.
        grant_url = f"{reverse('backoffice:role_admin')}?scrutin={poll.pk}"
        for group in _POLL_MENU:
            entries = []
            for item in group.items:
                if item.needs_countersign and not poll.paper_requires_countersign:
                    continue
                held = not item.roles or bool(roles & set(item.roles))
                if not held and not commune_admin:
                    continue
                active = item.lit_by(url_name)
                if active:
                    current_label = item.label
                entries.append(
                    {
                        "label": item.label,
                        "url": reverse(f"backoffice:{item.url_name}", args=[poll.pk])
                        if held
                        else grant_url,
                        "current": active,
                        "needs_grant": not held,
                        "icon": item.icon,
                    }
                )
            if entries:
                poll_groups.append({"label": group.label, "items": entries})

    return global_items, poll_groups, current_label


@register.inclusion_tag("backoffice/_nav.html", takes_context=True)
def bo_nav(context: template.Context) -> dict[str, object]:
    """The left-column menu: the global links always, the poll groups when a
    poll is in scope, and — at the foot of the panel — the language and theme
    controls the public pages keep in their footer (§6.5)."""
    global_items, poll_groups, _label = _resolve(context)
    poll = context.get("poll")
    request = context["request"]
    return {
        "global_items": global_items,
        "poll_groups": poll_groups,
        "poll": poll if isinstance(poll, Poll) else None,
        "poll_index_url": reverse("backoffice:poll_index"),
        # Passed through so the language form can post with a CSRF token and come
        # back to the same screen; the inclusion tag gets a bare context.
        "csrf_token": context.get("csrf_token"),
        "request_path": request.get_full_path(),
    }


@register.simple_tag(takes_context=True)
def bo_current_label(context: template.Context) -> Promise | str:
    """The active menu entry's label, for the breadcrumb leaf. Empty on the poll
    index and anywhere the current screen is not in the menu at all."""
    _global, _poll, label = _resolve(context)
    return label
