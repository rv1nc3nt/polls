# SPDX-License-Identifier: 0BSD
"""Screen 2 of §6.5 — configuration du scrutin.

What it must get right is R-3.3's boundary: everything is editable while the
poll is ``draft`` and nothing is afterwards, save the reasoned ``closes_at``
extension of R-3.4. The write goes through ``elections.config`` (§5.1), which
logs the fields that moved; the screen itself renders the editor or the
read-only view from ``poll.state`` alone.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.audit.models import Action, AuditEvent, Reason
from apps.core.models import PollRole, Role, User
from apps.elections import config
from apps.elections.models import Poll, TallyMethod
from apps.elections.transitions import open_poll


@pytest.fixture
def admin_user(db: None) -> User:
    return User.objects.create_user(username="p.martin", password="x", full_name="P. Martin")


def _grant(poll: Poll, user: User, role: Role) -> None:
    PollRole.objects.create(poll=poll, user=user, role=role)


def _dt(value: object) -> str:
    return timezone.localtime(value).strftime("%Y-%m-%dT%H:%M")  # type: ignore[arg-type]


_BOOL_FIELDS = (
    "require_complete_ranking",
    "allow_ties_in_ballot",
    "paper_requires_signed_form",
    "paper_requires_countersign",
    "paper_requires_reconciliation",
    "allow_ballot_modification",
    "show_live_participation",
)


def _payload(poll: Poll) -> dict[str, object]:
    """A POST body that re-submits the poll's current configuration unchanged.

    The datetime fields round-trip at minute precision, so a bare re-submit
    counts as touching them; a test that needs an exact ``changed`` set says so
    against the field it actually altered.
    """
    languages = list(poll.languages) or ["fr"]
    options = list(poll.options.all())
    data: dict[str, object] = {
        "opens_at": _dt(poll.opens_at),
        "closes_at": _dt(poll.closes_at),
        "paper_entry_deadline": _dt(poll.paper_entry_deadline),
        "timezone": poll.timezone,
        "tally_method": poll.tally_method,
        "tally_method_version": poll.tally_method_version,
        "tiebreak_rule": poll.tiebreak_rule,
        "eligible_list_types": list(poll.eligible_list_types),
        "default_language": languages[0],
        "extra_languages": languages[1:],
        "opt-TOTAL_FORMS": str(len(options)),
        "opt-INITIAL_FORMS": str(len(options)),
        "opt-MIN_NUM_FORMS": "0",
        "opt-MAX_NUM_FORMS": "1000",
    }
    for name in _BOOL_FIELDS:
        if getattr(poll, name):
            data[name] = "on"
    for code in languages:
        data[f"title_{code}"] = poll.title_i18n.get(code, "")
        data[f"description_{code}"] = poll.description_i18n.get(code, "")
    for index, option in enumerate(options):
        data[f"opt-{index}-pk"] = str(option.pk)
        data[f"opt-{index}-option_id"] = option.option_id
        for code in languages:
            data[f"opt-{index}-label_{code}"] = option.label_i18n.get(code, "")
    return data


def _url(poll: Poll) -> str:
    return f"/fr/mairie/scrutin/{poll.pk}/configuration/"


# --- the draft / non-draft boundary (R-3.3) --------------------------------


def test_the_draft_screen_offers_an_editable_form(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    _grant(open_window_poll, admin_user, Role.POLL_ADMIN)
    client.force_login(admin_user)

    body = client.get(_url(open_window_poll)).content.decode()
    assert 'name="tally_method"' in body
    assert 'name="opt-0-option_id"' in body
    # R-3.7: the test-poll quality is shown, never offered as a field.
    assert 'name="is_sandbox"' not in body


def test_saving_persists_the_change_and_logs_which_fields_moved(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    _grant(open_window_poll, admin_user, Role.POLL_ADMIN)
    client.force_login(admin_user)

    data = _payload(open_window_poll)
    data["tally_method"] = TallyMethod.PLURALITY
    data["title_fr"] = "Titre révisé"
    response = client.post(_url(open_window_poll), data)
    assert response.status_code == 302

    open_window_poll.refresh_from_db()
    assert open_window_poll.tally_method == TallyMethod.PLURALITY
    assert open_window_poll.title_i18n["fr"] == "Titre révisé"

    event = AuditEvent.objects.get(action=Action.POLL_CONFIG_CHANGED, poll=open_window_poll)
    assert event.object_ref == f"poll:{open_window_poll.pk}"
    assert "tally_method" in event.after["changed"]
    assert "title_i18n" in event.after["changed"]


def test_options_can_be_relabelled_and_added(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    _grant(open_window_poll, admin_user, Role.POLL_ADMIN)
    client.force_login(admin_user)

    data = _payload(open_window_poll)
    data["opt-0-label_fr"] = "Place arborée"
    data["opt-TOTAL_FORMS"] = "4"
    data["opt-3-option_id"] = "d"
    data["opt-3-label_fr"] = "Quatrième proposition"
    assert client.post(_url(open_window_poll), data).status_code == 302

    labels = {o.option_id: o.label("fr") for o in open_window_poll.options.all()}
    assert labels["a"] == "Place arborée"
    assert labels["d"] == "Quatrième proposition"
    assert open_window_poll.options.count() == 4


def test_fewer_than_two_propositions_is_refused(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    """§3.1: an ordered list of at least two options."""
    _grant(open_window_poll, admin_user, Role.POLL_ADMIN)
    client.force_login(admin_user)

    data = _payload(open_window_poll)
    data["opt-1-DELETE"] = "on"
    data["opt-2-DELETE"] = "on"
    response = client.post(_url(open_window_poll), data)

    assert response.status_code == 200
    assert "au moins deux propositions" in response.content.decode()
    assert open_window_poll.options.count() == 3
    assert not AuditEvent.objects.filter(action=Action.POLL_CONFIG_CHANGED).exists()


def test_a_closing_instant_before_the_opening_one_is_refused(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    _grant(open_window_poll, admin_user, Role.POLL_ADMIN)
    client.force_login(admin_user)

    data = _payload(open_window_poll)
    data["closes_at"] = _dt(open_window_poll.opens_at - timedelta(hours=1))
    response = client.post(_url(open_window_poll), data)

    assert response.status_code == 200
    assert "doit suivre l&#x27;ouverture" in response.content.decode()
    open_window_poll.refresh_from_db()
    assert open_window_poll.closes_at > open_window_poll.opens_at


def test_adding_a_language_leaves_a_translation_gap_for_the_dashboard(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    """§3.8: the configuration screen shows the gaps; it does not force them
    closed. A newly enabled language has no content field yet, so it is a gap
    the dashboard names as an opening blocker (§4)."""
    _grant(open_window_poll, admin_user, Role.POLL_ADMIN)
    client.force_login(admin_user)

    data = _payload(open_window_poll)
    data["extra_languages"] = ["en"]
    assert client.post(_url(open_window_poll), data).status_code == 302

    open_window_poll.refresh_from_db()
    assert open_window_poll.languages == ["fr", "en"]
    assert "title:en" in open_window_poll.missing_translations()


def test_a_non_draft_poll_is_read_only(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    open_poll(open_window_poll)
    _grant(open_window_poll, admin_user, Role.POLL_ADMIN)
    client.force_login(admin_user)

    body = client.get(_url(open_window_poll)).content.decode()
    assert "la configuration est figée" in body
    assert 'name="tally_method"' not in body
    # The frozen values are still shown for consultation.
    assert open_window_poll.get_tally_method_display() in body


def test_the_service_refuses_a_write_once_the_poll_has_left_draft(
    open_window_poll: Poll, admin_user: User
) -> None:
    """R-3.3 / INV-6, checked before any write so nothing is half-applied.
    ``Poll.save()`` and the trigger back this; the service message is the one
    a council member can act on."""
    open_poll(open_window_poll)
    draft = config.ConfigDraft(
        scalars={"tally_method": TallyMethod.APPROVAL},
        languages=["fr"],
        title_i18n={"fr": "Autre"},
        description_i18n={"fr": "Autre"},
    )
    with pytest.raises(config.ConfigurationLocked):
        config.save_configuration(open_window_poll, draft, actor=admin_user)

    open_window_poll.refresh_from_db()
    assert open_window_poll.tally_method == TallyMethod.SCHULZE


# --- R-3.4: the one change still allowed once the poll is open -------------


def test_the_closing_date_can_be_extended_on_an_open_poll(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    open_poll(open_window_poll)
    window = open_window_poll.paper_entry_deadline - open_window_poll.closes_at
    new_closes_at = open_window_poll.closes_at + timedelta(days=3)
    _grant(open_window_poll, admin_user, Role.POLL_ADMIN)
    client.force_login(admin_user)

    response = client.post(
        _url(open_window_poll),
        {
            "new_closes_at": _dt(new_closes_at),
            "reason": Reason.ADMINISTRATIVE_DECISION,
        },
    )
    assert response.status_code == 302

    open_window_poll.refresh_from_db()
    assert abs((open_window_poll.closes_at - new_closes_at).total_seconds()) < 60
    # §4: the paper keying window moves with it, keeping its configured length.
    assert open_window_poll.paper_entry_deadline - open_window_poll.closes_at == window
    assert AuditEvent.objects.filter(
        action=Action.POLL_CLOSES_AT_EXTENDED, poll=open_window_poll
    ).exists()


def test_an_extension_to_an_earlier_instant_is_refused(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    open_poll(open_window_poll)
    original = Poll.objects.get(pk=open_window_poll.pk).closes_at
    _grant(open_window_poll, admin_user, Role.POLL_ADMIN)
    client.force_login(admin_user)

    response = client.post(
        _url(open_window_poll),
        {
            "new_closes_at": _dt(original - timedelta(days=1)),
            "reason": Reason.ADMINISTRATIVE_DECISION,
        },
    )
    assert response.status_code == 200
    assert "postérieure" in response.content.decode()
    assert Poll.objects.get(pk=open_window_poll.pk).closes_at == original


# --- the gate (§3.7) ------------------------------------------------------


def test_an_auditor_cannot_reach_the_configuration_screen(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    """Configuration is the poll admin's, not the auditor's (§3.7)."""
    _grant(open_window_poll, admin_user, Role.AUDITOR)
    client.force_login(admin_user)
    assert client.get(_url(open_window_poll)).status_code == 403


def test_the_dashboard_links_to_the_configuration_screen(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    _grant(open_window_poll, admin_user, Role.POLL_ADMIN)
    client.force_login(admin_user)
    body = client.get(f"/fr/mairie/scrutin/{open_window_poll.pk}/").content.decode()
    assert f"/mairie/scrutin/{open_window_poll.pk}/configuration/" in body
