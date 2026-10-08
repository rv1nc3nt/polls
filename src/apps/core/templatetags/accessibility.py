# SPDX-License-Identifier: 0BSD
"""Template tags for accessibility enhancements (RGAA 4 / WCAG 2.1 AA).

This module provides template tags for:
- Adding accessibility attributes to form fields
- Generating error IDs for aria-describedby
- Creating accessible error messages

Usage:
    {% load accessibility %}
    
    {# Add error description to a field #}
    {{ field|accessible_field }}
    
    {# Or with custom error ID #}
    {{ field|accessible_field:"custom_error_id" }}
"""

from __future__ import annotations

from django import template
from django.forms import BoundField

register = template.Library()


@register.filter
def accessible_field(field: BoundField, error_id: str | None = None) -> str:
    """Render a form field with accessibility attributes.

    Adds aria-describedby to link the field to its error message when errors
    are present.

    Args:
        field: The bound form field to render
        error_id: Optional custom error ID. If None, uses field.id_for_label + "_error"

    Returns:
        Safe string with the rendered field and accessibility attributes

    RGAA Criteria: 11.7 (Form errors properly associated)
    WCAG Criteria: 3.3.1 (Error Identification), 3.3.2 (Labels or Instructions)
    """
    if not isinstance(field, BoundField):
        return str(field)

    # Generate error ID if not provided
    if error_id is None:
        error_id = f"{field.id_for_label}_error"

    # Add aria-describedby if field has errors
    if field.errors:
        widget = field.field.widget
        # Clone attrs to avoid modifying the original
        attrs = widget.attrs.copy()
        if "aria-describedby" not in attrs:
            attrs["aria-describedby"] = error_id
            # Create a new widget with updated attrs
            widget = type(widget)(attrs=attrs)
            # Create a copy of the field with the new widget
            field.field.widget = widget

    return str(field)


@register.filter
def error_id(field: BoundField) -> str:
    """Generate an error ID for a form field.

    Args:
        field: The bound form field

    Returns:
        Error ID string: field.id_for_label + "_error"

    Usage:
        {% load accessibility %}
        <p id="{{ field|error_id }}" class="error" role="alert">
            {{ field.errors|join:", " }}
        </p>
    """
    if not isinstance(field, BoundField):
        return ""
    return f"{field.id_for_label}_error"


@register.simple_tag
def accessible_errors(field: BoundField, tag: str = "p", **kwargs) -> str:
    """Render field errors with accessibility attributes.

    Args:
        field: The bound form field
        tag: HTML tag to use (default: "p")
        **kwargs: Additional attributes for the tag

    Returns:
        Safe string with the error message wrapped in the specified tag

    Usage:
        {% load accessibility %}
        {% accessible_errors field role="alert" aria-live="assertive" %}

    RGAA Criteria: 11.7 (Form errors properly associated)
    WCAG Criteria: 3.3.1 (Error Identification)
    """
    if not field.errors:
        return ""

    error_id = f"{field.id_for_label}_error"
    kwargs.setdefault("id", error_id)
    kwargs.setdefault("role", "alert")
    kwargs.setdefault("class", "error")

    attrs = " ".join(f'{k}="{v}"' for k, v in kwargs.items())
    errors_text = ", ".join(str(e) for e in field.errors)
    return f"<{tag} {attrs}>{errors_text}</{tag}>"
