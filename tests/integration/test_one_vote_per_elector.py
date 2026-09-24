# SPDX-License-Identifier: 0BSD
"""Every ordering of what can happen to one elector leaves them one vote at most.

The journeys elsewhere each pin one path through register, confirm, cast,
modify, key on paper, countersign, correct, delete, and review. The double-vote
question (INV-5, R-9.2, R-9.3, R-9.4) is about the paths nobody thought to
write down, so this walks all of them: every sequence of those actions up to
``DEPTH`` long, against one roll entry, each action attempted whether or not it
makes sense at that point — a refusal is an outcome like any other. After every
step the invariants must hold:

* the entry has at most one counted ballot behind it — its live paper ballot,
  or the online vote its one registration's channel records (INV-4, INV-5);
* the ballots in force match the channel indicators, source for source, so the
  closure counts agree with the hash (§9).
* no paper version counts without a countersignature of that very version by
  an operator other than its author (R-8.7, decision log #32).

The tree is explored depth-first with a savepoint per node, rolled back on the
way up, so each branch starts from exactly the state its prefix produced.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import timedelta

import pytest
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.audit import services as audit
from apps.audit.models import Action, AuditEvent, Reason
from apps.ballots import services as ballots
from apps.ballots.models import Ballot, BallotSource, BallotStatus, PaperBallotLink
from apps.core.models import User
from apps.core.types import Token
from apps.elections.models import Poll, PollOption, RollEntry, WorkingRollEntry
from apps.elections.windows import WindowClosed
from apps.registrations import services as registrations
from apps.registrations.models import Channel, Registration, RegistrationState
from tests.conftest import force_open

#: Three steps take seconds; each extra step multiplies the tree by the number
#: of actions (four took 46 s). ``POLLS_ORDERING_DEPTH=4`` for a deeper sweep.
DEPTH = int(os.environ.get("POLLS_ORDERING_DEPTH", "3"))
RANKING = [["a"], ["b"], ["c"]]
IN_FORCE = (BallotStatus.LIVE, BallotStatus.PENDING_COUNTERSIGN)


@dataclass(frozen=True)
class World:
    """What the elector holds outside the database: the tokens mailed to them,
    newest last, and a counter for fresh addresses."""

    tokens: tuple[Token, ...] = ()
    addresses: int = 0


@dataclass(frozen=True)
class Cast:
    poll: Poll
    entry: RollEntry
    keyer: User
    signer: User


#: What an action attempted out of turn may answer with. ``DoesNotExist`` is the
#: nothing-to-countersign, nothing-to-delete case: no paper ballot in force.
Refusals = (
    ballots.BallotRefused,
    registrations.RegistrationRefused,
    WindowClosed,
    PaperBallotLink.DoesNotExist,
)


def _register(c: Cast, w: World, dob: str) -> World:
    w = replace(w, addresses=w.addresses + 1)
    _registration, token = registrations.register(
        c.poll,
        {
            "last_name": "Dupont",
            "first_names": "Émile",
            "date_of_birth": dob,
            "email": f"emile{w.addresses}@example.fr",
            "declared_on_honour": "on",
        },
        language="fr",
    )
    return replace(w, tokens=(*w.tokens, token)) if token is not None else w


def register(c: Cast, w: World) -> World:
    return _register(c, w, "12/05/1970")


def review_and_approve(c: Cast, w: World) -> World:
    """A mistyped date: no match, the review queue, and a poll admin binding it
    to the entry (R-5.4)."""
    w = _register(c, w, "12/05/1971")
    pending = Registration.objects.filter(
        poll=c.poll, state=RegistrationState.PENDING_REVIEW
    ).latest("created_at")
    _registration, token = registrations.approve(
        pending, c.entry, Reason.IDENTITY_CONFIRMED_AT_MAIRIE, actor=c.signer
    )
    return replace(w, tokens=(*w.tokens, token))


def follow_link(c: Cast, w: World) -> World:
    for token in w.tokens:
        registrations.arrive(c.poll, token)
    return w


def cast(c: Cast, w: World) -> World:
    for token in reversed(w.tokens):
        try:
            ballots.cast_online(c.poll, token, RANKING)
        except Refusals:
            continue
        break
    return w


def vote_online(c: Cast, w: World) -> World:
    """Register, follow the link and cast, as one step — so that a three-step
    sweep still reaches what an online voter does next."""
    return cast(c, follow_link(c, register(c, w)))


def modify(c: Cast, w: World) -> World:
    for token in w.tokens:
        try:
            ballots.modify(c.poll, ballots.online_ballot_hash(c.poll, token), [["c"], ["b"], ["a"]])
        except Refusals:
            continue
    return w


def key_paper(c: Cast, w: World) -> World:
    ballots.enter_paper(c.poll, str(c.entry.pk), RANKING, str(c.keyer.pk), "fr")
    return w


def _paper_in_force(c: Cast) -> Ballot:
    link = PaperBallotLink.objects.get(poll=c.poll, roll_entry=c.entry, ballot__status__in=IN_FORCE)
    return link.ballot


def countersign(c: Cast, w: World) -> World:
    ballots.countersign(_paper_in_force(c), str(c.signer.pk))
    return w


def correct_paper(c: Cast, w: World) -> World:
    ballots.correct_paper(
        _paper_in_force(c), [["b"], ["a"], ["c"]], str(c.keyer.pk), Reason.KEYING_ERROR, ""
    )
    return w


def delete_paper(c: Cast, w: World) -> World:
    ballots.delete_paper(_paper_in_force(c), str(c.signer.pk), Reason.VOTER_REQUEST, "")
    return w


ACTIONS: dict[str, Callable[[Cast, World], World]] = {
    "register": register,
    "review": review_and_approve,
    "link": follow_link,
    "cast": cast,
    "vote": vote_online,
    "modify": modify,
    "key": key_paper,
    "countersign": countersign,
    "correct": correct_paper,
    "delete": delete_paper,
}


def _check(c: Cast, path: tuple[str, ...]) -> None:
    paper_live = PaperBallotLink.objects.filter(
        roll_entry=c.entry, ballot__status=BallotStatus.LIVE
    ).count()
    bound = Registration.objects.filter(roll_entry=c.entry).exclude(
        state=RegistrationState.REJECTED
    )
    assert bound.count() <= 1, path
    online = bound.filter(channel=Channel.ONLINE).count()
    assert paper_live + online <= 1, path

    by_channel = (
        Registration.objects.filter(poll=c.poll)
        .exclude(state=RegistrationState.REJECTED)
        .aggregate(
            online=Count("pk", filter=Q(channel=Channel.ONLINE)),
            paper=Count("pk", filter=Q(channel=Channel.PAPER)),
        )
    )
    in_force = Ballot.objects.filter(poll=c.poll, status__in=IN_FORCE)
    assert in_force.filter(source=BallotSource.ONLINE).count() == by_channel["online"], path
    assert in_force.filter(source=BallotSource.PAPER).count() == by_channel["paper"], path
    # R-8.7: no paper version is counted unless a second operator countersigned
    # *that version* — a name carried over from an earlier ranking does not count.
    for link in PaperBallotLink.objects.filter(poll=c.poll, ballot__status=BallotStatus.LIVE):
        signed = AuditEvent.objects.filter(
            action=Action.PAPER_BALLOT_COUNTERSIGNED, object_ref=audit.ref(link.ballot)
        ).exclude(actor_id=link.operator_id)
        assert signed.exists(), path
    # One person: never more than one online ballot chain live at once.
    assert Ballot.live.filter(poll=c.poll, source=BallotSource.ONLINE).count() <= 1, path


def _explore(c: Cast, w: World, path: tuple[str, ...], seen: list[int]) -> None:
    if len(path) == DEPTH:
        return
    for name, action in ACTIONS.items():
        here = (*path, name)
        savepoint = transaction.savepoint()
        try:
            try:
                with transaction.atomic():
                    after = action(c, w)
            except Refusals:
                after = w
            seen[0] += 1
            _check(c, here)
            _explore(c, after, here, seen)
        finally:
            transaction.savepoint_rollback(savepoint)


@pytest.mark.parametrize("modification", [True, False], ids=["modifiable", "cast-once"])
def test_no_ordering_gives_one_elector_two_counted_ballots(db: None, modification: bool) -> None:
    now = timezone.now()
    poll = Poll.objects.create(
        title_i18n={"fr": "Aménagement"},
        description_i18n={"fr": "Propositions."},
        languages=["fr"],
        opens_at=now - timedelta(days=1),
        closes_at=now + timedelta(days=1),
        paper_entry_deadline=now + timedelta(days=1),
        paper_requires_countersign=True,
        allow_ballot_modification=modification,
    )
    for position, option_id in enumerate(["a", "b", "c"]):
        PollOption.objects.create(
            poll=poll, option_id=option_id, label_i18n={"fr": option_id.upper()}, position=position
        )
    WorkingRollEntry.objects.create(
        birth_name="Dupont",
        first_names="Émile",
        date_of_birth="12/05/1970",
        date_of_birth_parsed="1970-05-12",
        list_types=["principale"],
    )
    force_open(poll)
    poll = Poll.objects.get(pk=poll.pk)
    c = Cast(
        poll=poll,
        entry=RollEntry.objects.get(poll=poll),
        keyer=User.objects.create_user(username="keyer", password="x", full_name="K"),
        signer=User.objects.create_user(username="signer", password="x", full_name="S"),
    )
    seen = [0]
    _explore(c, World(), (), seen)
    assert seen[0] == sum(len(ACTIONS) ** n for n in range(1, DEPTH + 1))
