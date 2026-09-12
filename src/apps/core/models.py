# SPDX-License-Identifier: 0BSD
"""Accounts, roles, job runs, and the commune record.

``User`` is a named operator account (R-2.2): shared logins are the thing the
audit log cannot survive, so there is no anonymous or generic account anywhere.
Roles are assigned per poll (R-2.1) except ``commune_admin``, which is a flag on
the account itself.

``Commune`` is the one commune this instance serves (R-1.3, R-1.5) and the
data-controller identity its notices carry (R-13.1, R-13.2). It is created by
the first-run wizard (§6.5.11) alongside the initial administrator, and edited
afterwards from screen 14 (§6.5.14).

``MailSettings`` is the commune's SMTP relay, configured from screen 12
(§6.5.12) instead of only the environment (§14): deliverability is the most
fragile dependency in the design, and tuning it is a task for after go-live,
per commune, which an env-var restart cannot do without ops help.
"""

from __future__ import annotations

import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _

from . import images, secretstore


def commune_logo_path(instance: Commune, filename: str) -> str:
    """Content-addressed, like an option's image (R-3.12,
    ``apps.elections.models.option_image_path``): a changed logo gets a new
    URL, so a browser that already cached the old one under its old name is
    never left showing it. ``instance.logo_content_hash`` and
    ``.logo_content_type`` are set by ``apps.backoffice.communesettings.set_logo``
    before it calls ``instance.logo.save(...)``, which is what invokes this."""
    ext = images.EXTENSIONS[instance.logo_content_type]
    return f"commune/logo-{instance.logo_content_hash}{ext}"


def commune_favicon_path(instance: Commune, filename: str) -> str:
    """The favicon's counterpart to ``commune_logo_path`` above."""
    ext = images.EXTENSIONS[instance.favicon_content_type]
    return f"commune/favicon-{instance.favicon_content_hash}{ext}"


class Commune(models.Model):
    """The single commune this instance serves, and the details R-13 requires
    its public notices to carry.

    One instance is one commune (R-1.3, R-1.5), so this is one row: ``id`` is
    pinned to ``1`` and a check constraint holds it there, which is what lets
    ``Commune.current()`` be unambiguous without a "get the latest" convention.
    The row is created by the first-run wizard (§6.5.11) so that an adopting
    commune never edits the source to name itself; screen 14 (§6.5.14,
    ``apps.backoffice.communesettings``) is the only writer afterwards, the
    deferred-configuration items of §13 — the data-protection referent above
    all — being what the record exists to hold.
    """

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    name = models.CharField(
        _("nom de la commune"),
        max_length=200,
        help_text=_("Tel qu'il doit apparaître sur les pages publiques et dans la notice."),
    )
    # R-13.1: the commune is the data controller. R-13.2: the information notice
    # names the referent who answers access, rectification and erasure requests.
    # The stored values are a proper noun and a contact string, the same in
    # every language, so these are plain fields with no per-language variant
    # (contrast the poll's title_i18n) — only the labels are translated.
    data_protection_referent = models.CharField(
        _("référent données personnelles"),
        max_length=200,
        help_text=_(
            "Personne ou service à qui les électeurs adressent leurs demandes "
            "d'accès, de rectification et d'effacement (R-13.2)."
        ),
    )
    data_protection_contact = models.CharField(
        _("contact du référent"),
        max_length=300,
        help_text=_("Adresse électronique ou postale, publiée dans la notice d'information."),
    )
    # Links in outgoing mail (§6.2 step 7) need an absolute address, and a
    # management command sending reminders has no request to read a host from
    # (apps.registrations.mail._absolute). Blank means "use the deployment's own
    # DJANGO_PUBLIC_BASE_URL (§14, §15)" — the same additive fallback screen 12
    # gives MailSettings — so an adopting commune whose Ansible deploy already
    # sets it is unaffected until an admin fills this field in from screen 14.
    public_base_url = models.CharField(
        _("adresse du site"),
        max_length=200,
        blank=True,
        default="",
        help_text=_(
            "Ex. : https://votecommune.fr — sans barre oblique finale. Utilisée pour "
            "composer les liens des courriels envoyés aux électeurs. Laissez vide pour "
            "utiliser l'adresse configurée au déploiement."
        ),
    )
    # §6.5.14, both optional — shown in the page header in place of the plain
    # commune name, and as the browser-tab icon, where one is set. Uploaded and
    # removed through apps.backoffice.communesettings, never through this form
    # directly: unlike the text fields above, a blank file input does not mean
    # "keep the current one" the way a blank password does on screen 12, so the
    # write path needs an explicit remove action, not a diff against a posted
    # value (§10, R-14.1: an ``alt`` naming the commune, not the file, follows
    # from the name field already required above).
    logo = models.FileField(_("logo"), upload_to=commune_logo_path, blank=True, default="")
    logo_content_type = models.CharField(max_length=40, blank=True, default="")
    logo_content_hash = models.CharField(max_length=64, blank=True, default="")
    favicon = models.FileField(_("favicon"), upload_to=commune_favicon_path, blank=True, default="")
    favicon_content_type = models.CharField(max_length=40, blank=True, default="")
    favicon_content_hash = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        verbose_name = _("commune")
        verbose_name_plural = _("commune")
        constraints = [
            models.CheckConstraint(condition=models.Q(id=1), name="commune_is_singleton"),
        ]

    def __str__(self) -> str:
        return self.name

    @classmethod
    def current(cls) -> Commune | None:
        """The commune record, or ``None`` before first-run has created it."""
        return cls.objects.filter(pk=1).first()


class MailEncryption(models.TextChoices):
    NONE = "none", _("aucun")
    STARTTLS = "starttls", _("STARTTLS")
    SSL = "ssl", _("SSL/TLS implicite")


class MailSettings(models.Model):
    """The commune's SMTP relay (§6.5.12). One instance, one relay: ``id`` is
    pinned to ``1`` exactly like ``Commune`` above, for the same reason —
    ``MailSettings.current()`` is unambiguous with no "get the latest"
    convention.

    Absent (no row at all) means "use the environment configuration of §14 /
    §15" — ``apps.core.mailbackend`` falls back to it, so an adopting commune
    whose Ansible deploy already sets ``DJANGO_EMAIL_HOST`` keeps working
    unchanged until an admin deliberately fills this screen in.

    The password is the one secret this database stores reversibly rather
    than hashed (contrast every operator password, §14) — an SMTP relay needs
    it back in plaintext to authenticate — so it is never stored directly.
    ``set_password``/``get_password`` are the only way in or out, through
    ``apps.core.secretstore``; nothing else on this model, and no template,
    ever sees ``password_encrypted``.
    """

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    host = models.CharField(_("serveur SMTP"), max_length=255)
    port = models.PositiveIntegerField(_("port"), default=587)
    encryption = models.CharField(
        _("chiffrement"),
        max_length=10,
        choices=MailEncryption.choices,
        default=MailEncryption.STARTTLS,
    )
    username = models.CharField(_("identifiant"), max_length=255, blank=True)
    password_encrypted = models.TextField(_("mot de passe (chiffré)"), blank=True, default="")
    from_email = models.EmailField(
        _("adresse d'expédition"),
        blank=True,
        help_text=_(
            "Laissez vide pour utiliser l'adresse par défaut du déploiement. Doit "
            "généralement correspondre au compte authentifié auprès du serveur."
        ),
    )
    updated_at = models.DateTimeField(_("dernière modification"), auto_now=True)

    class Meta:
        verbose_name = _("paramètres de messagerie")
        verbose_name_plural = _("paramètres de messagerie")
        constraints = [
            models.CheckConstraint(condition=models.Q(id=1), name="mail_settings_is_singleton"),
        ]

    def __str__(self) -> str:
        return self.host or str(_("(non configuré)"))

    @classmethod
    def current(cls) -> MailSettings | None:
        """The saved relay settings, or ``None`` where none have been saved —
        the signal ``mailbackend`` reads to fall back to the environment."""
        return cls.objects.filter(pk=1).first()

    def set_password(self, raw_password: str) -> None:
        """Encrypts and stores. Does not save the row — callers already do,
        alongside the other fields, in one write (``mailsettings.save``)."""
        self.password_encrypted = secretstore.encrypt(raw_password) if raw_password else ""

    def get_password(self) -> str:
        """The plaintext password, decrypted on demand for one SMTP
        connection. Raises ``secretstore.SecretUnreadable`` if ``SECRET_KEY``
        has changed since it was saved — a re-entry, not a silent empty
        password reaching the relay as an anonymous login attempt."""
        return secretstore.decrypt(self.password_encrypted) if self.password_encrypted else ""


class User(AbstractUser):
    """A named account. First one created by the first-run wizard (§6.5.11)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    is_commune_admin = models.BooleanField(
        _("administrateur de la commune"),
        default=False,
        help_text=_("Gère les comptes et crée les scrutins."),
    )
    full_name = models.CharField(_("nom complet"), max_length=200, blank=True)

    class Meta:
        verbose_name = _("compte")
        verbose_name_plural = _("comptes")

    def __str__(self) -> str:
        return self.full_name or self.get_username()


class Role(models.TextChoices):
    POLL_ADMIN = "poll_admin", _("administrateur du scrutin")
    ENTRY_OPERATOR = "entry_operator", _("opérateur de saisie")
    AUDITOR = "auditor", _("auditeur")


class PollRole(models.Model):
    """A per-poll role assignment (R-2.1). Every grant is audited (§10)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    poll = models.ForeignKey("elections.Poll", on_delete=models.CASCADE, related_name="roles")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="poll_roles")
    role = models.CharField(max_length=20, choices=Role.choices)
    granted_at = models.DateTimeField(auto_now_add=True)
    granted_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="granted_roles", null=True, blank=True
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["poll", "user", "role"], name="uniq_poll_user_role")
        ]

    def __str__(self) -> str:
        return f"{self.user} — {self.get_role_display()}"


class JobRun(models.Model):
    """One row per management-command run (§14, self-locking commands).

    The lock is a row here rather than only a ``flock`` file, so that a job is
    observable after the fact and a second instance started by cron while the
    first is still running exits 0 without acting (T-49, T-51).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    command = models.CharField(max_length=50, db_index=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    succeeded = models.BooleanField(null=True)
    detail = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [models.Index(fields=["command", "started_at"])]

    def __str__(self) -> str:
        return f"{self.command} @ {self.started_at:%Y-%m-%d %H:%M}"
