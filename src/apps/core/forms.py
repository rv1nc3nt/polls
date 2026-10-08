# SPDX-License-Identifier: 0BSD
"""Accessible form base classes and utilities (RGAA 4 / WCAG 2.1 AA).

This module provides form enhancements for accessibility compliance:
- Automatic aria-required attributes on required fields

RGAA Criteria Addressed:
- 8.1: Required fields are identified (aria-required)
- 8.2: Required fields have explicit indication
- 11.1: Form fields have associated labels

WCAG Criteria Addressed:
- 3.3.2: Labels or Instructions
- 4.1.2: Name, Role, Value
"""

from __future__ import annotations

from typing import Any

from django import forms


class AccessibleFormMixin:
    """Mixin that adds accessibility attributes to form fields.

    Usage:
        class MyForm(AccessibleFormMixin, forms.Form):
            name = forms.CharField(required=True)

    This automatically adds:
    - aria-required="true" to required fields
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._add_accessibility_attrs()

    def _add_accessibility_attrs(self) -> None:
        """Mark required fields for assistive tools (RGAA 8.1, WCAG 3.3.2).

        ``autocomplete`` is deliberately not inferred from a field's name: the
        same ``name`` or ``email`` is the elector's own on the public form and
        someone else's, or the commune's, in the back office, where a
        browser would fill in the operator's details. A form that wants a
        token sets it on the widget.
        """
        for field in self.fields.values():  # type: ignore[attr-defined]
            if field.required:
                field.widget.attrs["aria-required"] = "true"


class AccessibleModelFormMixin(AccessibleFormMixin):
    """AccessibleFormMixin for ModelForms."""

    pass


class AccessibleForm(AccessibleFormMixin, forms.Form):
    """Base accessible form class for new forms."""

    pass


class AccessibleModelForm(AccessibleFormMixin, forms.ModelForm):  # type: ignore[type-arg]  # not subscriptable at runtime
    """Base accessible ModelForm class for new model forms."""

    pass
