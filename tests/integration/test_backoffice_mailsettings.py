# SPDX-License-Identifier: 0BSD
"""Screen 12 of §6.5 — paramètres de messagerie (§6.5.12).

Commune-level, so the gate is ``require_commune_admin`` and never a per-poll
role, exactly like screen 10 (``test_backoffice_accounts.py``). Three things
this must get right: the gate; that a save is audited by field name, never by
value, and never the password (§10); and that the relay it saves is really
what mail goes out through afterwards (``apps.core.mailbackend``), with the
environment configuration (§14) as the fallback while nothing is saved.
"""

from __future__ import annotations

import smtplib
from unittest.mock import MagicMock, patch

import pytest
from django.core import mail as django_mail
from django.test import Client, override_settings

from apps.audit.models import Action, AuditEvent
from apps.core.models import MailSettings, User
from apps.core.secretstore import decrypt

MAIL_URL = "/fr/mairie/messagerie/"

SAVE_PAYLOAD = {
    "action": "save",
    "host": "smtp.example.fr",
    "port": "587",
    "encryption": "starttls",
    "username": "mairie",
    "from_email": "mairie@example.fr",
    "raw_password": "un-secret-smtp",
}


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


def _messages(response: object) -> list[str]:
    return [str(m) for m in response.context["messages"]]  # type: ignore[attr-defined]


# --- the gate (§3.7) --------------------------------------------------------


def test_anonymous_is_sent_to_the_login_page(client: Client, db: None) -> None:
    response = client.get(MAIL_URL)
    assert response.status_code == 302
    assert "/mairie/connexion/" in response["Location"]


def test_a_plain_operator_is_refused(client: Client, plain_operator: User) -> None:
    """A per-poll role, even every per-poll role, is not commune-level (§3.7)."""
    client.force_login(plain_operator)
    assert client.get(MAIL_URL).status_code == 403


def test_a_superuser_flag_is_not_consulted(client: Client, db: None) -> None:
    stray = User.objects.create_user(username="root", password="x")
    stray.is_superuser = True
    stray.is_staff = True
    stray.save(update_fields=["is_superuser", "is_staff"])
    client.force_login(stray)
    assert client.get(MAIL_URL).status_code == 403


def test_a_commune_admin_reaches_the_screen(admin_client: Client) -> None:
    assert admin_client.get(MAIL_URL).status_code == 200


# --- saving (§6.5.12, §10) --------------------------------------------------


def test_saving_persists_settings_and_encrypts_the_password(admin_client: Client) -> None:
    admin_client.post(MAIL_URL, SAVE_PAYLOAD)
    config = MailSettings.current()
    assert config is not None
    assert config.host == "smtp.example.fr"
    assert config.port == 587
    assert config.encryption == "starttls"
    assert config.username == "mairie"
    assert config.from_email == "mairie@example.fr"
    assert "un-secret-smtp" not in config.password_encrypted
    assert decrypt(config.password_encrypted) == "un-secret-smtp"


def test_saving_writes_the_audit_event_naming_fields_not_values(admin_client: Client) -> None:
    # port (587) and encryption (starttls) already match MailSettings' own
    # defaults on a first save, so they do not register as "changed" — the
    # other four fields have no default and do.
    admin_client.post(MAIL_URL, SAVE_PAYLOAD)
    event = AuditEvent.objects.get(action=Action.MAIL_SETTINGS_CHANGED)
    assert event.poll_id is None
    assert event.object_ref == "mailsettings:1"
    assert set(event.after["changed"]) == {"host", "username", "from_email", "password"}
    dumped = str(event.before) + str(event.after)
    assert "un-secret-smtp" not in dumped
    assert "smtp.example.fr" not in dumped


def test_changing_port_and_encryption_is_named_in_the_audit_event(admin_client: Client) -> None:
    payload = {**SAVE_PAYLOAD, "port": "465", "encryption": "ssl"}
    admin_client.post(MAIL_URL, payload)
    event = AuditEvent.objects.get(action=Action.MAIL_SETTINGS_CHANGED)
    assert {"port", "encryption"} <= set(event.after["changed"])


def test_a_blank_password_on_resave_keeps_the_stored_one(admin_client: Client) -> None:
    admin_client.post(MAIL_URL, SAVE_PAYLOAD)
    payload = {**SAVE_PAYLOAD, "raw_password": "", "host": "smtp2.example.fr"}
    admin_client.post(MAIL_URL, payload)
    config = MailSettings.current()
    assert config is not None
    assert config.host == "smtp2.example.fr"
    assert decrypt(config.password_encrypted) == "un-secret-smtp"


def test_a_resave_with_no_changes_writes_no_second_event(admin_client: Client) -> None:
    admin_client.post(MAIL_URL, SAVE_PAYLOAD)
    admin_client.post(MAIL_URL, {**SAVE_PAYLOAD, "raw_password": ""})
    assert AuditEvent.objects.filter(action=Action.MAIL_SETTINGS_CHANGED).count() == 1


def test_an_out_of_range_port_is_refused(admin_client: Client) -> None:
    admin_client.post(MAIL_URL, {**SAVE_PAYLOAD, "port": "99999"})
    assert MailSettings.current() is None


# --- routing mail through what was saved, and the fallback (§14) -----------


@override_settings(EMAIL_BACKEND="apps.core.mailbackend.ConfigurableEmailBackend")
def test_unconfigured_mail_falls_back_to_the_environment_backend(db: None) -> None:
    """No ``MailSettings`` row: mail still goes through
    ``EMAIL_FALLBACK_BACKEND`` — locmem in tests — exactly as before screen 12
    existed. ``EMAIL_BACKEND`` restored here for the same reason as the test
    above: ``setup_test_environment`` otherwise forces locmem directly,
    which would pass even if ``ConfigurableEmailBackend`` never ran at all."""
    assert MailSettings.current() is None
    sent = django_mail.send_mail("Sujet", "Corps", "expediteur@example.fr", ["a@example.fr"])
    assert sent == 1
    assert django_mail.outbox[0].subject == "Sujet"


@override_settings(EMAIL_BACKEND="apps.core.mailbackend.ConfigurableEmailBackend")
def test_configured_mail_routes_through_the_saved_relay(admin_client: Client) -> None:
    """``setup_test_environment`` forces ``EMAIL_BACKEND`` to locmem for every
    test (so a bug can never actually dial out) — restored here, for this one
    test, to exercise the routing decision itself; ``smtplib.SMTP`` stays
    mocked, so nothing really goes over the network either way."""
    admin_client.post(MAIL_URL, SAVE_PAYLOAD)
    with patch("smtplib.SMTP") as smtp_cls:
        smtp_cls.return_value = MagicMock()
        sent = django_mail.send_mail("Sujet", "Corps", "expediteur@example.fr", ["a@example.fr"])
    assert sent == 1
    # Nothing lands in the in-memory outbox: it really went through smtplib,
    # not the fallback backend.
    assert django_mail.outbox == []
    smtp_cls.return_value.login.assert_called_once_with("mairie", "un-secret-smtp")


# --- the test-send action (§6.5.12, §14) ------------------------------------


def test_test_send_before_saving_is_refused(admin_client: Client) -> None:
    response = admin_client.post(
        MAIL_URL, {"action": "test", "recipient": "verif@example.fr"}, follow=True
    )
    assert any("Enregistrez d" in m for m in _messages(response))


def test_a_successful_test_send(admin_client: Client) -> None:
    admin_client.post(MAIL_URL, SAVE_PAYLOAD)
    with patch("smtplib.SMTP") as smtp_cls:
        smtp_cls.return_value = MagicMock()
        response = admin_client.post(
            MAIL_URL, {"action": "test", "recipient": "verif@example.fr"}, follow=True
        )
    assert any("Message de test envoyé" in m for m in _messages(response))
    smtp_cls.return_value.login.assert_called_once_with("mairie", "un-secret-smtp")
    smtp_cls.return_value.sendmail.assert_called_once()


def test_a_failed_test_send_shows_the_smtp_error(admin_client: Client) -> None:
    admin_client.post(MAIL_URL, SAVE_PAYLOAD)
    with patch("smtplib.SMTP") as smtp_cls:
        instance = MagicMock()
        instance.login.side_effect = smtplib.SMTPAuthenticationError(535, b"identifiants refuses")
        smtp_cls.return_value = instance
        response = admin_client.post(
            MAIL_URL, {"action": "test", "recipient": "verif@example.fr"}, follow=True
        )
    assert any("chec de l" in m for m in _messages(response))
    # The failed test send itself writes nothing (§10): only the one event
    # from the save above, none from the attempt that followed it. The
    # message is a raw smtplib error, exactly the free text `reason` exists
    # to keep out of the audit log.
    assert AuditEvent.objects.filter(action=Action.MAIL_SETTINGS_CHANGED).count() == 1
