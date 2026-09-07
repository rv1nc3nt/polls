# SPDX-License-Identifier: 0BSD
"""Closure and the publication artefacts (§9, R-11).

Two aggregates are read here, from different tables, and they are never joined:
counts come from ``Registration``, the hash comes from ``Ballot`` (INV-1). They
meet only as two integers in a dictionary, which is exactly the pair of
irreconcilable lists an administrator is allowed to see (R-7.5).
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from typing import Any

from apps.ballots.models import Ballot
from apps.core.canonical import CanonicalBallot, canonical_serialisation, closure_hash
from apps.core.types import OptionId, TrackingCode
from apps.registrations.models import Channel, Registration, RegistrationState
from apps.tally.methods import Method, tally
from apps.tally.tiebreak import tiebreak_order

from .models import Poll, TiebreakRule


@dataclass(frozen=True)
class Closure:
    closure_hash: bytes
    counts: dict[str, int]


def live_ballots(poll: Poll) -> list[CanonicalBallot]:
    """The live set (§3.4) in the shape the serialiser and the tally want."""
    return [
        CanonicalBallot(
            TrackingCode(b.tracking_code), [[OptionId(o) for o in g] for g in b.ranking]
        )
        for b in Ballot.live.filter(poll=poll).only("tracking_code", "ranking")
    ]


def frozen_counts(poll: Poll) -> dict[str, int]:
    """Participation as at closure (§9).

    Computed on entry to ``closed`` and stored, never derived at publication
    time: they read ``Registration``, which the retention job deletes, and a
    late publication must still produce them (T-58). ``pending_email``
    registrations are excluded from turnout entirely (R-5.5, T-27).
    """
    active = Registration.objects.filter(poll=poll, state=RegistrationState.ACTIVE)
    online = active.filter(channel=Channel.ONLINE).count()
    paper = active.filter(channel=Channel.PAPER).count()
    registered = active.count()
    return {
        "registered": registered,
        "ballots_online": online,
        "ballots_paper": paper,
        "non_voters": registered - online - paper,
    }


def compute_closure(poll: Poll) -> Closure:
    """The closure hash and the frozen counts, as one operation (§9)."""
    return Closure(closure_hash=closure_hash(live_ballots(poll)), counts=frozen_counts(poll))


def published_csv(poll: Poll) -> str:
    """The anonymised ballot list (R-11.2).

    Exactly the live set and nothing else, so a third party can recompute the
    closure hash from this file alone (§9). One row per ballot; the ranking is
    the canonical JSON array of groups, so the CSV and the hashed bytes carry
    the same value in the same form.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["tracking_code", "ranking"])
    for ballot in sorted(live_ballots(poll), key=lambda b: str(b.tracking_code)):
        writer.writerow(
            [
                str(ballot.tracking_code),
                json.dumps(
                    [sorted(g) for g in ballot.ranking], ensure_ascii=False, separators=(",", ":")
                ),
            ]
        )
    return buffer.getvalue()


def publication(poll: Poll) -> dict[str, Any]:
    """Everything §9 requires published, as one JSON-serialisable document.

    Option **labels** appear here as a separate lookup table, never inside a
    ranking (§3.8): correcting a translation after publication must move
    neither the hash nor the result (T-23).
    """
    ballots = live_ballots(poll)
    options = [OptionId(o.option_id) for o in poll.options.all()]
    result = tally([b.ranking for b in ballots], options, Method(poll.tally_method))

    document: dict[str, Any] = {
        "poll_id": str(poll.id),
        "tally_method": poll.tally_method,
        "tally_method_version": poll.tally_method_version,
        "closure_hash": (poll.closure_hash or b"").hex(),
        "opening_seed": (poll.opening_seed or b"").hex(),
        "counts": poll.frozen_counts,
        "closure_override_reason": poll.closure_override_reason,
        "options": {o.option_id: o.label_i18n for o in poll.options.all()},
        "ballot_count": len(ballots),
        "winner": result.winner,
        "matrix": result.matrix,
        "derivation": result.derivation,
        "serialisation_bytes": len(canonical_serialisation(ballots)),
    }

    if result.tied:
        if poll.tiebreak_rule == TiebreakRule.COMPUTED and poll.closure_hash and poll.opening_seed:
            order = tiebreak_order(result.tied, bytes(poll.opening_seed), bytes(poll.closure_hash))
            document["tiebreak"] = {
                "rule": "computed",
                "tied": list(result.tied),
                "order": [{"option_id": o, "draw": d.hex()} for o, d in order],
                "winner": order[0][0],
            }
            document["winner"] = order[0][0]
        else:
            # §8.3: the tally reports the tie and stops; a poll admin enters the
            # result of the physical draw and it is logged.
            document["tiebreak"] = {"rule": "physical", "tied": list(result.tied)}

    if len(options) <= 4 and poll.tally_method == Method.SCHULZE:
        document["orderings"] = ordering_summary(ballots, options)
    return document


def ordering_summary(ballots: list[CanonicalBallot], options: list[OptionId]) -> dict[str, int]:
    """The per-ordering summary table (R-11.3).

    Six rows for three strictly ranked options, sufficient on its own to
    recompute the result. Only worth publishing while the option count is small.
    """
    summary: dict[str, int] = {}
    for ballot in ballots:
        key = ">".join("=".join(sorted(group)) for group in ballot.ranking)
        summary[key] = summary.get(key, 0) + 1
    return dict(sorted(summary.items()))
