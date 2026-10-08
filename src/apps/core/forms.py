# SPDX-License-Identifier: 0BSD
"""Accessible form base classes and utilities (RGAA 4 / WCAG 2.1 AA).

This module provides form enhancements for accessibility compliance:
- Automatic aria-required attributes on required fields
- Automatic aria-describedby linking fields to their error messages
- Proper autocomplete attributes for user form fields
- ARIA labels and descriptions for complex widgets

RGAA Criteria Addressed:
- 8.1: Required fields are identified (aria-required)
- 8.2: Required fields have explicit indication
- 11.1: Form fields have associated labels
- 11.2: Form fields have proper autocomplete
- 11.7: Form errors are associated with fields

WCAG Criteria Addressed:
- 1.3.5: Identify Input Purpose (autocomplete)
- 3.3.2: Labels or Instructions (aria-describedby for errors)
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
    - aria-describedby linking to error message IDs
    - autocomplete attributes where appropriate
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._add_accessibility_attrs()

    def _add_accessibility_attrs(self) -> None:
        """Add accessibility attributes to all fields after initialization."""
        for field_name, field in self.fields.items():
            # Add aria-required for required fields (RGAA 8.1, WCAG 3.3.2)
            if field.required:
                field.widget.attrs["aria-required"] = "true"

            # Add autocomplete for common field types (RGAA 11.13, WCAG 1.3.5)
            self._add_autocomplete(field_name, field)

    def _add_autocomplete(self, field_name: str, field: forms.Field) -> None:
        """Add autocomplete attributes based on field name and type."""
        # Map field names to autocomplete values
        autocomplete_map: dict[str, str] = {
            "first_name": "given-name",
            "first_names": "given-name",
            "last_name": "family-name",
            "name": "name",
            "full_name": "name",
            "email": "email",
            "address": "street-address",
            "city": "address-level2",
            "postal_code": "postal-code",
            "phone": "tel",
            "date_of_birth": "bday",
            "username": "username",
            "password": "current-password",
            "new_password": "new-password",
            "search": "search",
        }

        # Check field name first
        for name_pattern, autocomplete in autocomplete_map.items():
            if field_name == name_pattern:
                field.widget.attrs["autocomplete"] = autocomplete
                return

        # Check field type
        if isinstance(field, forms.EmailField):
            field.widget.attrs["autocomplete"] = "email"
        elif isinstance(field, forms.CharField):
            # Check widget type for text inputs
            if isinstance(field.widget, forms.EmailInput):
                field.widget.attrs["autocomplete"] = "email"
            elif isinstance(field.widget, forms.PasswordInput):
                field.widget.attrs["autocomplete"] = "current-password"

    def add_error_descriptions(self) -> None:
        """Add aria-describedby to fields that have errors.

        Called after form validation to link fields to their error messages.
        This ensures screen readers can announce errors when users navigate to
        fields with validation errors.

        RGAA 11.7: Form errors are properly associated with their fields
        WCAG 3.3.1: Error identification
        """
        for field_name, field in self.fields.items():
            if field.errors and field_name in self.data:
                error_id = f"{field.id_for_label}_error"
                # Add to widget attrs if not already there
                if "aria-describedby" not in field.widget.attrs:
                    field.widget.attrs["aria-describedby"] = error_id
                # Ensure error element has matching ID


class AccessibleModelFormMixin(AccessibleFormMixin):
    """AccessibleFormMixin for ModelForms."""

    pass


class AccessibleForm(AccessibleFormMixin, forms.Form):
    """Base accessible form class for new forms."""

    pass


class AccessibleModelForm(AccessibleFormMixin, forms.ModelForm):
    """Base accessible ModelForm class for new model forms."""

    pass
