# SPDX-License-Identifier: 0BSD
"""Screen 12 — paramètres de messagerie (§6.5.12).

Commune-level, like screen 10: it goes through ``require_commune_admin``, not
``require_poll_role``, because an SMTP relay serves every poll, not one.

Two actions. ``save`` writes the relay settings and logs which fields moved —
never their values, and never the password, the same restraint §10 applies to
poll configuration (``elections.config.save_configuration``). ``send_test``
sends a real message through the settings already saved, so a mistyped host or
a stale password shows up here rather than days later as a confirmation mail
nobody received (§14's own advice to test-send before opening a poll, now
reachable from the screen that sets the relay up). It is deliberately not on
§10's minimum list — like ``accounts.set_password``, the interesting content
would be a raw smtplib/socket error message, exactly the free text ``reason``
exists to keep out of the log.
"""

from __future__ import annotations

import smtplib
from dataclasses import dataclass

from django.core.mail import EmailMessage
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from apps.audit import services as audit
from apps.audit.models import Action
from apps.core import mailbackend
from apps.core.models import MailSettings, User

#: The fields a save can change, and the only names ``save``'s audit event
#: ever names (§10) — never a value, and never the password.
_FIELDS = ("host", "port", "encryption", "username", "from_email")


class TestSendFailed(Exception):
    """The test send could not reach or authenticate to the relay. ``str(self)``
    is smtplib's or socket's own message, shown to the admin as-is."""


@dataclass(frozen=True)
class MailSettingsDraft:
    """A validated screen-12 submission, ready to apply. ``raw_password``
    blank means "keep the password already stored" — the form never
    redisplays it, so there is nothing to resubmit unless it is changing."""

    host: str
    port: int
    encryption: str
    username: str
    from_email: str
    raw_password: str = ""


def current() -> MailSettings | None:
    return MailSettings.current()


@transaction.atomic
def save(draft: MailSettingsDraft, *, actor: User) -> MailSettings:
    """Apply a screen-12 edit and log which fields changed (§10)."""
    config = MailSettings.objects.select_for_update().filter(pk=1).first() or MailSettings(pk=1)
    changed = {name for name in _FIELDS if getattr(config, name) != getattr(draft, name)}
    for name in _FIELDS:
        setattr(config, name, getattr(draft, name))
    if draft.raw_password:
        config.set_password(draft.raw_password)
        changed.add("password")
    config.save()
    if changed:
        audit.record(
            action=Action.MAIL_SETTINGS_CHANGED,
            poll=None,
            actor=actor,
            object_ref=audit.ref(config),
            after={"changed": sorted(changed)},
        )
    return config


def send_test(config: MailSettings, *, recipient: str) -> None:
    """Screen 12's "envoyer un message de test" action, against the settings
    already saved. Raises ``TestSendFailed`` on any connection, authentication
    or delivery error rather than swallowing it (``fail_silently=False``) —
    the whole point of checking from here is to see the real error."""
    connection = mailbackend.connection_for(config, fail_silently=False)
    message = EmailMessage(
        subject=_("Message de test — espace mairie"),
        body=_(
            "Ceci est un message de test envoyé depuis les paramètres de "
            "messagerie de l'espace mairie. Si vous le recevez, le serveur "
            "SMTP configuré est joignable et accepte ces identifiants."
        ),
        from_email=mailbackend.default_from_email(),
        to=[recipient],
        connection=connection,
    )
    try:
        sent = message.send()
    except (OSError, smtplib.SMTPException) as exc:
        raise TestSendFailed(str(exc)) from exc
    if not sent:
        raise TestSendFailed(str(_("L'envoi a échoué sans message d'erreur du serveur.")))
