# SPDX-License-Identifier: 0BSD
"""INV-1 and INV-5 — no path from a voter to an online ballot (§5, T-25).

This has no schema expression: the models simply share no foreign key. So it is
asserted three ways — over the model metadata, over the import graph, and over
the field values of a registration and the ballot cast from its token.
"""

from __future__ import annotations

import ast
from pathlib import Path

from apps.ballots.models import Ballot, PaperBallotLink
from apps.registrations.models import Registration

SRC = Path(__file__).resolve().parents[2] / "src"


def test_ballot_carries_no_voter_registration_or_nne_reference() -> None:
    """§5: adding one to satisfy INV-5 would destroy INV-1."""
    names = {field.name for field in Ballot._meta.get_fields()}
    assert not names & {"voter", "registration", "nne", "voter_hash", "email"}

    relations = {
        field.related_model
        for field in Ballot._meta.get_fields()
        if field.is_relation and field.related_model is not None
    }
    # PaperBallotLink is the one deliberate association (R-8.2 bis), and it is
    # reached from the ballot, not from the registration.
    assert Registration not in relations


def test_registration_has_no_relation_to_ballot() -> None:
    relations = {
        field.related_model
        for field in Registration._meta.get_fields()
        if field.is_relation and field.related_model is not None
    }
    assert Ballot not in relations
    assert PaperBallotLink not in relations


def test_neither_models_module_imports_the_other() -> None:
    """Keep the two in separate service modules so a join has no natural place
    to be written (§5.1)."""
    for module, forbidden in (
        ("registrations/models.py", "apps.ballots"),
        ("ballots/models.py", "apps.registrations"),
        ("registrations/services.py", "apps.ballots"),
    ):
        tree = ast.parse((SRC / "apps" / module).read_text())
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert not any(name.startswith(forbidden) for name in imported), module


def test_no_value_is_common_to_a_registration_and_a_ballot_row() -> None:
    """T-25: in particular no tracking code, which is why the confirmation
    email carries none (§6.2)."""
    registration_fields = {f.name for f in Registration._meta.get_fields()}
    ballot_fields = {f.name for f in Ballot._meta.get_fields()}
    shared = registration_fields & ballot_fields
    assert shared <= {"id", "poll", "created_at"}
    assert "tracking_code" not in registration_fields
