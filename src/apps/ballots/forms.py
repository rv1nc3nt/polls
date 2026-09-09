# SPDX-License-Identifier: 0BSD
"""The ranking entry widget (§6.3, §6.4).

Numbered selects, one per proposition — the keyboard- and screen-reader-usable
alternative to drag-and-drop that R-6.3 and R-14.1 require. A voter gives each
proposition a rank number or leaves it blank; propositions sharing a number are
a tie, blanks are unranked and rank equal-last (R-10.4).

Display order is shuffled per render (R-6.2) with a system CSPRNG, and pinned in
a hidden field so a re-render after a validation error keeps the same order
rather than reshuffling under the voter. Admissibility is delegated to
``ranking.validate_ranking`` so the page and a direct POST are judged alike
(T-29).

Shared: the paper-entry screen (§6.5.5) uses it now; the online ballot page
(§6.3) will use the same form and the same template partial.
"""

from __future__ import annotations

import secrets
from typing import Any

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.elections.models import Poll

from .ranking import BallotRefused, validate_ranking


class RankingForm(forms.Form):
    """One ``rank_<option_id>`` select per proposition, plus a hidden ``order``.

    ``cleaned_data["ranking"]`` is the ``list[list[str]]`` the services and the
    canonical serialisation expect, groups in ascending rank, ids sorted within
    a group.
    """

    def __init__(
        self,
        *args: Any,
        poll: Poll,
        language: str,
        initial_ranking: list[list[str]] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        options = list(poll.options.all())
        ids = [option.option_id for option in options]

        pinned = self.data.get("order", "") if self.is_bound else ""
        order = [option_id for option_id in pinned.split(",") if option_id in ids]
        if sorted(order) != sorted(ids):
            order = list(ids)
            secrets.SystemRandom().shuffle(order)

        self.fields["order"] = forms.CharField(
            widget=forms.HiddenInput, required=False, initial=",".join(order)
        )
        rank_choices = [("", _("Non classé"))] + [
            (str(rank), str(rank)) for rank in range(1, len(options) + 1)
        ]
        labels = {
            option.option_id: (option.label(language) or option.option_id) for option in options
        }
        # Prefill from an existing ballot (§6.3 modification): the position of a
        # group in the ranking is its rank, ties share it, an unplaced option
        # stays blank. Ignored once the form is bound — a re-render after a
        # validation error keeps what the voter submitted.
        seeded: dict[str, str] = {}
        if initial_ranking and not self.is_bound:
            for position, group in enumerate(initial_ranking, start=1):
                for option_id in group:
                    seeded[option_id] = str(position)

        for option_id in order:
            self.fields[f"rank_{option_id}"] = forms.ChoiceField(
                choices=rank_choices,
                required=False,
                label=labels[option_id],
                initial=seeded.get(option_id, ""),
            )

        self._display_order = order
        self._option_ids = ids
        self._require_complete = poll.require_complete_ranking
        # Public: the template partial branches its instructions on it.
        self.allow_ties = poll.allow_ties_in_ballot

    def ranked_fields(self) -> list[tuple[str, forms.BoundField]]:
        """``(option_id, bound select)`` in display order, for the template."""
        return [(option_id, self[f"rank_{option_id}"]) for option_id in self._display_order]

    def clean(self) -> dict[str, Any]:
        cleaned: dict[str, Any] = super().clean() or {}
        by_rank: dict[int, list[str]] = {}
        for option_id in self._display_order:
            raw = cleaned.get(f"rank_{option_id}") or ""
            if raw:
                by_rank.setdefault(int(raw), []).append(option_id)
        ranking = [sorted(by_rank[rank]) for rank in sorted(by_rank)]
        try:
            validate_ranking(
                ranking,
                self._option_ids,
                require_complete=self._require_complete,
                allow_ties=self.allow_ties,
            )
        except BallotRefused as refused:
            raise forms.ValidationError(str(refused)) from refused
        cleaned["ranking"] = ranking
        return cleaned
