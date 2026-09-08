# SPDX-License-Identifier: 0BSD
"""The registration form (§6.2 step 1).

Field validation only. The form never decides an outcome: whether a
registration is consistent with the roll is ``services.register``'s business,
and a form that refused a divergent name would defeat R-5.4, which routes it to
a human instead (T-28).

The help text is part of the requirement, not decoration: an elector who does
not know what an NNE is cannot register, and step 1 names the two places to
find one.
"""

from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.core.names import is_valid_nne, normalise_nne


class RegistrationForm(forms.Form):
    last_name = forms.CharField(label=_("Nom de famille"), max_length=200)
    first_names = forms.CharField(
        label=_("Prénom(s)"),
        max_length=200,
        help_text=_("Tous vos prénoms, tels qu'ils figurent sur votre carte électorale."),
    )
    nne = forms.CharField(
        label=_("Numéro national d'électeur (NNE)"),
        max_length=20,
        required=False,
        help_text=_(
            "Il figure sur votre carte électorale. Vous pouvez l'obtenir auprès de la mairie, "
            "ou par le service « Interroger sa situation électorale »."
        ),
    )
    email = forms.EmailField(
        label=_("Adresse électronique"),
        help_text=_(
            "Choisissez une adresse que vous seul consultez : c'est elle qui recevra le lien "
            "de vote, et ce lien vaut droit de vote. Une même adresse ne peut servir qu'une "
            "fois ; deux personnes partageant une adresse doivent voter à la mairie."
        ),
    )
    declared_on_honour = forms.BooleanField(
        label=_(
            "Je déclare sur l'honneur être inscrit sur la liste électorale de la commune "
            "et ne m'inscrire qu'une seule fois à cette consultation."
        ),
        required=True,
    )

    def clean_nne(self) -> str:
        """Normalised, and refused only when it is present and malformed.

        A blank NNE is allowed through: R-5.4 routes it to ``pending_review``,
        because an elector who cannot find their number must still have a way in
        that does not end at a form error.
        """
        value = normalise_nne(self.cleaned_data.get("nne", ""))
        if value and not is_valid_nne(value):
            raise forms.ValidationError(_("Un NNE comporte 8 ou 9 chiffres."))
        return value
