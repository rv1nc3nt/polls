# SPDX-License-Identifier: 0BSD
"""The "find my ballot" form of the public results page (R-11.4)."""

from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.core.codes import parse_tracking_code
from apps.core.types import TrackingCode


class TrackingCodeForm(forms.Form):
    code = forms.CharField(
        label=_("Votre code de suivi"),
        help_text=_(
            "Tel qu'il figure sur votre récépissé ou dans le courriel reçu après le vote, "
            "par exemple ABCDE-FGHJK. Tirets, espaces et minuscules sont acceptés."
        ),
        max_length=40,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "off",
                "autocapitalize": "characters",
                "spellcheck": "false",
            }
        ),
    )

    def clean_code(self) -> TrackingCode:
        # The receipt prints the code with a dash; the published list holds it
        # without (§9), which is why a search of the file by hand found nothing.
        code = parse_tracking_code(self.cleaned_data["code"])
        if code is None:
            raise forms.ValidationError(
                _(
                    "Ce n'est pas un code de suivi : il compte dix caractères, lettres et "
                    "chiffres, sans O, 0, I ni 1."
                )
            )
        return code
