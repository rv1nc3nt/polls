# SPDX-License-Identifier: 0BSD
"""T-46 — a missing translation falls back, never to an empty string (§3.8)."""

from __future__ import annotations

from apps.elections.models import Poll


def test_t46_missing_translation_falls_back_to_the_poll_default() -> None:
    poll = Poll(
        languages=["fr", "en"],
        title_i18n={"fr": "Aménagement de la place"},
        description_i18n={"fr": "Trois propositions.", "en": "Three proposals."},
    )
    assert poll.title("en") == "Aménagement de la place"
    assert poll.description("en") == "Three proposals."
    assert poll.title("de") == "Aménagement de la place"


def test_t46_default_language_is_the_first_enabled_one() -> None:
    assert Poll(languages=["en", "fr"]).default_language == "en"
    assert Poll(languages=[]).default_language == "fr"
