# SPDX-License-Identifier: 0BSD
"""The registration form (§6.2 step 1).

Field validation only. The form never decides an outcome: whether a
registration is consistent with the roll is ``services.register``'s business,
and a form that refused a divergent name — or an unusual date — would defeat
R-5.4, which routes it to a human instead (T-28).

The help text is part of the requirement, not decoration: step 1 says plainly
that either the birth surname or the name in use is accepted (R-5.3), so an
elector who knows only the name on their card is not turned away at the form.
"""

from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _


class RegistrationForm(forms.Form):
    last_name = forms.CharField(
        label=_("Nom de famille"),
        max_length=200,
        help_text=_("Votre nom de naissance ou votre nom d'usage : les deux sont acceptés."),
    )
    first_names = forms.CharField(
        label=_("Prénom(s)"),
        max_length=200,
        help_text=_("Tous vos prénoms, tels qu'ils figurent sur votre carte électorale."),
    )
    date_of_birth = forms.CharField(
        label=_("Date de naissance"),
        max_length=40,
        help_text=_("Au format JJ/MM/AAAA."),
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
