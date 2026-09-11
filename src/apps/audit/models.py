# SPDX-License-Identifier: 0BSD
"""The audit log (§10, R-12).

Reference-only, decided before the model was written and not retrofittable:
an event stores a *reference* and non-identifying state, never a copied personal
value. ``object_ref`` names the row; ``before``/``after`` hold state, channel,
status, role and rankings by option id. No elector's name, date of birth or
email is ever written here (T-55).

The identity therefore lives only in the referenced row, which the retention job
deletes (§11). Afterwards the log still reads *registration 7f3a… moved
pending_review → active, by operator M, at T, reason name_divergence_accepted* —
a complete record of what was done, with no way to recover to whom. That lets
INV-3 stay absolute: no update or delete path to this table at all, in the
application or in the database, and so no exception for the purge to be granted.

A dangling reference is expected, not an error: the audit screen renders it as
*objet supprimé (rétention)*.
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class Action(models.TextChoices):
    """The vocabulary of §10's minimum list. Extend deliberately."""

    POLL_CREATED = "poll_created", _("scrutin créé")
    POLL_CONFIG_CHANGED = "poll_config_changed", _("configuration modifiée")
    POLL_STATE_CHANGED = "poll_state_changed", _("transition d'état")
    POLL_CLOSES_AT_EXTENDED = "poll_closes_at_extended", _("clôture repoussée")
    ROLL_IMPORTED = "roll_imported", _("liste électorale importée")
    ROLL_SNAPSHOT_TAKEN = "roll_snapshot_taken", _("copie figée prise")
    REGISTRATION_REVIEWED = "registration_reviewed", _("inscription examinée")
    REGISTRATION_DUPLICATE = "registration_duplicate", _("tentative de doublon d'inscription")
    REGISTRATION_INELIGIBLE = (
        "registration_ineligible",
        _("inscription refusée : type de liste non autorisé"),
    )
    PAPER_BALLOT_CREATED = "paper_ballot_created", _("bulletin papier saisi")
    PAPER_BALLOT_CORRECTED = "paper_ballot_corrected", _("bulletin papier rectifié")
    PAPER_BALLOT_DELETED = "paper_ballot_deleted", _("bulletin papier supprimé")
    PAPER_BALLOT_COUNTERSIGNED = "paper_ballot_countersigned", _("bulletin contresigné")
    CHANNEL_COLLISION_OVERRIDE = "channel_collision_override", _("collision de canal forcée")
    CLOSURE_OVERRIDE = "closure_override", _("clôture forcée")
    TALLY_RUN = "tally_run", _("dépouillement effectué")
    TIEBREAK_ENTERED = "tiebreak_entered", _("tirage au sort physique saisi")
    RESULTS_PUBLISHED = "results_published", _("résultats publiés")
    ROLE_ASSIGNED = "role_assigned", _("rôle attribué")
    ROLE_REVOKED = "role_revoked", _("rôle retiré")
    MAIL_SETTINGS_CHANGED = "mail_settings_changed", _("paramètres de messagerie modifiés")
    TEMPLATE_CREATED = "template_created", _("modèle enregistré")
    TEMPLATE_RENAMED = "template_renamed", _("modèle renommé")
    TEMPLATE_DELETED = "template_deleted", _("modèle supprimé")
    AUDIT_LOG_ACCESSED = "audit_log_accessed", _("journal consulté")
    RETENTION_PURGE = "retention_purge", _("purge de rétention")
    JOB_REFUSED = "job_refused", _("tâche planifiée refusée")


class Reason(models.TextChoices):
    """``reason`` is a structured code, not prose (§10).

    Free text authored by an operator will contain a name sooner or later —
    *nom mal orthographié : Dupond/Dupont* — and ``reason`` is retained. Any
    note accompanying the code is stored on the referenced object, where the
    purge takes it.
    """

    NAME_DIVERGENCE_ACCEPTED = "name_divergence_accepted", _("divergence de nom acceptée")
    NAME_DIVERGENCE_REFUSED = "name_divergence_refused", _("divergence de nom refusée")
    NO_ROLL_MATCH = "no_roll_match", _("aucune correspondance dans la liste")
    INELIGIBLE_LIST_TYPE = "ineligible_list_type", _("type de liste non autorisé pour ce scrutin")
    IDENTITY_CONFIRMED_AT_MAIRIE = "identity_confirmed_at_mairie", _("identité confirmée en mairie")
    KEYING_ERROR = "keying_error", _("erreur de saisie")
    VOTER_REQUEST = "voter_request", _("demande de l'électeur")
    DUPLICATE_BALLOT = "duplicate_ballot", _("bulletin en double")
    VOTED_ONLINE_ALREADY = "voted_online_already", _("a déjà voté en ligne")
    COUNTERSIGN_UNAVAILABLE = "countersign_unavailable", _("contreseing indisponible")
    DEADLINE_REACHED = "deadline_reached", _("échéance atteinte")
    ADMINISTRATIVE_DECISION = "administrative_decision", _("décision administrative")
    OTHER = "other", _("autre")


class AuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    poll = models.ForeignKey(
        "elections.Poll", on_delete=models.PROTECT, related_name="audit_events", null=True
    )
    # Null where a scheduled command acted; ``actor_label`` then names it.
    actor = models.ForeignKey(
        "core.User", on_delete=models.PROTECT, related_name="audit_events", null=True, blank=True
    )
    actor_label = models.CharField(max_length=50, blank=True)
    action = models.CharField(max_length=40, choices=Action.choices)
    # "registration:<uuid>", "ballot:<uuid>", "poll:<uuid>" (§10).
    object_ref = models.CharField(max_length=100, blank=True)
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    reason = models.CharField(max_length=40, choices=Reason.choices, blank=True)
    at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _("événement d'audit")
        verbose_name_plural = _("journal d'audit")
        ordering = ["-at"]
        indexes = [
            models.Index(fields=["poll", "at"]),
            models.Index(fields=["actor", "at"]),
            models.Index(fields=["object_ref"]),
        ]

    def __str__(self) -> str:
        return f"{self.at:%Y-%m-%d %H:%M} {self.action} {self.object_ref}"
