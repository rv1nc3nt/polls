# SPDX-License-Identifier: 0BSD
"""Screen 14 of §6.5 — paramètres de la commune (§6.5.14).

Commune-level, so the gate is ``require_commune_admin`` and never a per-poll
role, exactly like screens 10, 12 and 13. Three things this must get right:
the gate; that a save is audited by field name, never by value (§10); and that
``public_base_url`` really is what ``apps.registrations.mail`` builds links
from afterwards, with the deployment's own configuration (§15) as the
fallback while nothing is saved — see ``test_registration_mail.py`` for that
half.
"""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.audit.models import Action, AuditEvent
from apps.core.models import Commune, User

SETTINGS_URL = "/fr/mairie/commune/"
LOGO_URL = "/fr/mairie/commune/logo/"
LOGO_REMOVE_URL = "/fr/mairie/commune/logo/supprimer/"
FAVICON_URL = "/fr/mairie/commune/favicon/"
FAVICON_REMOVE_URL = "/fr/mairie/commune/favicon/supprimer/"

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
ICO_BYTES = b"\x00\x00\x01\x00" + b"\x00" * 32

SAVE_PAYLOAD = {
    "name": "Sainte-Marie-du-Mont",
    "data_protection_referent": "Secrétariat de mairie",
    "data_protection_contact": "rgpd@sainte-marie-du-mont.example.fr",
    "public_base_url": "https://vote.sainte-marie-du-mont.example.fr",
}


@pytest.fixture
def commune(db: None) -> Commune:
    return Commune.objects.create(
        name="Sainte-Marie-du-Mont",
        data_protection_referent="Secrétariat de mairie",
        data_protection_contact="rgpd@sainte-marie-du-mont.example.fr",
    )


@pytest.fixture
def commune_admin(commune: Commune) -> User:
    return User.objects.create_user(
        username="c.admin", password="x", full_name="C. Admin", is_commune_admin=True
    )


@pytest.fixture
def plain_operator(commune: Commune) -> User:
    return User.objects.create_user(username="m.durand", password="x", full_name="M. Durand")


@pytest.fixture
def admin_client(client: Client, commune_admin: User) -> Client:
    client.force_login(commune_admin)
    return client


def _messages(response: object) -> list[str]:
    return [str(m) for m in response.context["messages"]]  # type: ignore[attr-defined]


# --- the gate (§3.7) --------------------------------------------------------


def test_anonymous_is_sent_to_the_login_page(client: Client, commune: Commune) -> None:
    response = client.get(SETTINGS_URL)
    assert response.status_code == 302
    assert "/mairie/connexion/" in response["Location"]


def test_a_plain_operator_is_refused(client: Client, plain_operator: User) -> None:
    client.force_login(plain_operator)
    assert client.get(SETTINGS_URL).status_code == 403


def test_a_superuser_flag_is_not_consulted(client: Client, commune: Commune) -> None:
    stray = User.objects.create_user(username="root", password="x")
    stray.is_superuser = True
    stray.is_staff = True
    stray.save(update_fields=["is_superuser", "is_staff"])
    client.force_login(stray)
    assert client.get(SETTINGS_URL).status_code == 403


def test_a_commune_admin_reaches_the_screen(admin_client: Client) -> None:
    assert admin_client.get(SETTINGS_URL).status_code == 200


# --- saving (§6.5.14, §10) --------------------------------------------------


def test_saving_persists_the_fields(admin_client: Client, commune: Commune) -> None:
    admin_client.post(SETTINGS_URL, SAVE_PAYLOAD)
    commune.refresh_from_db()
    assert commune.data_protection_contact == "rgpd@sainte-marie-du-mont.example.fr"
    assert commune.public_base_url == "https://vote.sainte-marie-du-mont.example.fr"


def test_a_trailing_slash_is_stripped(admin_client: Client, commune: Commune) -> None:
    payload = {**SAVE_PAYLOAD, "public_base_url": "https://vote.example.fr/"}
    admin_client.post(SETTINGS_URL, payload)
    commune.refresh_from_db()
    assert commune.public_base_url == "https://vote.example.fr"


def test_a_blank_address_is_accepted_and_means_use_the_deployment_default(
    admin_client: Client, commune: Commune
) -> None:
    payload = {**SAVE_PAYLOAD, "public_base_url": ""}
    response = admin_client.post(SETTINGS_URL, payload)
    assert response.status_code == 302
    commune.refresh_from_db()
    assert commune.public_base_url == ""


def test_a_malformed_address_is_refused(admin_client: Client, commune: Commune) -> None:
    payload = {**SAVE_PAYLOAD, "public_base_url": "pas-une-url"}
    admin_client.post(SETTINGS_URL, payload)
    commune.refresh_from_db()
    assert commune.public_base_url == ""


def test_saving_writes_the_audit_event_naming_fields_not_values(
    admin_client: Client, commune: Commune
) -> None:
    admin_client.post(SETTINGS_URL, SAVE_PAYLOAD)
    event = AuditEvent.objects.get(action=Action.COMMUNE_SETTINGS_CHANGED)
    assert event.poll_id is None
    assert event.object_ref == "commune:1"
    assert set(event.after["changed"]) == {"public_base_url"}
    dumped = str(event.before) + str(event.after)
    assert "vote.sainte-marie-du-mont.example.fr" not in dumped


def test_a_resave_with_no_changes_writes_no_event(admin_client: Client) -> None:
    admin_client.post(SETTINGS_URL, SAVE_PAYLOAD)
    admin_client.post(SETTINGS_URL, SAVE_PAYLOAD)
    assert AuditEvent.objects.filter(action=Action.COMMUNE_SETTINGS_CHANGED).count() == 1


# --- logo and favicon (§6.5.14, both optional) ------------------------------


def test_the_gate_applies_to_the_logo_and_favicon_endpoints_too(
    client: Client, plain_operator: User
) -> None:
    client.force_login(plain_operator)
    upload = SimpleUploadedFile("logo.png", PNG_BYTES, content_type="image/png")
    assert client.post(LOGO_URL, {"logo": upload}).status_code == 403
    assert client.post(LOGO_REMOVE_URL).status_code == 403
    assert client.post(FAVICON_URL, {"favicon": upload}).status_code == 403
    assert client.post(FAVICON_REMOVE_URL).status_code == 403


def test_uploading_a_logo_persists_it_and_serves_it_back(
    admin_client: Client, commune: Commune
) -> None:
    upload = SimpleUploadedFile("logo.png", PNG_BYTES, content_type="image/png")
    response = admin_client.post(LOGO_URL, {"logo": upload}, follow=True)
    assert any("Logo mis à jour" in m for m in _messages(response))
    commune.refresh_from_db()
    assert commune.logo.name
    assert commune.logo.name.endswith(".png")
    assert commune.logo_content_type == "image/png"


def test_uploading_a_favicon_accepts_ico(admin_client: Client, commune: Commune) -> None:
    upload = SimpleUploadedFile("icon.ico", ICO_BYTES, content_type="image/x-icon")
    admin_client.post(FAVICON_URL, {"favicon": upload})
    commune.refresh_from_db()
    assert commune.favicon.name is not None
    assert commune.favicon.name.endswith(".ico")
    assert commune.favicon_content_type == "image/x-icon"


def test_an_oversized_logo_is_refused(admin_client: Client, commune: Commune) -> None:
    from apps.backoffice import communesettings

    oversized = b"\x89PNG\r\n\x1a\n" + b"\x00" * communesettings.MAX_LOGO_SIZE
    upload = SimpleUploadedFile("logo.png", oversized, content_type="image/png")
    response = admin_client.post(LOGO_URL, {"logo": upload}, follow=True)
    assert any("volumineuse" in m for m in _messages(response))
    commune.refresh_from_db()
    assert not commune.logo


def test_an_unrecognised_format_is_refused(admin_client: Client, commune: Commune) -> None:
    upload = SimpleUploadedFile("logo.txt", b"not an image", content_type="image/png")
    response = admin_client.post(LOGO_URL, {"logo": upload}, follow=True)
    assert any("non reconnu" in m for m in _messages(response))
    commune.refresh_from_db()
    assert not commune.logo


def test_an_svg_is_refused_despite_the_declared_content_type(
    admin_client: Client, commune: Commune
) -> None:
    """§14: no sanitiser exists here to strip a `<script>` from an uploaded
    SVG before serving it back, so SVG is never a recognised format."""
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>1</script></svg>'
    upload = SimpleUploadedFile("logo.svg", svg, content_type="image/svg+xml")
    admin_client.post(LOGO_URL, {"logo": upload})
    commune.refresh_from_db()
    assert not commune.logo


def test_replacing_a_logo_deletes_the_previous_file(admin_client: Client, commune: Commune) -> None:
    first = SimpleUploadedFile("a.png", PNG_BYTES, content_type="image/png")
    admin_client.post(LOGO_URL, {"logo": first})
    commune.refresh_from_db()
    storage = commune.logo.storage
    old_name = commune.logo.name
    assert old_name is not None

    second = SimpleUploadedFile("b.png", PNG_BYTES + b"\x01", content_type="image/png")
    admin_client.post(LOGO_URL, {"logo": second})
    commune.refresh_from_db()
    assert commune.logo.name != old_name
    assert not storage.exists(old_name)


def test_removing_a_logo_deletes_the_file_and_clears_the_field(
    admin_client: Client, commune: Commune
) -> None:
    upload = SimpleUploadedFile("logo.png", PNG_BYTES, content_type="image/png")
    admin_client.post(LOGO_URL, {"logo": upload})
    commune.refresh_from_db()
    storage = commune.logo.storage
    name = commune.logo.name
    assert name is not None

    response = admin_client.post(LOGO_REMOVE_URL, follow=True)
    assert any("Logo supprimé" in m for m in _messages(response))
    commune.refresh_from_db()
    assert not commune.logo
    assert commune.logo_content_type == ""
    assert not storage.exists(name)


def test_removing_an_absent_logo_is_a_harmless_no_op(
    admin_client: Client, commune: Commune
) -> None:
    admin_client.post(LOGO_REMOVE_URL)
    assert not AuditEvent.objects.filter(action=Action.COMMUNE_BRANDING_REMOVED).exists()


def test_logo_and_favicon_uploads_are_audited_by_field_not_value(
    admin_client: Client, commune: Commune
) -> None:
    upload = SimpleUploadedFile("logo.png", PNG_BYTES, content_type="image/png")
    admin_client.post(LOGO_URL, {"logo": upload})
    event = AuditEvent.objects.get(action=Action.COMMUNE_BRANDING_CHANGED)
    assert event.poll_id is None
    assert event.object_ref == "commune:1"
    assert event.after == {"field": "logo"}


def test_the_favicon_is_independent_of_the_logo(admin_client: Client, commune: Commune) -> None:
    logo = SimpleUploadedFile("logo.png", PNG_BYTES, content_type="image/png")
    favicon = SimpleUploadedFile("icon.ico", ICO_BYTES, content_type="image/x-icon")
    admin_client.post(LOGO_URL, {"logo": logo})
    admin_client.post(FAVICON_URL, {"favicon": favicon})
    admin_client.post(LOGO_REMOVE_URL, follow=True)
    commune.refresh_from_db()
    assert not commune.logo
    assert commune.favicon.name is not None
    assert commune.favicon.name.endswith(".ico")
