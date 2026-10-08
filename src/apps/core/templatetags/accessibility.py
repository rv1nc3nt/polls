# SPDX-License-Identifier: 0BSD
"""Template tags for accessible form errors (RGAA 4 / WCAG 2.1 AA).

Django already puts ``aria-invalid`` and ``aria-describedby="<id>_error"`` on a
widget whose field has errors, so a field is rendered as plain ``{{ field }}``.
These tags supply the other end of that link: the element the id points to.

Usage:
    {% load accessibility %}
    {{ field }}
    {% accessible_errors field %}
"""

from __future__ import annotations

from typing import Any

from django import template
from django.forms import BoundField
from django.forms.utils import flatatt
from django.utils.html import format_html, format_html_join
from django.utils.safestring import SafeString

register = template.Library()


@register.filter
def error_id(field: BoundField) -> str:
    """The id Django's ``aria-describedby`` points at: ``<id_for_label>_error``."""
    if not isinstance(field, BoundField):
        return ""
    return f"{field.id_for_label}_error"


@register.simple_tag
def accessible_errors(field: BoundField, tag: str = "p", **attrs: Any) -> SafeString:
    """The field's errors in one element carrying the id the widget describes itself by.

    Built with ``format_html`` so the error text and the attribute values are
    escaped while the element itself is not: a plain ``str`` would be shown
    as literal markup, and ``mark_safe`` alone would let a message through
    unescaped.

    RGAA 11.10 / WCAG 3.3.1: the error is announced (``role="alert"``).
    """
    if not field.errors:
        return SafeString("")

    attrs.setdefault("id", error_id(field))
    attrs.setdefault("role", "alert")
    attrs.setdefault("class", "error")
    return format_html(
        "<{tag}{attrs}>{errors}</{tag}>",
        tag=tag,
        attrs=flatatt(attrs),
        errors=format_html_join(", ", "{}", ((e,) for e in field.errors)),
    )
