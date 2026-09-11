# SPDX-License-Identifier: 0BSD
"""Named poll templates — R-3.6, R-3.9, §3.9. Three write paths:

* screen 2's *enregistrer comme modèle* (``poll_config``, commune-admin only,
  any poll state — INV-6 freezes the fields it reads from ``draft`` onward);
* screen 13, modèles de scrutin (§6.5.13): rename and delete, commune-level
  like screens 10 and 12;
* "Nouveau scrutin"'s ``?modele=`` (§6.5), which seeds the creation form from
  a template's mechanism fields and nothing else — title, description and
  propositions are still entered fresh.

What this must get right: a template never carries title, description or
options (§3.9); it is reachable to a commune admin in every poll state, not
only ``draft``; deleting one leaves a poll already created from it untouched;
and each write is audited by §10's restraint — a reference, never a copied
value (``TEMPLATE_CREATED``/``_DELETED``) or field names only
(``TEMPLATE_RENAMED``).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.audit.models import Action, AuditEvent
from apps.core.models import PollRole, Role, User
from apps.elections import config, polltemplates
from apps.elections.models import Poll, PollTemplate, TallyMethod

TEMPLATE_URL = "/fr/mairie/modeles/"
CREATE_URL = "/fr/mairie/nouveau/"


def _dt(value: object) -> str:
    return timezone.localtime(value).strftime("%Y-%m-%dT%H:%M")  # type: ignore[arg-type]


@pytest.fixture
def commune_admin(db: None) -> User:
    return User.objects.create_user(
        username="c.admin", password="x", full_name="C. Admin", is_commune_admin=True
    )


@pytest.fixture
def plain_operator(db: None) -> User:
    return User.objects.create_user(username="m.durand", password="x", full_name="M. Durand")


@pytest.fixture
def admin_client(client: Client, commune_admin: User) -> Client:
    client.force_login(commune_admin)
    return client


def _config_url(poll: Poll) -> str:
    return f"/fr/mairie/scrutin/{poll.pk}/configuration/"


def _grant_poll_admin(poll: Poll, user: User) -> None:
    """Screen 2 is gated by ``require_poll_role`` (§3.7), not the
    commune-admin flag: a commune admin needs a grant on ``poll`` like anyone
    else to reach it at all, exactly as §3.7's split intends."""
    PollRole.objects.create(poll=poll, user=user, role=Role.POLL_ADMIN)


def _messages(response: object) -> list[str]:
    return [str(m) for m in response.context["messages"]]  # type: ignore[attr-defined]


# --- screen 13's gate (§3.7) ------------------------------------------------


def test_anonymous_is_sent_to_the_login_page(client: Client, db: None) -> None:
    response = client.get(TEMPLATE_URL)
    assert response.status_code == 302
    assert "/mairie/connexion/" in response["Location"]


def test_a_plain_operator_is_refused(client: Client, plain_operator: User) -> None:
    client.force_login(plain_operator)
    assert client.get(TEMPLATE_URL).status_code == 403


def test_a_commune_admin_reaches_the_screen(admin_client: Client) -> None:
    assert admin_client.get(TEMPLATE_URL).status_code == 200


# --- saving a template from screen 2 (§3.9) ---------------------------------


def test_a_commune_admin_saves_a_template_from_a_draft_poll(
    admin_client: Client, commune_admin: User, open_window_poll: Poll
) -> None:
    _grant_poll_admin(open_window_poll, commune_admin)
    response = admin_client.post(
        _config_url(open_window_poll), {"action": "save_template", "name": "Condorcet simple"}
    )
    assert response.status_code == 302

    template = PollTemplate.objects.get(name="Condorcet simple")
    assert template.tally_method == open_window_poll.tally_method
    assert template.require_complete_ranking == open_window_poll.require_complete_ranking
    assert template.allow_ties_in_ballot == open_window_poll.allow_ties_in_ballot
    assert template.tiebreak_rule == open_window_poll.tiebreak_rule
    assert template.allow_ballot_modification == open_window_poll.allow_ballot_modification
    assert template.eligible_list_types == open_window_poll.eligible_list_types
    assert template.languages == open_window_poll.languages
    assert template.created_by is not None

    event = AuditEvent.objects.get(action=Action.TEMPLATE_CREATED)
    assert event.poll_id == open_window_poll.pk
    assert event.object_ref == f"polltemplate:{template.pk}"
    # §10: a reference and nothing else — no copied value, and certainly not
    # the template's own name.
    assert event.before == {}
    assert event.after == {}


def test_a_template_carries_no_content(
    admin_client: Client, commune_admin: User, open_window_poll: Poll
) -> None:
    """§3.9: never a title, a description or the propositions — those belong
    to duplicating a poll directly (R-3.6), a separate, still-unbuilt path."""
    _grant_poll_admin(open_window_poll, commune_admin)
    admin_client.post(
        _config_url(open_window_poll), {"action": "save_template", "name": "Sans contenu"}
    )
    template = PollTemplate.objects.get(name="Sans contenu")
    assert not hasattr(template, "title_i18n")
    assert not hasattr(template, "description_i18n")
    assert not hasattr(template, "options")


def test_saving_a_template_is_not_confined_to_draft(
    admin_client: Client, commune_admin: User, open_paper_poll: Poll
) -> None:
    """INV-6 freezes these fields from `draft` onward, so there is nothing a
    later edit could invalidate — the action is offered in every state."""
    _grant_poll_admin(open_paper_poll, commune_admin)
    response = admin_client.post(
        _config_url(open_paper_poll),
        {"action": "save_template", "name": "Depuis un scrutin ouvert"},
    )
    assert response.status_code == 302
    assert PollTemplate.objects.filter(name="Depuis un scrutin ouvert").exists()


def test_a_duplicate_name_is_refused(
    admin_client: Client, commune_admin: User, open_window_poll: Poll
) -> None:
    _grant_poll_admin(open_window_poll, commune_admin)
    PollTemplate.objects.create(name="Déjà pris")
    response = admin_client.post(
        _config_url(open_window_poll), {"action": "save_template", "name": "Déjà pris"}, follow=True
    )
    assert "porte déjà ce nom" in " ".join(_messages(response))
    assert PollTemplate.objects.filter(name="Déjà pris").count() == 1


def test_a_poll_admin_without_the_commune_flag_is_refused(
    client: Client, plain_operator: User, open_window_poll: Poll
) -> None:
    """The screen renders this action's form only to a commune admin (§3.9);
    reaching it any other way is a forged request, refused outright."""
    PollRole.objects.create(poll=open_window_poll, user=plain_operator, role=Role.POLL_ADMIN)
    client.force_login(plain_operator)
    response = client.post(
        _config_url(open_window_poll), {"action": "save_template", "name": "Ne doit pas exister"}
    )
    assert response.status_code == 403
    assert not PollTemplate.objects.filter(name="Ne doit pas exister").exists()


def test_the_draft_editor_still_works_alongside_the_template_action(
    admin_client: Client, commune_admin: User, open_window_poll: Poll
) -> None:
    """§3.7's split is about the grant, not about who *can* hold both — a
    commune admin who also holds ``poll_admin`` here still gets the ordinary
    draft editor, unaffected by the new action living on the same screen."""
    _grant_poll_admin(open_window_poll, commune_admin)
    response = admin_client.get(_config_url(open_window_poll))
    assert response.status_code == 200
    assert response.context["editable"] is True
    assert response.context["commune_admin"] is True


# --- creating from a template ("Nouveau scrutin", R-3.6) -------------------


@pytest.fixture
def a_template(db: None) -> PollTemplate:
    return PollTemplate.objects.create(
        name="Approbation à un tour",
        tally_method=TallyMethod.APPROVAL,
        tally_method_version="2",
        require_complete_ranking=False,
        allow_ties_in_ballot=True,
        eligible_list_types=["principale", "complementaire_municipale"],
        languages=["fr", "en"],
    )


def test_the_create_form_is_seeded_from_the_chosen_template(
    admin_client: Client, a_template: PollTemplate
) -> None:
    response = admin_client.get(CREATE_URL, {"modele": str(a_template.pk)})
    initial = response.context["form"].initial
    assert initial["tally_method"] == TallyMethod.APPROVAL
    assert initial["tally_method_version"] == "2"
    assert initial["require_complete_ranking"] is False
    assert initial["allow_ties_in_ballot"] is True
    assert initial["eligible_list_types"] == ["principale", "complementaire_municipale"]
    assert initial["default_language"] == "fr"
    assert initial["extra_languages"] == ["en"]
    # §3.9: no title, description or option seeded — a template carries none.
    assert not initial.get("title_fr")
    assert not initial.get("description_fr")


def test_an_unknown_template_id_404s(admin_client: Client) -> None:
    response = admin_client.get(CREATE_URL, {"modele": "00000000-0000-0000-0000-000000000000"})
    assert response.status_code == 404


def test_creating_from_a_template_carries_the_mechanism_only(
    admin_client: Client, a_template: PollTemplate
) -> None:
    """The poll created still needs title, description and options entered as
    for a blank poll — R-3.6's other half, the mechanism, comes from the
    template."""
    now = timezone.now()
    payload = {
        "opens_at": _dt(now + timedelta(days=1)),
        "closes_at": _dt(now + timedelta(days=8)),
        "paper_entry_deadline": _dt(now + timedelta(days=8)),
        "timezone": "Europe/Paris",
        "tally_method": a_template.tally_method,
        "tally_method_version": a_template.tally_method_version,
        "tiebreak_rule": a_template.tiebreak_rule,
        "eligible_list_types": a_template.eligible_list_types,
        "default_language": "fr",
        "extra_languages": ["en"],
        "title_fr": "Choix du revêtement",
        "description_fr": "Depuis un modèle.",
        "opt-TOTAL_FORMS": "2",
        "opt-INITIAL_FORMS": "0",
        "opt-MIN_NUM_FORMS": "0",
        "opt-MAX_NUM_FORMS": "1000",
        "opt-0-option_id": "a",
        "opt-0-label_fr": "Option A",
        "opt-1-option_id": "b",
        "opt-1-label_fr": "Option B",
    }
    response = admin_client.post(CREATE_URL, payload)
    assert response.status_code == 302
    poll = Poll.objects.get(title_i18n__fr="Choix du revêtement")
    assert poll.tally_method == TallyMethod.APPROVAL
    assert poll.tally_method_version == "2"


# --- screen 13: rename and delete (§6.5.13) ---------------------------------


def test_renaming_a_template(admin_client: Client, a_template: PollTemplate) -> None:
    response = admin_client.post(
        TEMPLATE_URL, {"template": str(a_template.pk), "action": "rename", "name": "Nouveau nom"}
    )
    assert response.status_code == 302
    a_template.refresh_from_db()
    assert a_template.name == "Nouveau nom"

    event = AuditEvent.objects.get(action=Action.TEMPLATE_RENAMED)
    assert event.poll_id is None
    assert event.object_ref == f"polltemplate:{a_template.pk}"
    assert event.after == {"changed": ["name"]}
    # §10, T-55-style restraint: the value itself never rides the event.
    assert "Nouveau nom" not in str(event.before) + str(event.after)


def test_renaming_to_an_existing_name_is_refused(
    admin_client: Client, a_template: PollTemplate
) -> None:
    PollTemplate.objects.create(name="Occupé")
    response = admin_client.post(
        TEMPLATE_URL,
        {"template": str(a_template.pk), "action": "rename", "name": "Occupé"},
        follow=True,
    )
    assert "porte déjà ce nom" in " ".join(_messages(response))
    a_template.refresh_from_db()
    assert a_template.name != "Occupé"


def test_deleting_a_template(admin_client: Client, a_template: PollTemplate) -> None:
    pk = a_template.pk
    response = admin_client.post(TEMPLATE_URL, {"template": str(pk), "action": "delete"})
    assert response.status_code == 302
    assert not PollTemplate.objects.filter(pk=pk).exists()

    event = AuditEvent.objects.get(action=Action.TEMPLATE_DELETED)
    assert event.poll_id is None
    assert event.object_ref == f"polltemplate:{pk}"


def test_deleting_a_template_does_not_affect_a_poll_already_created_from_it(
    admin_client: Client, a_template: PollTemplate
) -> None:
    """§3.9: the fields were copied at creation time, not referenced."""
    now = timezone.now()
    poll = config.create_poll(
        config.ConfigDraft(
            scalars={
                **polltemplates.scalars(a_template),
                "opens_at": now + timedelta(days=1),
                "closes_at": now + timedelta(days=8),
                "paper_entry_deadline": now + timedelta(days=8),
                "timezone": "Europe/Paris",
            },
            languages=list(a_template.languages),
            title_i18n={"fr": "Depuis un modèle bientôt supprimé"},
            description_i18n={"fr": "…"},
            options=[
                config.OptionDraft(option_id="a", labels={"fr": "Option A"}),
                config.OptionDraft(option_id="b", labels={"fr": "Option B"}),
            ],
        ),
        is_sandbox=False,
        actor=User.objects.create_user(username="op", password="x"),
    )
    admin_client.post(TEMPLATE_URL, {"template": str(a_template.pk), "action": "delete"})
    poll.refresh_from_db()
    assert poll.tally_method == TallyMethod.APPROVAL


def test_an_unknown_action_leaves_the_template_untouched(
    admin_client: Client, a_template: PollTemplate
) -> None:
    response = admin_client.post(
        TEMPLATE_URL, {"template": str(a_template.pk), "action": "sabote"}, follow=True
    )
    assert "Action inconnue" in " ".join(_messages(response))
    assert PollTemplate.objects.filter(pk=a_template.pk).exists()


# --- the pure read side ------------------------------------------------------


def test_scalars_is_exactly_the_mechanism_fields(a_template: PollTemplate) -> None:
    values = polltemplates.scalars(a_template)
    assert set(values) == set(polltemplates.TEMPLATE_FIELDS)
    assert "title_i18n" not in values
    assert "description_i18n" not in values
