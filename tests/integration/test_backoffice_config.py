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
from apps.ballots.models import Ballot, BallotSource, BallotStatus
from apps.core.codes import new_tracking_code
from apps.core.models import PollRole, Role, User
from apps.elections import config
from apps.elections.models import Poll, PollOption, PollState, TallyMethod, WorkingRollEntry
from apps.elections.transitions import TransitionRefused, open_poll, opening_blockers


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


def test_the_draft_screen_carries_the_add_remove_proposition_enhancement(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    """The propositions count is not fixed (R-3.1: *at least* two). The screen
    ships static/js/option-editor.js and the hooks it drives — an « Ajouter »
    control and a clone template carrying Django's ``__prefix__`` placeholder —
    so a poll can be given any number of options. Progressive enhancement: the
    ``extra`` blank rows and the DELETE checkbox are the no-JS path.
    """
    _grant(open_window_poll, admin_user, Role.POLL_ADMIN)
    client.force_login(admin_user)

    body = client.get(_url(open_window_poll)).content.decode()
    assert "js/option-editor.js" in body
    assert "data-option-editor" in body
    assert "data-option-add-button" in body
    assert 'name="opt-__prefix__-option_id"' in body

    # The frozen, read-only view past draft carries none of it.
    open_poll(open_window_poll)
    frozen = client.get(_url(open_window_poll)).content.decode()
    assert "js/option-editor.js" not in frozen
    assert "data-option-editor" not in frozen


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


def test_t22_one_untranslated_option_label_blocks_the_opening_and_is_named(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    """T-22 / R-14.3: English enabled, title and description translated, every
    option label translated *but one* — the poll cannot leave ``draft`` and the
    gap is named for the operator. ``open_poll`` refuses and leaves the state
    untouched; the dashboard spells the gap out in French; the configuration
    screen carries the pointer to it.

    §3.8 phrases this as "the configuration screen shows the gaps"; the
    implementation names them on the dashboard (screen 1) and screen 2 directs
    the reader there — recorded in the ``missing_translations`` docstring. R-14.3
    fixes only that the gap block the opening and be surfaced, which holds.
    """
    _grant(open_window_poll, admin_user, Role.POLL_ADMIN)
    client.force_login(admin_user)

    assert [o.option_id for o in open_window_poll.options.all()] == ["a", "b", "c"]

    # First POST enables English; its content fields do not exist on the form
    # until the language is on the poll, so this leaves every ``en`` string blank.
    add_en = _payload(open_window_poll)
    add_en["extra_languages"] = ["en"]
    assert client.post(_url(open_window_poll), add_en).status_code == 302

    # Second POST fills the English content — title, description and two of the
    # three option labels. Option c is left untranslated.
    poll = Poll.objects.get(pk=open_window_poll.pk)
    assert poll.languages == ["fr", "en"]
    fill = _payload(poll)
    fill["title_en"] = "Redevelopment of the square"
    fill["description_en"] = "Three options."
    fill["opt-0-label_en"] = "The square, redeveloped"
    fill["opt-1-label_en"] = "A wooded park"
    fill["opt-2-label_en"] = ""  # option c left untranslated
    assert client.post(_url(poll), fill).status_code == 302

    poll = Poll.objects.get(pk=poll.pk)
    assert poll.missing_translations() == ["option:c:en"]
    assert "missing_translation:option:c:en" in opening_blockers(poll)

    # Cannot leave draft.
    with pytest.raises(TransitionRefused):
        open_poll(poll)
    assert Poll.objects.get(pk=poll.pk).state == "draft"

    # The dashboard names the gap, in French, pointing at the option.
    dashboard = client.get(f"/fr/mairie/scrutin/{poll.pk}/").content.decode()
    assert "Traduction manquante en en : proposition « c »." in dashboard

    # The configuration screen carries the reader to where the gaps are shown.
    config_screen = client.get(_url(poll)).content.decode()
    assert "tableau de bord" in config_screen


# --- §8.2: the screen-2 misconfiguration warning -------------------------

_WARNING_MARK = "un bulletin qui place plusieurs propositions en tête donne une voix"


def test_the_editor_warns_on_plurality_with_ballot_ties_without_blocking_the_save(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    """§8.2: ``plurality`` + ``allow_ties_in_ballot`` tallies deterministically,
    so the screen warns rather than refusing — the save still goes through and
    the poll can still open."""
    _grant(open_window_poll, admin_user, Role.POLL_ADMIN)
    client.force_login(admin_user)

    data = _payload(open_window_poll)
    data["tally_method"] = TallyMethod.PLURALITY
    data["allow_ties_in_ballot"] = "on"
    assert client.post(_url(open_window_poll), data).status_code == 302

    open_window_poll.refresh_from_db()
    assert open_window_poll.tally_method == TallyMethod.PLURALITY
    assert open_window_poll.allow_ties_in_ballot is True

    body = client.get(_url(open_window_poll)).content.decode()
    assert _WARNING_MARK in body
    assert 'role="status"' in body
    # Advisory, not an error: it must not be dressed as a validation failure.
    assert 'role="alert"' not in body


def test_no_warning_without_the_combination(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    _grant(open_window_poll, admin_user, Role.POLL_ADMIN)
    client.force_login(admin_user)

    body = client.get(_url(open_window_poll)).content.decode()
    assert _WARNING_MARK not in body


def test_the_read_only_view_still_carries_the_warning(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    """The combination is frozen in past ``draft`` — the operator can no longer
    fix it, which is exactly when naming it explains a later tally."""
    open_window_poll.tally_method = TallyMethod.PLURALITY
    open_window_poll.allow_ties_in_ballot = True
    open_window_poll.save()
    open_poll(open_window_poll)
    _grant(open_window_poll, admin_user, Role.POLL_ADMIN)
    client.force_login(admin_user)

    body = client.get(_url(open_window_poll)).content.decode()
    assert "la configuration est figée" in body
    assert _WARNING_MARK in body


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


# --- R-2.1 / §4: manual open and close from screen 2 ------------------------


def test_t67_open_now_succeeds_early_and_refuses_an_unready_poll(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    """T-67: *ouvrir maintenant* works at any time, including well before
    ``opens_at`` — nothing on the vote/registration write paths depends on
    ``state`` — and refuses, with the same blockers ``open_poll`` itself would
    report, on a poll that is not ready."""
    open_window_poll.opens_at = timezone.now() + timedelta(hours=6)
    open_window_poll.save(update_fields=["opens_at"])
    _grant(open_window_poll, admin_user, Role.POLL_ADMIN)
    client.force_login(admin_user)

    response = client.post(_url(open_window_poll), {"action": "open_poll"})
    assert response.status_code == 302
    open_window_poll.refresh_from_db()
    assert open_window_poll.state == PollState.OPEN
    assert open_window_poll.opening_seed is not None
    assert AuditEvent.objects.filter(
        action=Action.POLL_STATE_CHANGED, poll=open_window_poll
    ).exists()

    unready = Poll.objects.create(
        title_i18n={"fr": "Autre"},
        description_i18n={"fr": "Autre"},
        languages=["fr"],
        opens_at=timezone.now() + timedelta(days=1),
        closes_at=timezone.now() + timedelta(days=3),
        paper_entry_deadline=timezone.now() + timedelta(days=3),
    )
    PollOption.objects.create(poll=unready, option_id="a", label_i18n={"fr": "A"}, position=0)
    PollOption.objects.create(poll=unready, option_id="b", label_i18n={"fr": "B"}, position=1)
    _grant(unready, admin_user, Role.POLL_ADMIN)
    WorkingRollEntry.objects.all().delete()

    body = client.post(_url(unready), {"action": "open_poll"}).content.decode()
    unready.refresh_from_db()
    assert unready.state == PollState.DRAFT
    assert "Ouverture refusée" in body


def test_t68_close_now_is_gated_on_the_deadline_and_needs_a_reason_when_blocked(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    """T-68: *clôturer maintenant* is refused outright, without closing the
    poll, before ``paper_entry_deadline``; once due, refused again without a
    reason while a ballot awaits countersignature, then succeeds with one —
    the override reason ``close_poll`` cannot get from a scheduled command."""
    open_window_poll.paper_requires_countersign = True
    open_window_poll.save(update_fields=["paper_requires_countersign"])
    poll = open_poll(open_window_poll)
    Ballot.objects.create(
        poll=poll,
        tracking_code=new_tracking_code(),
        ranking=[["a"], ["b"], ["c"]],
        source=BallotSource.PAPER,
        status=BallotStatus.PENDING_COUNTERSIGN,
    )
    _grant(poll, admin_user, Role.POLL_ADMIN)
    client.force_login(admin_user)

    # Not yet due: the form is absent, and a forged POST changes nothing.
    body = client.get(_url(poll)).content.decode()
    assert 'value="close_poll"' not in body
    response = client.post(_url(poll), {"action": "close_poll"})
    assert response.status_code == 403
    poll.refresh_from_db()
    assert poll.state == PollState.OPEN

    now = timezone.now()
    poll.closes_at = now - timedelta(minutes=2)
    poll.paper_entry_deadline = now - timedelta(minutes=1)
    poll.save(update_fields=["closes_at", "paper_entry_deadline"])

    # Due, but blocked without a reason: refused, not silently dropped (§9).
    body = client.get(_url(poll)).content.decode()
    assert 'value="close_poll"' in body
    blocked = client.post(_url(poll), {"action": "close_poll", "reason": ""}).content.decode()
    assert "Clôture refusée" in blocked
    poll.refresh_from_db()
    assert poll.state == PollState.OPEN

    response = client.post(
        _url(poll), {"action": "close_poll", "reason": Reason.COUNTERSIGN_UNAVAILABLE}
    )
    assert response.status_code == 302
    poll.refresh_from_db()
    assert poll.state == PollState.CLOSED
    assert poll.closure_override_reason == Reason.COUNTERSIGN_UNAVAILABLE
    assert AuditEvent.objects.filter(action=Action.CLOSURE_OVERRIDE, poll=poll).exists()


def test_close_now_succeeds_without_a_reason_once_due_and_nothing_is_blocked(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    now = timezone.now()
    open_window_poll.closes_at = now - timedelta(minutes=2)
    open_window_poll.paper_entry_deadline = now - timedelta(minutes=1)
    open_window_poll.save(update_fields=["closes_at", "paper_entry_deadline"])
    poll = open_poll(open_window_poll)
    _grant(poll, admin_user, Role.POLL_ADMIN)
    client.force_login(admin_user)

    response = client.post(_url(poll), {"action": "close_poll", "reason": ""})
    assert response.status_code == 302
    poll.refresh_from_db()
    assert poll.state == PollState.CLOSED
    assert poll.closure_override_reason == ""


def test_announce_now_shows_the_poll_publicly_and_freezes_configuration(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    """R-3.10: ``draft → announced``, config frozen the instant it runs —
    same trigger as opening (INV-6: ``state != draft``) — and ``open_poll``
    still works from ``announced`` afterwards, exactly as from ``draft``."""
    _grant(open_window_poll, admin_user, Role.POLL_ADMIN)
    client.force_login(admin_user)

    response = client.post(_url(open_window_poll), {"action": "announce_poll"})
    assert response.status_code == 302
    open_window_poll.refresh_from_db()
    assert open_window_poll.state == PollState.ANNOUNCED
    assert AuditEvent.objects.filter(
        action=Action.POLL_STATE_CHANGED, poll=open_window_poll
    ).exists()

    body = client.get(_url(open_window_poll)).content.decode()
    assert "la configuration est figée" in body
    with pytest.raises(config.ConfigurationLocked):
        config.save_configuration(
            open_window_poll,
            config.ConfigDraft(
                scalars={"tally_method": TallyMethod.APPROVAL},
                languages=["fr"],
                title_i18n={"fr": "Autre"},
                description_i18n={"fr": "Autre"},
            ),
            actor=admin_user,
        )

    response = client.post(_url(open_window_poll), {"action": "open_poll"})
    assert response.status_code == 302
    open_window_poll.refresh_from_db()
    assert open_window_poll.state == PollState.OPEN


def test_announce_now_refuses_fewer_than_two_propositions(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    open_window_poll.options.exclude(option_id="a").delete()
    _grant(open_window_poll, admin_user, Role.POLL_ADMIN)
    client.force_login(admin_user)

    body = client.post(_url(open_window_poll), {"action": "announce_poll"}).content.decode()
    open_window_poll.refresh_from_db()
    assert open_window_poll.state == PollState.DRAFT
    assert "Annonce refusée" in body


def test_announce_now_is_refused_once_the_poll_has_left_draft(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    poll = open_poll(open_window_poll)
    _grant(poll, admin_user, Role.POLL_ADMIN)
    client.force_login(admin_user)

    response = client.post(_url(poll), {"action": "announce_poll"})
    assert response.status_code == 403
    poll.refresh_from_db()
    assert poll.state == PollState.OPEN
