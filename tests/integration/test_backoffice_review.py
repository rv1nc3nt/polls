# SPDX-License-Identifier: 0BSD
"""``backoffice.review`` (§6.5.4): the near-match search backing screen 4.

The HTTP-level test in ``test_registration_http.py`` pins the screen through
``poll_roll`` + ``near_matches(registration, roll)``, the path the queue view
takes to run one query for the whole queue rather than one per row. This pins
``near_matches``'s own fallback — called with no ``roll`` — against the same
result, since nothing else exercises that branch.
"""

from __future__ import annotations

from apps.backoffice import review
from apps.elections.models import Poll
from apps.registrations import services
from tests.conftest import force_open

FORM = {
    "last_name": "Dupond",
    "first_names": "Émile",
    "date_of_birth": "12/05/1970",
    "email": "emile.dupond@example.fr",
    "declared_on_honour": "on",
}


def test_near_matches_without_a_preloaded_roll_agrees_with_the_batched_call(
    open_window_poll: Poll,
) -> None:
    force_open(open_window_poll)
    registration, _ = services.register(open_window_poll, FORM, language="fr")

    batched = review.near_matches(registration, review.poll_roll(open_window_poll))
    on_demand = review.near_matches(registration)

    assert [m.entry.pk for m in on_demand] == [m.entry.pk for m in batched]
    assert on_demand and on_demand[0].same_dob
