# SPDX-License-Identifier: 0BSD
"""``settings.EMAIL_BACKEND``, in every environment (§6.5.12, §14).

Django's mail settings are process-wide, read once at start-up from the
environment (§15) — a relay that needs re-tuning after go-live otherwise means
a config change and a restart, with ops in the loop for something the mairie
should be able to fix itself between two confirmation mails. This backend
checks ``MailSettings`` on every send instead of once at start-up: present, it
opens a plain SMTP connection with those values; absent, it defers entirely to
``settings.EMAIL_FALLBACK_BACKEND`` — the value each environment file used to
put directly in ``EMAIL_BACKEND`` before screen 12 existed. An adopting
commune with working environment configuration is therefore unaffected until
an admin deliberately fills the screen in.
"""

from __future__ import annotations

from collections.abc import Sequence

from django.conf import settings
from django.core.mail import get_connection
from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail.backends.smtp import EmailBackend as SMTPBackend
from django.core.mail.message import EmailMessage

from .models import MailEncryption, MailSettings


def connection_for(config: MailSettings, *, fail_silently: bool = False) -> SMTPBackend:
    """A plain SMTP connection built from one ``MailSettings`` row.

    Shared by ``ConfigurableEmailBackend`` below and by screen 12's "envoyer un
    message de test" action (``apps.backoffice.mailsettings.send_test``), so
    the two ways of reaching the relay can never disagree about how a saved
    row turns into connection parameters.
    """
    return SMTPBackend(
        host=config.host,
        port=config.port,
        username=config.username,
        password=config.get_password(),
        use_tls=config.encryption == MailEncryption.STARTTLS,
        use_ssl=config.encryption == MailEncryption.SSL,
        fail_silently=fail_silently,
    )


def default_from_email() -> str:
    """The ``From:`` address mail goes out under.

    Screen 12's value overrides ``settings.DEFAULT_FROM_EMAIL`` where an admin
    has set one, since it usually has to match the authenticated account; the
    deployment default (§15) still holds otherwise.
    """
    config = MailSettings.current()
    if config is not None and config.from_email:
        return config.from_email
    return settings.DEFAULT_FROM_EMAIL


class ConfigurableEmailBackend(BaseEmailBackend):
    """Routes to the DB-configured relay where screen 12 has one, else to the
    environment configuration every deployment already had (§14)."""

    def send_messages(self, email_messages: Sequence[EmailMessage]) -> int:
        config = MailSettings.current()
        if config is not None and config.host:
            connection: BaseEmailBackend = connection_for(config, fail_silently=self.fail_silently)
        else:
            connection = get_connection(
                backend=settings.EMAIL_FALLBACK_BACKEND, fail_silently=self.fail_silently
            )
        return connection.send_messages(email_messages) or 0
