# SPDX-License-Identifier: 0BSD
"""Forms for the espace mairie (§6.5).

Screen 2's forms. They validate *shape* — a closing instant after the opening
one, a real timezone, at least two propositions — and hand the cleaned values
to ``elections.config``, the one writer (§6.5: no view writes through the ORM).

Whether the poll may be edited at all is R-3.3's business and is checked in the
service, not here: a form that quietly rendered itself read-only would hide the
reason it did.

The content fields — title, description, each option's label — are built per
enabled language at construction time, from the poll's *current* ``languages``.
Change the language set and save, and the new language's empty fields appear on
the next load, where the dashboard is already naming them as opening blockers
(§3.8).
"""

from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django import forms
from django.conf import settings
from django.contrib.auth import password_validation
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.utils.translation import gettext_lazy as _

from apps.audit.models import Reason
from apps.core.models import MailSettings, Role, User
from apps.elections import config
from apps.elections.models import ListType, Poll, TallyMethod, TiebreakRule

#: ``datetime-local`` submits without seconds; accept both shapes on the way in.
_DATETIME_FORMATS = ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S")

#: R-3.4's reason vocabulary, narrowed to the codes that can mean "the closing
#: date moved". The full ``Reason`` set includes ballot-review codes that would
#: be a valid enum value and a false record here (§10) — the same reasoning as
#: ``review.py``'s split of the registration decision codes.
EXTENSION_REASONS: tuple[Reason, ...] = (
    Reason.ADMINISTRATIVE_DECISION,
    Reason.DEADLINE_REACHED,
    Reason.OTHER,
)


class _DateTimeField(forms.DateTimeField):
    """A ``datetime-local`` field, so the operator gets a calendar widget."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            input_formats=_DATETIME_FORMATS,
            widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
            **kwargs,
        )


def _language_name(code: str) -> str:
    return dict(settings.LANGUAGES).get(code, code)


class PollConfigForm(forms.Form):
    """The editable configuration of a ``draft`` poll (§3.1, §6.5.2)."""

    opens_at = _DateTimeField(
        label=_("Ouverture du scrutin"),
        help_text=_(
            "Heure locale du serveur. Le scrutin s'ouvre à cette heure, ou plus tard si "
            "la tâche planifiée a pris du retard (§4)."
        ),
    )
    closes_at = _DateTimeField(label=_("Clôture du vote en ligne"))
    paper_entry_deadline = _DateTimeField(
        label=_("Fin de saisie des bulletins papier"),
        help_text=_(
            "Au moins égale à la clôture. Laissez-la égale à la clôture s'il n'y a pas "
            "de saisie papier différée : toute période pendant laquelle un bulletin peut "
            "encore entrer en base est affichée publiquement (§6.4)."
        ),
    )
    timezone = forms.CharField(
        label=_("Fuseau horaire du scrutin"), max_length=64, initial="Europe/Paris"
    )

    tally_method = forms.ChoiceField(
        label=_("Méthode de dépouillement"), choices=TallyMethod.choices
    )
    tally_method_version = forms.CharField(
        label=_("Version de la méthode"), max_length=20, initial="1"
    )
    require_complete_ranking = forms.BooleanField(
        label=_("Classement complet obligatoire"), required=False
    )
    allow_ties_in_ballot = forms.BooleanField(
        label=_("Ex æquo autorisés sur un bulletin"), required=False
    )
    tiebreak_rule = forms.ChoiceField(
        label=_("Départage en cas d'égalité"), choices=TiebreakRule.choices
    )

    paper_requires_signed_form = forms.BooleanField(
        label=_("Formulaire signé exigé pour un bulletin papier"), required=False
    )
    paper_requires_countersign = forms.BooleanField(
        label=_("Contreseing d'un second opérateur exigé"), required=False
    )
    paper_requires_reconciliation = forms.BooleanField(
        label=_("Rapprochement des bulletins papier exigé"), required=False
    )

    allow_ballot_modification = forms.BooleanField(
        label=_("Autoriser la modification d'un bulletin déjà voté"),
        required=False,
        help_text=_(
            "Ce n'est pas qu'un réglage de confidentialité. Désactiver la modification "
            "renforce l'anonymat — aucun lien n'est alors calculé entre un bulletin et le "
            "jeton qui l'a émis — mais retire à un électeur sous contrainte son seul "
            "recours : revoter seul une fois la pression levée (§7). La commune choisit "
            "lequel des deux risques elle préfère porter."
        ),
    )
    eligible_list_types = forms.MultipleChoiceField(
        label=_("Types de liste ouvrant le droit de vote"),
        choices=ListType.choices,
        widget=forms.CheckboxSelectMultiple,
        help_text=_(
            "Une question municipale prend la liste principale et la complémentaire "
            "municipale ; la complémentaire européenne seule ne confère aucun droit ici (R-4.7)."
        ),
    )
    show_live_participation = forms.BooleanField(
        label=_("Afficher la participation pendant le scrutin"),
        required=False,
        help_text=_(
            "Par défaut non : publier la participation pendant le vote peut l'influencer (§6.6)."
        ),
    )

    default_language = forms.ChoiceField(label=_("Langue par défaut"), choices=[])
    extra_languages = forms.MultipleChoiceField(
        label=_("Langues supplémentaires"),
        choices=[],
        widget=forms.CheckboxSelectMultiple,
        required=False,
        help_text=_(
            "Le titre, la description et chaque proposition devront être traduits dans "
            "chaque langue avant l'ouverture (§3.8)."
        ),
    )

    def __init__(self, *args: Any, content_languages: list[str], **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.content_languages = content_languages
        available = list(settings.LANGUAGES)
        self.fields["default_language"].choices = available  # type: ignore[attr-defined]
        self.fields["extra_languages"].choices = available  # type: ignore[attr-defined]
        for code in content_languages:
            name = _language_name(code)
            self.fields[f"title_{code}"] = forms.CharField(
                label=_("Titre (%(lang)s)") % {"lang": name},
                max_length=300,
                required=False,
            )
            self.fields[f"description_{code}"] = forms.CharField(
                label=_("Description (%(lang)s)") % {"lang": name},
                widget=forms.Textarea(attrs={"rows": 4}),
                required=False,
            )

    def clean_timezone(self) -> str:
        value: str = self.cleaned_data["timezone"]
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise forms.ValidationError(_("Fuseau horaire inconnu.")) from None
        return value

    def clean(self) -> dict[str, Any]:
        super().clean()
        cleaned = self.cleaned_data
        opens_at = cleaned.get("opens_at")
        closes_at = cleaned.get("closes_at")
        paper_deadline = cleaned.get("paper_entry_deadline")
        if opens_at and closes_at and closes_at <= opens_at:
            self.add_error("closes_at", _("La clôture doit suivre l'ouverture."))
        if closes_at and paper_deadline and paper_deadline < closes_at:
            self.add_error(
                "paper_entry_deadline",
                _("La fin de saisie des bulletins papier ne peut précéder la clôture."),
            )

        default_language = cleaned.get("default_language")
        extra = cleaned.get("extra_languages") or []
        if default_language:
            # §3.8: the first entry of ``languages`` is the default and the
            # fallback, so it leads the list and is never repeated in the tail.
            cleaned["languages"] = [default_language, *(c for c in extra if c != default_language)]
        return cleaned

    def to_draft(self, options: list[config.OptionDraft]) -> config.ConfigDraft:
        cleaned = self.cleaned_data
        languages: list[str] = cleaned["languages"]
        scalars = {name: cleaned[name] for name in config.SCALAR_FIELDS if name in cleaned}

        def content(prefix: str) -> dict[str, str]:
            # An empty string is "no translation", which is exactly what
            # ``missing_translations`` looks for — so it is dropped, not stored
            # (§3.8). A language removed from the set this save drops with it.
            out = {
                code: cleaned.get(f"{prefix}_{code}", "").strip() for code in self.content_languages
            }
            return {code: text for code, text in out.items() if text and code in languages}

        return config.ConfigDraft(
            scalars=scalars,
            languages=languages,
            title_i18n=content("title"),
            description_i18n=content("description"),
            options=options,
        )


class PollCreateForm(PollConfigForm):
    """The "Nouveau scrutin" screen's form — screen 2's shape, plus the one
    field screen 2 deliberately excludes.

    ``is_sandbox`` is fixed at creation and never editable again (R-3.7), so it
    belongs on this form and nowhere near ``PollConfigForm.to_draft``, which
    feeds ``save_configuration`` — the edit path that must never touch it.
    """

    is_sandbox = forms.BooleanField(
        label=_("Scrutin bac à sable"),
        required=False,
        help_text=_(
            "Fixé pour toujours : un scrutin bac à sable n'apparaît sur aucune page "
            "publique, aucun résultat publié et aucune statistique (R-3.7)."
        ),
    )


class OptionForm(forms.Form):
    """One proposition row. Blank rows are ignored; a deleted row is dropped."""

    pk = forms.CharField(required=False, widget=forms.HiddenInput)
    option_id = forms.SlugField(
        label=_("Identifiant"),
        max_length=50,
        required=False,
        help_text=_(
            "Court, sans espace ni accent. Porté par les bulletins et le résultat publié : "
            "ne le modifiez pas après l'ouverture (§3.8)."
        ),
    )

    def __init__(self, *args: Any, content_languages: list[str], **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.content_languages = content_languages
        for code in content_languages:
            self.fields[f"label_{code}"] = forms.CharField(
                label=_("Intitulé (%(lang)s)") % {"lang": _language_name(code)},
                max_length=300,
                required=False,
            )

    def _has_label(self) -> bool:
        return any(self.cleaned_data.get(f"label_{code}") for code in self.content_languages)

    def is_blank(self) -> bool:
        return not self.cleaned_data.get("option_id") and not self._has_label()

    def clean(self) -> dict[str, Any]:
        super().clean()
        cleaned = self.cleaned_data
        if self._has_label() and not cleaned.get("option_id"):
            self.add_error("option_id", _("Donnez un identifiant à cette proposition."))
        return cleaned

    def to_draft(self) -> config.OptionDraft | None:
        cleaned = self.cleaned_data
        if cleaned.get("DELETE") or self.is_blank():
            return None
        labels = {code: cleaned.get(f"label_{code}", "").strip() for code in self.content_languages}
        return config.OptionDraft(
            option_id=cleaned["option_id"],
            labels={code: text for code, text in labels.items() if text},
            pk=cleaned.get("pk", ""),
        )


class BaseOptionFormSet(forms.BaseFormSet):  # type: ignore[type-arg]  # not subscriptable at runtime
    """Cross-row rules: at least two propositions, no shared identifier (§3.1).

    Validation only — it raises, it does not keep state. The view re-derives the
    drafts from the (now valid) forms through ``option_drafts`` below, so the
    typing stays exact past ``formset_factory``, which erases this subclass.
    """

    def clean(self) -> None:
        if any(self.errors):
            return
        drafts = option_drafts(self)
        ids = [draft.option_id for draft in drafts]
        if len(ids) != len(set(ids)):
            raise forms.ValidationError(_("Deux propositions portent le même identifiant."))
        if len(drafts) < 2:
            raise forms.ValidationError(
                _("Un scrutin comporte au moins deux propositions (R-3.1).")
            )


OptionFormSet = forms.formset_factory(
    OptionForm, formset=BaseOptionFormSet, extra=2, can_delete=True
)


def option_drafts(formset: forms.BaseFormSet[OptionForm]) -> list[config.OptionDraft]:
    """The non-blank, non-deleted proposition rows, in row order."""
    return [draft for form in formset.forms if (draft := form.to_draft()) is not None]


class ExtensionForm(forms.Form):
    """R-3.4 — the one configuration change still allowed once the poll is open.

    The instant and the reason are validated here; that the poll is ``open``
    and the new instant is later is ``transitions.extend_closes_at``'s guard,
    which owns ``closes_at`` and the audit event.
    """

    new_closes_at = _DateTimeField(label=_("Nouvelle date de clôture"))
    reason = forms.ChoiceField(
        label=_("Motif (obligatoire)"),
        choices=[(reason.value, reason.label) for reason in EXTENSION_REASONS],
    )


#: R-8.7 bis: the codes a poll admin may cite for closing over a
#: ``pending_countersign`` ballot. ``COUNTERSIGN_UNAVAILABLE`` is the one this
#: override exists for; the other two cover a closure forced for some other
#: reason before every countersignature is in.
CLOSURE_REASONS: tuple[Reason, ...] = (
    Reason.COUNTERSIGN_UNAVAILABLE,
    Reason.ADMINISTRATIVE_DECISION,
    Reason.OTHER,
)


class ClosureOverrideForm(forms.Form):
    """Screen 2's manual ``close_poll`` trigger (§4).

    The reason is required only when ``closing_blockers`` finds ballots
    pending countersignature (R-8.7 bis); that is ``transitions.close_poll``'s
    guard to enforce, not a client-side rule, so the field stays optional here
    and an omitted reason on a blocked closure comes back as a message naming
    the blocker instead of a form error.
    """

    reason = forms.ChoiceField(
        label=_("Motif de clôture forcée (si des bulletins attendent un contreseing)"),
        required=False,
        choices=[("", "—")] + [(reason.value, reason.label) for reason in CLOSURE_REASONS],
    )


#: R-3.11's reason vocabulary. Narrowed like ``EXTENSION_REASONS`` above: the
#: full ``Reason`` set includes ballot- and registration-review codes that
#: would be valid enum values and false records here (§10).
WITHDRAWAL_REASONS: tuple[Reason, ...] = (
    Reason.ADMINISTRATIVE_DECISION,
    Reason.OTHER,
)


class WithdrawalForm(forms.Form):
    """Screen 2's manual ``withdraw_poll`` trigger (R-3.11).

    Unlike ``ClosureOverrideForm``'s reason, this one is required unconditionally
    — ``withdrawing_blockers`` refuses a missing reason exactly as it refuses
    the wrong source state, so the field matches that here rather than leaving
    it to come back as a named blocker.
    """

    reason = forms.ChoiceField(
        label=_("Motif du retrait (obligatoire)"),
        choices=[(reason.value, reason.label) for reason in WITHDRAWAL_REASONS],
    )


def config_initial(poll: Poll) -> dict[str, Any]:
    """The bound values for ``PollConfigForm`` on a GET.

    In ``views.py`` this would trip ``test_every_poll_scoped_view_is_gated``,
    which flags any function there taking a ``poll``; it lives here instead.
    """
    languages = list(poll.languages) or [poll.default_language]
    initial: dict[str, Any] = {name: getattr(poll, name) for name in config.SCALAR_FIELDS}
    initial["default_language"] = poll.default_language
    initial["extra_languages"] = [code for code in languages if code != poll.default_language]
    for code in languages:
        initial[f"title_{code}"] = poll.title_i18n.get(code, "")
        initial[f"description_{code}"] = poll.description_i18n.get(code, "")
    return initial


def option_initial(poll: Poll) -> list[dict[str, Any]]:
    """One ``OptionForm`` initial per stored proposition, in order."""
    rows: list[dict[str, Any]] = []
    for option in poll.options.all():
        row: dict[str, Any] = {"pk": str(option.pk), "option_id": option.option_id}
        for code, text in option.label_i18n.items():
            row[f"label_{code}"] = text
        rows.append(row)
    return rows


#: A screen-2 configuration warning code (``config.configuration_warnings``) as a
#: sentence a council member can act on — the same codes/French split as
#: ``dashboard.describe_blocker`` keeps for the opening blockers.
_CONFIG_WARNINGS: dict[str, Any] = {
    "plurality_allows_ties": _(
        "Méthode majoritaire avec ex æquo autorisés sur le bulletin : un bulletin "
        "qui place plusieurs propositions en tête donne une voix à chacune (§8.2). "
        "C'est rarement voulu pour une question à choix unique — vérifiez l'un ou "
        "l'autre réglage."
    ),
}


def config_warnings(poll: Poll) -> list[str]:
    """Legal-but-suspect configuration on ``poll``, described for screen 2 (§8.2).

    Non-blocking: the poll still saves and still opens. In ``views.py`` this
    would trip ``test_every_poll_scoped_view_is_gated``; it lives here beside
    the other screen-2 read helpers.
    """
    codes = config.configuration_warnings(
        poll.tally_method, allow_ties_in_ballot=poll.allow_ties_in_ballot
    )
    return [str(_CONFIG_WARNINGS.get(code, code)) for code in codes]


# --- Screen 10: comptes et rôles (§6.5.10) --------------------------------


class NewAccountForm(forms.ModelForm):  # type: ignore[type-arg]  # not subscriptable at runtime
    """A new named operator account (R-2.2).

    Validates shape and — through the model's unique username — that the login
    is free; ``accounts.create_account`` is the writer (§6.5). The password is
    run past Django's configured validators here so a weak one is refused before
    it reaches the service.
    """

    raw_password = forms.CharField(
        label=_("Mot de passe initial"),
        widget=forms.PasswordInput,
        help_text=_("À remettre à la personne, qui le changera à la première connexion."),
    )

    class Meta:
        model = User
        fields = ("username", "full_name", "is_commune_admin")
        labels = {
            "username": _("Identifiant de connexion"),
            "full_name": _("Nom complet"),
            "is_commune_admin": _("Administrateur de la commune"),
        }
        help_texts = {
            "is_commune_admin": _(
                "Gère les comptes et crée les scrutins. Ne donne accès à aucun "
                "écran d'un scrutin : cela demande un rôle sur ce scrutin (§3.7)."
            ),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # ``blank=True`` on the model, required here: an account exists to name a
        # natural person in the audit log (R-2.2), so it is given a name.
        self.fields["full_name"].required = True

    def clean_raw_password(self) -> str:
        password: str = self.cleaned_data["raw_password"]
        password_validation.validate_password(password)
        return password


# --- Screen 11: première installation (§6.5.11) --------------------------


class FirstRunForm(forms.Form):
    """The first-run wizard: the commune record and the initial administrator
    in one form (§6.5.11).

    It validates shape only — a password that passes Django's validators and a
    confirmation that matches it — and hands the cleaned values to
    ``firstrun.install``, which writes both rows in one transaction. The
    username is not checked for uniqueness because the screen only exists while
    there are no accounts (``access.require_first_run``).
    """

    commune_name = forms.CharField(
        label=_("Nom de la commune"),
        max_length=200,
        help_text=_("Tel qu'il apparaîtra sur les pages publiques et dans la notice."),
    )
    data_protection_referent = forms.CharField(
        label=_("Référent données personnelles"),
        max_length=200,
        help_text=_(
            "Personne ou service qui répond aux demandes d'accès, de rectification "
            "et d'effacement des électeurs (R-13.2)."
        ),
    )
    data_protection_contact = forms.CharField(
        label=_("Contact du référent"),
        max_length=300,
        help_text=_("Adresse électronique ou postale, publiée dans la notice d'information."),
    )

    username = forms.CharField(
        label=_("Identifiant de connexion de l'administrateur"),
        max_length=150,
        validators=[UnicodeUsernameValidator()],
    )
    full_name = forms.CharField(
        label=_("Nom complet de l'administrateur"),
        max_length=200,
        help_text=_("Le journal d'audit nomme une personne, pas une fonction (R-2.2)."),
    )
    raw_password = forms.CharField(label=_("Mot de passe"), widget=forms.PasswordInput)
    raw_password_confirm = forms.CharField(
        label=_("Confirmer le mot de passe"), widget=forms.PasswordInput
    )

    def clean_raw_password(self) -> str:
        password: str = self.cleaned_data["raw_password"]
        password_validation.validate_password(password)
        return password

    def clean(self) -> dict[str, Any]:
        super().clean()
        cleaned = self.cleaned_data
        password = cleaned.get("raw_password")
        confirm = cleaned.get("raw_password_confirm")
        if password and confirm and password != confirm:
            self.add_error("raw_password_confirm", _("Les deux mots de passe diffèrent."))
        return cleaned


class GrantRoleForm(forms.Form):
    """Assign one per-poll role of §3.7 to an active account (R-2.1)."""

    account = forms.ModelChoiceField(
        label=_("Compte"),
        queryset=User.objects.filter(is_active=True).order_by("username"),
        empty_label=_("— choisir —"),
    )
    role = forms.ChoiceField(label=_("Rôle"), choices=Role.choices)


# --- Screen 12: paramètres de messagerie (§6.5.12) ------------------------


class MailSettingsForm(forms.ModelForm):  # type: ignore[type-arg]  # not subscriptable at runtime
    """The SMTP relay. The password is entered here but never redisplayed —
    ``instance`` never puts it back in ``initial`` (it lives encrypted, off
    this form's fields entirely) — and a blank submission keeps whatever is
    already stored (``mailsettings.save``)."""

    raw_password = forms.CharField(
        label=_("Mot de passe"),
        widget=forms.PasswordInput(render_value=False),
        required=False,
        help_text=_("Laissez vide pour conserver le mot de passe déjà enregistré."),
    )

    class Meta:
        model = MailSettings
        fields = ("host", "port", "encryption", "username", "from_email")
        labels = {
            "host": _("Serveur SMTP"),
            "port": _("Port"),
            "encryption": _("Chiffrement"),
            "username": _("Identifiant"),
            "from_email": _("Adresse d'expédition"),
        }
        widgets = {"encryption": forms.RadioSelect}

    def clean_port(self) -> int:
        port: int = self.cleaned_data["port"]
        if not 1 <= port <= 65535:
            raise forms.ValidationError(_("Le port doit être compris entre 1 et 65535."))
        return port


class MailTestForm(forms.Form):
    """Screen 12's "envoyer un message de test" action."""

    recipient = forms.EmailField(label=_("Adresse de test"))


# --- Screen 13: modèles de scrutin (§6.5.13) -------------------------------


class TemplateNameForm(forms.Form):
    """One field, shared by screen 2's *enregistrer comme modèle* (§3.9) and
    screen 13's rename — both write nothing but a name."""

    name = forms.CharField(label=_("Nom du modèle"), max_length=200)
