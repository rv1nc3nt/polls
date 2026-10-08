# SPDX-License-Identifier: 0BSD
"""The error element and the autocomplete hints of the accessible forms (RGAA 4)."""

from __future__ import annotations

from django import forms
from django.template import Context, Template

from apps.backoffice.forms import CommuneSettingsForm, FirstRunForm, NewAccountForm
from apps.core.forms import AccessibleForm


class _Choice(AccessibleForm):
    pick = forms.ChoiceField(choices=[("x", "X"), ("y", "Y")])


def _render(source: str, **context: object) -> str:
    return Template("{% load accessibility %}" + source).render(Context(context))


def test_the_error_element_is_markup_and_not_escaped_text() -> None:
    form = _Choice({"pick": "zzz"})
    out = _render("{% accessible_errors form.pick %}", form=form)
    assert out.startswith("<p ") and out.endswith("</p>")
    for attribute in ('id="id_pick_error"', 'role="alert"', 'class="error"'):
        assert attribute in out
    assert "&lt;" not in out


def test_the_error_element_is_the_id_djangos_aria_describedby_points_at() -> None:
    form = _Choice({"pick": "zzz"})
    widget = str(form["pick"])
    assert 'aria-describedby="id_pick_error"' in widget
    assert 'id="id_pick_error"' in _render("{% accessible_errors form.pick %}", form=form)


def test_error_text_and_attributes_are_escaped() -> None:
    class Hostile(AccessibleForm):
        a = forms.CharField()

        def clean_a(self) -> str:
            raise forms.ValidationError("<script>alert(1)</script>")

    form = Hostile({"a": "v"})
    out = _render('{% accessible_errors form.a role="a&quot;b" %}', form=form)
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_a_valid_field_has_no_error_element() -> None:
    assert _render("{% accessible_errors form.pick %}", form=_Choice({"pick": "x"})) == ""


def test_autocomplete_is_not_inferred_from_a_field_name() -> None:
    """On the back office ``name`` and ``email`` are the commune's, not the operator's."""
    commune = CommuneSettingsForm()
    assert all("autocomplete" not in f.widget.attrs for f in commune.fields.values())


def test_a_password_being_set_is_declared_new_password() -> None:
    for form in (FirstRunForm(), NewAccountForm()):
        assert form.fields["raw_password"].widget.attrs["autocomplete"] == "new-password"
    assert FirstRunForm().fields["raw_password_confirm"].widget.attrs["autocomplete"] == (
        "new-password"
    )
