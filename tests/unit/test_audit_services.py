# SPDX-License-Identifier: 0BSD
"""The PII guard in ``audit.services._check`` (§10).

Only a defence against a mistake at write time — the scan of T-55 is what
actually holds — but it must catch a forbidden key wherever it appears in the
payload, not only at the top level: screen 8's own access-logging nests the
operator's free-text search box one level down, under ``filters``.
"""

from __future__ import annotations

import pytest

from apps.audit.services import PersonalDataInAuditEvent, _check


def test_top_level_forbidden_key_is_caught() -> None:
    with pytest.raises(PersonalDataInAuditEvent):
        _check({"email": "person@example.fr"}, "after")


def test_forbidden_key_nested_one_level_down_is_caught() -> None:
    """The shape screen 8's ``audit_log`` view produces (§10)."""
    with pytest.raises(PersonalDataInAuditEvent):
        _check({"filters": {"object_ref": "Dupont"}}, "after")


def test_forbidden_key_nested_inside_a_list_is_caught() -> None:
    with pytest.raises(PersonalDataInAuditEvent):
        _check({"rows": [{"status": "ok"}, {"email": "person@example.fr"}]}, "after")


def test_unrelated_nested_payload_is_allowed() -> None:
    _check({"filters": {"object_filtered": True, "actor_id": "42"}, "page": 3}, "after")
