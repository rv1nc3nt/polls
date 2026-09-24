# SPDX-License-Identifier: 0BSD
"""One poll, start to finish, through the screens the commune actually uses.

Every other test enters the lifecycle part-way — a ``force_open`` fixture, a
service call standing in for a screen. This one drives the whole of it over
HTTP with CSRF enforced, from the commune admin importing the roll to a third
party re-tallying the published CSV with the Rust verifier (T-10), and checks
at every step that nobody holds two counted ballots (INV-5, R-9.2, R-9.3):

* the roll is imported (§6.1) and the poll created (§6.5.2) with every paper
  formality on — signed form, countersignature, reconciliation (R-8.2);
* it is announced and opened by hand (R-3.10, R-3.4); roles are granted on
  screen 10 (R-2.1);
* electors register, confirm and vote online, one modifies (R-7.1), one goes
  through the review queue (R-5.4), one never opens the mail;
* paper ballots are keyed, refused a self-countersignature, countersigned by a
  second operator (R-8.7), one deleted and its elector back online (R-9.4);
* every crossing of the two channels is attempted and refused;
* online voting closes, one paper ballot is keyed in the transcription window
  that follows (§6.4), the reconciliation is signed (R-8.6), the poll closes,
  is published, and the public artefacts agree with each other, with the
  participation counts and with an independent re-tally (R-11).

Time "passes" by moving ``closes_at`` and ``paper_entry_deadline`` — the two
settings that still move (R-3.4) — rather than by faking the clock, which the
INV-2 trigger reads from the database and a patched Python clock would not
reach.
"""

from __future__ import annotations

import csv
import io
import json
import re
import shutil
import subprocess
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from django.core import mail as django_mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import Count, Q
from django.test import Client
from django.utils import timezone

from apps.audit.models import Action, AuditEvent
from apps.ballots import services as ballots
from apps.ballots.models import Ballot, BallotSource, BallotStatus, PaperBallotLink
from apps.core.canonical import CanonicalBallot, closure_hash
from apps.core.models import User
from apps.core.types import OptionId, TrackingCode
from apps.elections.models import Poll, PollState, RollEntry
from apps.registrations.models import Channel, Registration, RegistrationState

if TYPE_CHECKING:
    from django.test.client import _MonkeyPatchedWSGIResponse as HttpResponse

CaptureOnCommit = Callable[..., AbstractContextManager[list[Any]]]

VERIFIER_DIR = Path(__file__).resolve().parents[2] / "verifier"

ROLL_CSV = (
    "Nom de naissance;Nom d'usage;Prénoms;Date de naissance;Type de liste\n"
    "Dupont;;Émile;12/05/1970;Liste principale\n"
    "Martin;;Alice;01/01/1980;Liste principale\n"
    "Petit;;Jeanne;03/03/1975;Liste principale\n"
    "Bernard;;Paul;04/04/1965;Liste principale\n"
    "Durand;;Luc;05/05/1990;Liste principale\n"
    "Leroy;;Marc;06/06/1955;Liste principale\n"
    "Roux;;Sophie;07/07/1988;Liste principale\n"
)
ROLL_MAPPING = {
    "col_birth_name": "Nom de naissance",
    "col_usual_name": "Nom d'usage",
    "col_first_names": "Prénoms",
    "col_date_of_birth": "Date de naissance",
    "col_list_type": "Type de liste",
}

_CSRF = re.compile(r'name="csrfmiddlewaretoken" value="([^"]+)"')
_LINK = re.compile(r"/bulletin/[0-9a-f-]+/acces/(\S+?)/")
_CODE = re.compile(r"\b([0-9A-Z]{5}-[0-9A-Z]{5})\b")


def _ranked(*option_ids: str) -> dict[str, str]:
    """The ranking widget's POST for a strict order (§6.3, R-6.3)."""
    data = {"order": ",".join(option_ids)}
    data.update({f"rank_{option_id}": str(n) for n, option_id in enumerate(option_ids, 1)})
    return data


class Browser:
    """A test client that has to fetch a page to be able to post from it.

    CSRF is enforced, so every POST carries the token the page it was
    submitted from rendered — the same constraint a browser is under.
    """

    def __init__(self, address: str) -> None:
        self.client = Client(enforce_csrf_checks=True, REMOTE_ADDR=address)

    def get(self, url: str) -> HttpResponse:
        return self.client.get(url)

    def submit(self, page: str, data: dict[str, Any], *, to: str | None = None) -> HttpResponse:
        shown = self.client.get(page)
        assert shown.status_code == 200, (page, shown.status_code)
        token = _CSRF.search(shown.content.decode())
        assert token, f"no form with a CSRF token on {page}"
        return self.client.post(to or page, {**data, "csrfmiddlewaretoken": token.group(1)})

    def login(self, username: str) -> None:
        response = self.submit(
            "/fr/mairie/connexion/", {"username": username, "password": "motdepasse-1"}
        )
        assert response.status_code == 302, response.content.decode()


def _account(username: str, *, commune_admin: bool = False) -> User:
    return User.objects.create_user(
        username=username,
        password="motdepasse-1",
        full_name=username.title(),
        is_commune_admin=commune_admin,
    )


def _dt(value: Any) -> str:
    return str(timezone.localtime(value).strftime("%Y-%m-%dT%H:%M"))


def _mailed_token() -> str:
    match = _LINK.search(str(django_mail.outbox[-1].body))
    assert match, django_mail.outbox[-1].body
    return match.group(1)


class Elector:
    """A member of the public: their own device, their own address."""

    def __init__(self, poll: Poll, n: int, capture: CaptureOnCommit) -> None:
        self.poll = poll
        self.browser = Browser(f"192.0.2.{n}")
        self.capture = capture
        self.token: str | None = None

    @property
    def access(self) -> str:
        assert self.token
        return f"/fr/bulletin/{self.poll.pk}/acces/{self.token}/"

    def register(self, last: str, first: str, dob: str, email: str) -> HttpResponse:
        django_mail.outbox.clear()
        with self.capture(execute=True):
            response = self.browser.submit(
                f"/fr/inscription/{self.poll.pk}/",
                {
                    "last_name": last,
                    "first_names": first,
                    "date_of_birth": dob,
                    "email": email,
                    "declared_on_honour": "on",
                },
            )
        if response.status_code == 302 and django_mail.outbox:
            self.token = _mailed_token()
        return response

    def cast(self, *ranking: str) -> str:
        """Follow the mailed link, cast, and read the tracking code off the
        receipt page (R-6.4)."""
        with self.capture(execute=True):
            response = self.browser.submit(self.access, _ranked(*ranking))
        assert response.status_code == 302, response.content.decode()
        receipt = self.browser.get(response["Location"]).content.decode()
        code = _CODE.search(receipt)
        assert code, receipt
        return code.group(1).replace("-", "")


def _live_ballots_per_elector(poll: Poll) -> int:
    """How many counted ballots the most-represented roll entry has behind it.

    A paper ballot is found through its link; an online one cannot be (§7), so
    it is counted through the channel indicator of the one registration bound
    to the entry (INV-4). Anything above 1 is a double vote.
    """
    worst = 0
    for entry in RollEntry.objects.filter(poll=poll):
        paper = PaperBallotLink.objects.filter(
            roll_entry=entry, ballot__status=BallotStatus.LIVE
        ).count()
        online = (
            Registration.objects.filter(roll_entry=entry, channel=Channel.ONLINE)
            .exclude(state=RegistrationState.REJECTED)
            .count()
        )
        worst = max(worst, paper + online)
    return worst


def _assert_no_double_vote(poll: Poll) -> None:
    assert _live_ballots_per_elector(poll) <= 1
    by_channel = (
        Registration.objects.filter(poll=poll)
        .exclude(state=RegistrationState.REJECTED)
        .aggregate(
            online=Count("pk", filter=Q(channel=Channel.ONLINE)),
            paper=Count("pk", filter=Q(channel=Channel.PAPER)),
        )
    )
    in_force = Ballot.objects.filter(
        poll=poll, status__in=[BallotStatus.LIVE, BallotStatus.PENDING_COUNTERSIGN]
    )
    assert in_force.filter(source=BallotSource.ONLINE).count() == by_channel["online"]
    assert in_force.filter(source=BallotSource.PAPER).count() == by_channel["paper"]


@pytest.mark.django_db(transaction=False)
def test_a_poll_from_roll_import_to_independent_re_tally(
    django_capture_on_commit_callbacks: CaptureOnCommit, tmp_path: Path
) -> None:
    cache.clear()
    secretary = _account("secretaire", commune_admin=True)
    mayor = _account("maire")
    agent1 = _account("agent1")
    agent2 = _account("agent2")

    # --- Screen 3: the commune admin imports the roll (§6.1) ----------------
    mairie = Browser("198.51.100.1")
    mairie.login("secretaire")
    upload = SimpleUploadedFile("liste.csv", ROLL_CSV.encode(), content_type="text/csv")
    token = _CSRF.search(mairie.get("/fr/mairie/liste-electorale/").content.decode())
    assert token
    uploaded = mairie.client.post(
        "/fr/mairie/liste-electorale/",
        {"file": upload, "csrfmiddlewaretoken": token.group(1)},
    )
    assert uploaded.status_code == 302
    applied = mairie.submit(
        "/fr/mairie/liste-electorale/verification/", {**ROLL_MAPPING, "action": "confirm"}
    )
    assert applied.status_code == 302
    assert AuditEvent.objects.filter(action=Action.ROLL_IMPORTED).count() == 1

    # --- Poll creation, every paper formality on (R-3.1, R-8.2) -------------
    now = timezone.now()
    created = mairie.submit(
        "/fr/mairie/nouveau/",
        {
            "opens_at": _dt(now + timedelta(days=1)),
            "closes_at": _dt(now + timedelta(days=8)),
            "paper_entry_deadline": _dt(now + timedelta(days=9)),
            "timezone": "Europe/Paris",
            "tally_method": "schulze",
            "tally_method_version": "1",
            "tiebreak_rule": "computed",
            "eligible_list_types": ["principale"],
            "default_language": "fr",
            "title_fr": "Aménagement de la place",
            "description_fr": "Trois propositions.",
            "allow_ballot_modification": "on",
            "paper_requires_signed_form": "on",
            "paper_requires_countersign": "on",
            "paper_requires_reconciliation": "on",
            "opt-TOTAL_FORMS": "3",
            "opt-INITIAL_FORMS": "0",
            "opt-MIN_NUM_FORMS": "0",
            "opt-MAX_NUM_FORMS": "1000",
            "opt-0-option_id": "a",
            "opt-0-label_fr": "Fontaine",
            "opt-1-option_id": "b",
            "opt-1-label_fr": "Kiosque",
            "opt-2-option_id": "c",
            "opt-2-label_fr": "Arbres",
        },
    )
    assert created.status_code == 302, created.content.decode()
    poll = Poll.objects.get()
    assert poll.state == PollState.DRAFT and not poll.is_sandbox
    base = f"/fr/mairie/scrutin/{poll.pk}"

    # --- Screen 10: roles (R-2.1) -------------------------------------------
    roles = f"/fr/mairie/comptes/roles/?scrutin={poll.pk}"
    granted = mairie.submit(
        roles,
        {
            "poll": str(poll.pk),
            "action": "sync_roles",
            "grid_account": [str(u.pk) for u in (secretary, mayor, agent1, agent2)],
            f"role__{mayor.pk}__poll_admin": "on",
            f"role__{agent1.pk}__entry_operator": "on",
            f"role__{agent2.pk}__entry_operator": "on",
        },
        to="/fr/mairie/comptes/roles/",
    )
    assert granted.status_code == 302
    # The commune admin who created the poll holds nothing on it (§3.7).
    assert mairie.get(f"{base}/configuration/").status_code == 403

    admin = Browser("198.51.100.2")
    admin.login("maire")
    op1 = Browser("198.51.100.3")
    op1.login("agent1")
    op2 = Browser("198.51.100.4")
    op2.login("agent2")

    # --- Screen 2: announce, then open by hand ahead of opens_at ------------
    assert (
        admin.submit(
            f"{base}/configuration/", {"confirmed": "1", "action": "announce_poll"}
        ).status_code
        == 302
    )
    assert (
        admin.submit(
            f"{base}/configuration/", {"confirmed": "1", "action": "open_poll"}
        ).status_code
        == 302
    )
    poll.refresh_from_db()
    assert poll.state == PollState.OPEN
    assert poll.roll_entries.count() == 7
    entry = {e.birth_name: e for e in poll.roll_entries.all()}
    capture = django_capture_on_commit_callbacks

    # --- Online: register, confirm and vote, then change one's mind ---------
    dupont = Elector(poll, 1, capture)
    assert dupont.register("DUPONT", "Emile", "12/05/1970", "emile@example.fr").status_code == 302
    dupont_code = dupont.cast("a", "b", "c")
    # R-7.1: the same link now leads to the modification page, token-free.
    to_modify = dupont.browser.get(dupont.access)
    assert to_modify.status_code == 302 and to_modify["Location"].endswith("/modifier/")
    modified = dupont.browser.submit(to_modify["Location"], _ranked("b", "a", "c"))
    assert modified.status_code == 302

    leroy = Elector(poll, 2, capture)
    assert leroy.register("Leroy", "Marc", "06/06/1955", "marc@example.fr").status_code == 302
    assert leroy.browser.get(leroy.access).status_code == 200  # confirms, does not vote

    bernard = Elector(poll, 3, capture)
    assert bernard.register("Bernard", "Paul", "04/04/1965", "paul@example.fr").status_code == 302
    # ... and never opens the mail: he will vote on paper instead.

    # A mistyped date of birth matches nothing and goes to review (R-5.4).
    durand = Elector(poll, 4, capture)
    assert durand.register("Durand", "Luc", "05/05/1991", "luc@example.fr").status_code == 302
    assert durand.token is None
    pending = Registration.objects.get(poll=poll, state=RegistrationState.PENDING_REVIEW)
    django_mail.outbox.clear()
    with capture(execute=True):
        decided = admin.submit(
            f"{base}/inscriptions/",
            {
                "registration": str(pending.pk),
                "decision": "approve",
                "approve_reason": "identity_confirmed_at_mairie",
                "roll_entry": str(entry["Durand"].pk),
            },
            to=f"{base}/inscriptions/decision/",
        )
    assert decided.status_code == 302
    durand.token = _mailed_token()
    durand_code = durand.cast("a", "c", "b")

    # --- Paper: keyed, refused a self-countersignature, countersigned -------
    def key_paper(operator: Browser, surname: str, *ranking: str) -> Ballot | None:
        search = f"{base}/bulletin-papier/?q={surname}"
        before = set(Ballot.objects.filter(poll=poll).values_list("pk", flat=True))
        chosen = operator.submit(search, {"q": surname, "roll_entry": str(entry[surname].pk)})
        if chosen.status_code == 302:
            # A paper ballot already in force: handed to screen 6, not keyed twice.
            assert "/bulletin-papier/" in chosen["Location"]
            return None
        assert chosen.status_code == 200
        if "Enregistrer le bulletin papier" not in chosen.content.decode():
            return None  # the screen was a dead end
        token = _CSRF.search(chosen.content.decode())
        assert token
        operator.client.post(
            f"{base}/bulletin-papier/",
            {
                "csrfmiddlewaretoken": token.group(1),
                "q": surname,
                "roll_entry": str(entry[surname].pk),
                "action": "record",
                **_ranked(*ranking),
            },
        )
        new = Ballot.objects.filter(poll=poll).exclude(pk__in=before)
        return new.get() if new.exists() else None

    def countersign(operator: Browser, ballot: Ballot) -> None:
        operator.submit(f"{base}/contreseing/", {"ballot": str(ballot.pk)})
        ballot.refresh_from_db()

    martin = key_paper(op1, "Martin", "a", "b", "c")
    assert martin is not None and martin.status == BallotStatus.PENDING_COUNTERSIGN
    countersign(op1, martin)
    assert martin.status == BallotStatus.PENDING_COUNTERSIGN  # R-8.7: a *second* operator
    countersign(op2, martin)
    assert martin.status == BallotStatus.LIVE

    # Bernard registered online but never confirmed; he is keyed on paper.
    bernard_paper = key_paper(op1, "Bernard", "c", "b", "a")
    assert bernard_paper is not None
    countersign(op2, bernard_paper)

    # Petit is keyed, the ballot deleted at her request, and she votes online.
    petit_paper = key_paper(op1, "Petit", "c", "a", "b")
    assert petit_paper is not None
    deleted = op2.submit(
        f"{base}/bulletin-papier/{petit_paper.pk}/",
        {"action": "delete", "reason": "voter_request", "note": ""},
    )
    assert deleted.status_code == 302
    petit_paper.refresh_from_db()
    assert petit_paper.status == BallotStatus.DELETED
    petit = Elector(poll, 5, capture)
    assert petit.register("Petit", "Jeanne", "03/03/1975", "jeanne@example.fr").status_code == 302
    petit_code = petit.cast("a", "b", "c")
    _assert_no_double_vote(poll)

    # --- Every crossing of the two channels is refused ----------------------
    # R-9.3: an online voter cannot be keyed on paper — the screen is a dead
    # end, and a hand-built POST gets no further than the form would.
    for online_voter in ("Dupont", "Petit", "Durand"):
        assert key_paper(op1, online_voter, "c", "b", "a") is None
        with pytest.raises(ballots.BallotRefused):
            ballots.enter_paper(
                poll, str(entry[online_voter].pk), [["c"], ["b"], ["a"]], str(agent1.pk), "fr"
            )
    # R-9.2: a paper voter cannot register online, nor use a link they hold.
    intruder = Elector(poll, 6, capture)
    refused = intruder.register("Martin", "Alice", "01/01/1980", "alice@example.fr")
    assert refused.status_code == 200 and intruder.token is None
    # A second paper ballot for the same elector hands off to correction.
    assert key_paper(op2, "Martin", "b", "a", "c") is None
    # A spent or foreign link casts nothing more.
    again = dupont.browser.client.post(dupont.access, _ranked("c", "b", "a"))
    assert again.status_code in (302, 403)
    _assert_no_double_vote(poll)

    # --- Online voting closes; paper transcription continues (§6.4) ---------
    poll.refresh_from_db()
    online_end = poll.opens_at + (timezone.now() - poll.opens_at) / 2
    Poll.objects.filter(pk=poll.pk).update(closes_at=online_end)
    late = Elector(poll, 7, capture)
    assert late.register("Roux", "Sophie", "07/07/1988", "sophie@example.fr").status_code == 200
    assert not Registration.objects.filter(poll=poll, email_canonical="sophie@example.fr").exists()
    roux = key_paper(op1, "Roux", "a", "c", "b")
    assert roux is not None
    countersign(op2, roux)
    # Dupont can no longer change his vote, and Bernard's link opens nothing.
    assert dupont.browser.get(dupont.access)["Location"].endswith("/info/indisponible/")
    assert bernard.browser.get(bernard.access)["Location"].endswith("/info/indisponible/")

    # Closing before the transcription deadline is refused (T-68).
    assert admin.client.post(
        f"{base}/configuration/", {"confirmed": "1", "action": "close_poll"}
    ).status_code in (403,)
    Poll.objects.filter(pk=poll.pk).update(
        paper_entry_deadline=online_end + (timezone.now() - online_end) / 2
    )

    # --- Screen 9: reconciliation (R-8.6), closure, publication -------------
    reconciled = admin.submit(
        f"{base}/depouillement/",
        {
            "confirmed": "1",
            "action": "record_reconciliation",
            "forms_retained_count": "3",
            "note": "",
        },
    )
    assert reconciled.status_code == 302
    assert poll.reconciliation_record.discrepancy == 0
    closed = admin.submit(
        f"{base}/configuration/", {"confirmed": "1", "action": "close_poll", "reason": ""}
    )
    assert closed.status_code == 302, closed.content.decode()
    poll.refresh_from_db()
    assert poll.state == PollState.CLOSED
    assert (
        admin.submit(f"{base}/depouillement/", {"confirmed": "1", "action": "publish"}).status_code
        == 302
    )
    poll.refresh_from_db()
    assert poll.state == PollState.PUBLISHED

    # --- What a third party sees --------------------------------------------
    public = Browser("203.0.113.9")
    published_csv = public.get(f"/fr/scrutin/{poll.pk}/resultats/?format=csv")
    assert published_csv.status_code == 200
    document = public.client.get(f"/fr/scrutin/{poll.pk}/resultats/?format=json").json()
    rows = list(csv.DictReader(io.StringIO(published_csv.content.decode())))

    paper_codes = {b.tracking_code for b in (martin, bernard_paper, roux)}
    online_codes = {dupont_code, petit_code, durand_code}
    assert {row["tracking_code"] for row in rows} == paper_codes | online_codes
    assert petit_paper.tracking_code not in {row["tracking_code"] for row in rows}
    by_code = {row["tracking_code"]: row["ranking"] for row in rows}
    assert by_code[dupont_code] == '[["b"],["a"],["c"]]'  # the modification, not the first cast

    # The counts the publication carries agree with the ballots it lists.
    counts = document["counts"]
    assert counts == {
        "registered": 7,  # Dupont, Leroy, Bernard, Durand, Martin, Petit, Roux
        "ballots_online": 3,
        "ballots_paper": 3,
        "paper_uncountersigned": 0,
        "non_voters": 1,
    }
    assert document["ballot_count"] == counts["ballots_online"] + counts["ballots_paper"] == 6

    # The closure hash recomputes from the CSV alone (R-11.1).
    recomputed = closure_hash(
        [
            CanonicalBallot(
                TrackingCode(row["tracking_code"]),
                [[OptionId(o) for o in group] for group in json.loads(row["ranking"])],
            )
            for row in rows
        ]
    )
    assert recomputed.hex() == document["closure_hash"] == bytes(poll.closure_hash or b"").hex()
    assert document["winner"] == "a"
    _assert_no_double_vote(poll)

    # --- T-10: the independent verifier agrees ------------------------------
    if shutil.which("cargo") is None:
        pytest.skip("no Rust toolchain; the verifier job runs this part in CI")
    subprocess.run(
        ["cargo", "build", "--release", "--quiet"],  # noqa: S607
        cwd=VERIFIER_DIR,
        check=True,
        capture_output=True,
    )
    csv_path = tmp_path / "bulletins.csv"
    csv_path.write_bytes(published_csv.content)
    verdict = subprocess.run(  # noqa: S603
        [
            str(VERIFIER_DIR / "target" / "release" / "polls-verifier"),
            str(csv_path),
            "--closure-hash",
            document["closure_hash"],
            "--opening-seed",
            document["opening_seed"],
            "--winner",
            document["winner"],
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert verdict.returncode == 0, verdict.stdout + verdict.stderr
    assert "AGREES" in verdict.stdout
