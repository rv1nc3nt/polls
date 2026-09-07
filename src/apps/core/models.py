# SPDX-License-Identifier: 0BSD
"""Accounts, roles and job runs.

``User`` is a named operator account (R-2.2): shared logins are the thing the
audit log cannot survive, so there is no anonymous or generic account anywhere.
Roles are assigned per poll (R-2.1) except ``commune_admin``, which is a flag on
the account itself.
"""

from __future__ import annotations

import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _


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
