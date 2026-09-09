# SPDX-License-Identifier: 0BSD
"""INV-1 and INV-5 — no path from a voter to an online ballot (§5, T-25, T-6).

This has no schema expression: the models simply share no foreign key. So it is
asserted four ways — over the model metadata, over the import graph, over the
field values of a registration and the ballot cast from its token, and (T-6)
over a full dump of every table after a whole online-only poll lifecycle.
"""

from __future__ import annotations

import ast
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.ballots import services as ballots
from apps.ballots.models import Ballot, PaperBallotLink
from apps.core.models import User
from apps.elections.models import Poll, PollOption, RollEntry, WorkingRollEntry
from apps.elections.transitions import open_poll
from apps.registrations import services as registrations
from apps.registrations.models import Registration

SRC = Path(__file__).resolve().parents[2] / "src"


def test_ballot_carries_no_voter_registration_or_roll_entry_reference() -> None:
    """§5: adding one to satisfy INV-5 would destroy INV-1."""
    names = {field.name for field in Ballot._meta.get_fields()}
    assert not names & {"voter", "registration", "roll_entry", "nne", "voter_hash", "email"}

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


# --- T-6: the full dump ---------------------------------------------------

# (birth name, first names, dob, parsed dob, email, ranking) — exact roll
# matches so every registration auto-approves and mints a token.
_VOTERS = [
    ("Bernard", "Alice", "01/02/1960", "1960-02-01", "alice@exemple.fr", [["a"], ["b"], ["c"]]),
    ("Dubois", "Bruno", "03/04/1955", "1955-04-03", "bruno@exemple.fr", [["b"], ["c"], ["a"]]),
    ("Petit", "Chloé", "05/06/1970", "1970-06-05", "chloe@exemple.fr", [["c"], ["a"], ["b"]]),
    ("Moreau", "David", "07/08/1948", "1948-08-07", "david@exemple.fr", [["a"], ["c"], ["b"]]),
]


def _rows(model: Any) -> list[dict[str, Any]]:
    """Every row of ``model`` as a plain dict, memoryviews coerced to bytes —
    a stand-in for a full database dump."""
    out: list[dict[str, Any]] = []
    for obj in model._default_manager.all():
        row: dict[str, Any] = {}
        for field in model._meta.concrete_fields:
            value = getattr(obj, field.attname)
            row[field.attname] = bytes(value) if isinstance(value, memoryview) else value
        out.append(row)
    return out


@pytest.fixture
def dumped_online_poll(db: None) -> Poll:
    """A whole online-only lifecycle: open, four registrations each confirmed
    and cast online, modification enabled so a ``ballot_hash`` is stored."""
    now = timezone.now()
    poll = Poll.objects.create(
        title_i18n={"fr": "Consultation en ligne"},
        description_i18n={"fr": "Trois propositions."},
        languages=["fr"],
        opens_at=now - timedelta(days=1),
        closes_at=now + timedelta(days=1),
        paper_entry_deadline=now + timedelta(days=1),
        allow_ballot_modification=True,
    )
    for position, option_id in enumerate(["a", "b", "c"]):
        PollOption.objects.create(
            poll=poll, option_id=option_id, label_i18n={"fr": option_id.upper()}, position=position
        )
    for last, first, dob, parsed, _email, _ranking in _VOTERS:
        WorkingRollEntry.objects.create(
            birth_name=last,
            first_names=first,
            date_of_birth=dob,
            date_of_birth_parsed=parsed,
            list_types=["principale"],
        )
    open_poll(poll)
    poll = Poll.objects.get(pk=poll.pk)
    for last, first, dob, _parsed, email, ranking in _VOTERS:
        registration, token = registrations.register(
            poll,
            {
                "last_name": last,
                "first_names": first,
                "date_of_birth": dob,
                "email": email,
                "declared_on_honour": "on",
            },
            language="fr",
        )
        assert token is not None, "voter should auto-approve on an exact roll match"
        registrations.confirm_mailbox(registration)
        ballots.cast_online(poll, token, ranking)
    return poll


def test_t6_a_full_dump_recovers_no_voter_to_ballot_link(dumped_online_poll: Poll) -> None:
    """T-6: given every row of every table, nothing joins a voter to their
    online ballot — no shared id, no shared value, no equal hash, and the one
    sanctioned bridge (``PaperBallotLink``) is empty for online voting.
    """
    registrations_rows = _rows(Registration)
    ballot_rows = _rows(Ballot)
    audit_rows = _rows(AuditEvent)
    assert len(registrations_rows) == len(ballot_rows) == len(_VOTERS)

    # The only sanctioned voter↔ballot association is a paper ballot's link, and
    # there are no paper ballots here.
    assert _rows(PaperBallotLink) == []

    # §7: a voter_hash and a ballot_hash are different SHA outputs — the two
    # spaces do not even intersect, so one cannot be tested against the other.
    voter_hashes = {r["voter_hash"] for r in registrations_rows if r["voter_hash"] is not None}
    ballot_hashes = {b["ballot_hash"] for b in ballot_rows if b["ballot_hash"] is not None}
    assert len(voter_hashes) == len(ballot_hashes) == len(_VOTERS)
    assert voter_hashes.isdisjoint(ballot_hashes)

    # Nothing identifying on the voter side appears anywhere on the ballot side.
    ballot_blob = json.dumps(ballot_rows, default=str, ensure_ascii=False)
    for r in registrations_rows:
        assert str(r["id"]) not in ballot_blob
        assert bytes(r["voter_hash"]).hex() not in ballot_blob
        assert r["declared_last_name"] not in ballot_blob
        if r["email_canonical"]:
            assert r["email_canonical"] not in ballot_blob

    # …and no ballot id or tracking code appears on the voter side (registrations,
    # the roll snapshot, operator accounts, the audit log).
    voter_blob = json.dumps(
        registrations_rows + _rows(RollEntry) + _rows(User) + audit_rows,
        default=str,
        ensure_ascii=False,
    )
    for b in ballot_rows:
        assert str(b["id"]) not in voter_blob
        assert b["tracking_code"] not in voter_blob

    # No single audit event carries both a registration reference and a ballot
    # reference (§10): casting online writes no audit event at all, and the
    # registration events name only the registration.
    assert not any(str(e["object_ref"]).startswith("ballot:") for e in audit_rows)
    for event in audit_rows:
        payload = json.dumps([event["object_ref"], event["before"], event["after"]], default=str)
        names_a_ballot = any(
            str(b["id"]) in payload or b["tracking_code"] in payload for b in ballot_rows
        )
        assert not names_a_ballot
