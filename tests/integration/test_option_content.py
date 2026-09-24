# SPDX-License-Identifier: 0BSD
"""A poll's own description and each option's extended description (R-3.12,
§3.1 bis): rendering, the shared poll-level image library's upload/removal,
and the screen-2 write path and views built on both.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import Client

from apps.audit.models import Action, AuditEvent
from apps.core.models import PollRole, Role, User
from apps.elections import config, pollimages, richtext
from apps.elections.models import Poll, PollImage
from tests.conftest import force_open

CaptureOnCommit = Callable[..., AbstractContextManager[list[Any]]]

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
_OTHER_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 33


@pytest.fixture
def admin_user(db: None) -> User:
    return User.objects.create_user(username="p.martin", password="x", full_name="P. Martin")


# --- rendering (apps.elections.richtext) ------------------------------------


def test_details_falls_back_and_is_never_a_blocker(open_window_poll: Poll) -> None:
    option = open_window_poll.options.first()
    assert option is not None
    # No details in any language: an empty string, not an error, and not a
    # gap `missing_translations` reports (§3.8, R-3.12).
    assert richtext.render_option_details(option) == ""
    assert f"option:{option.option_id}" not in open_window_poll.missing_translations()


def test_poll_description_is_rendered_as_markdown(open_window_poll: Poll) -> None:
    open_window_poll.description_i18n = {"fr": "## Bienvenue\n\n**Votez** avant la clôture."}
    open_window_poll.save(update_fields=["description_i18n"])

    html = richtext.render_poll_description(open_window_poll)
    assert "<h2>Bienvenue</h2>" in html
    assert "<strong>Votez</strong>" in html


def test_markdown_is_rendered_and_scripts_and_iframes_are_stripped(
    open_window_poll: Poll,
) -> None:
    option = open_window_poll.options.first()
    assert option is not None
    option.details_i18n = {
        "fr": (
            "## Titre\n\n"
            "**gras** et [lien](https://example.org).\n\n"
            '<script>alert(1)</script><iframe src="https://evil.example/"></iframe>'
        )
    }
    option.save(update_fields=["details_i18n"])

    html = richtext.render_option_details(option)
    assert "<h2>Titre</h2>" in html
    assert "<strong>gras</strong>" in html
    assert '<a href="https://example.org"' in html
    assert "<script>" not in html
    assert "evil.example" not in html
    assert "<iframe" not in html or "youtube-nocookie" in html


def test_youtube_fence_becomes_the_one_sandboxed_iframe(open_window_poll: Poll) -> None:
    option = open_window_poll.options.first()
    assert option is not None
    option.details_i18n = {"fr": "Texte avant.\n\n```youtube\ndQw4w9WgXcQ\n```\n\nTexte après."}
    option.save(update_fields=["details_i18n"])

    html = richtext.render_option_details(option)
    assert "youtube-nocookie.com/embed/dQw4w9WgXcQ" in html
    assert html.count("<iframe") == 1
    assert "Texte avant." in html
    assert "Texte après." in html


def test_youtube_fence_with_an_invalid_id_is_dropped_not_guessed_at(
    open_window_poll: Poll,
) -> None:
    """An id that fails the eleven-character check — including one carrying
    an injection attempt — drops the whole block rather than emitting
    anything built from it (§3.1 bis)."""
    option = open_window_poll.options.first()
    assert option is not None
    option.details_i18n = {"fr": '```youtube\n"; DROP TABLE elections_poll; --\n```'}
    option.save(update_fields=["details_i18n"])

    html = richtext.render_option_details(option)
    assert "<iframe" not in html
    assert "DROP TABLE" not in html


def test_youtube_url_alone_on_its_line_becomes_an_iframe_too(open_window_poll: Poll) -> None:
    option = open_window_poll.options.first()
    assert option is not None
    option.details_i18n = {"fr": "Texte avant.\n\nhttps://youtu.be/dQw4w9WgXcQ\n\nTexte après."}
    option.save(update_fields=["details_i18n"])

    html = richtext.render_option_details(option)
    assert "youtube-nocookie.com/embed/dQw4w9WgXcQ" in html
    assert html.count("<iframe") == 1
    assert "Texte avant." in html
    assert "Texte après." in html


def test_youtube_url_alone_on_its_line_embeds_with_crlf_line_endings(
    open_window_poll: Poll,
) -> None:
    """A `<textarea>` POST carries `\\r\\n` line breaks per the HTML forms
    spec no matter the operator's own OS, and nothing normalises it before
    the JSONField write — so the "alone on its own line" test must tolerate
    a stray `\\r` or a pasted link silently stops embedding."""
    option = open_window_poll.options.first()
    assert option is not None
    option.details_i18n = {
        "fr": "Texte avant.\r\n\r\nhttps://youtu.be/dQw4w9WgXcQ?si=abc123DEF45\r\n\r\nTexte après."
    }
    option.save(update_fields=["details_i18n"])

    html = richtext.render_option_details(option)
    assert "youtube-nocookie.com/embed/dQw4w9WgXcQ" in html
    assert html.count("<iframe") == 1


def test_youtube_watch_url_with_extra_query_params_embeds(open_window_poll: Poll) -> None:
    option = open_window_poll.options.first()
    assert option is not None
    option.details_i18n = {"fr": "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL123&t=42s"}
    option.save(update_fields=["details_i18n"])

    html = richtext.render_option_details(option)
    assert "youtube-nocookie.com/embed/dQw4w9WgXcQ" in html
    assert html.count("<iframe") == 1


def test_youtube_link_as_markdown_link_or_mid_sentence_stays_a_link(
    open_window_poll: Poll,
) -> None:
    """Only a line that is *nothing but* the URL is an embed request — the
    operator who deliberately wrote a link keeps a link (§3.1 bis)."""
    option = open_window_poll.options.first()
    assert option is not None
    option.details_i18n = {
        "fr": (
            "[Regardez la vidéo](https://youtu.be/dQw4w9WgXcQ)\n\n"
            "Voir aussi https://youtu.be/dQw4w9WgXcQ pour plus de détails."
        )
    }
    option.save(update_fields=["details_i18n"])

    html = richtext.render_option_details(option)
    assert "<iframe" not in html
    assert html.count('href="https://youtu.be/dQw4w9WgXcQ"') == 1


def test_image_reference_resolves_across_the_poll_but_not_a_foreign_poll(
    open_window_poll: Poll, admin_user: User
) -> None:
    """The library is shared by the whole poll (R-3.12): the same image
    resolves from the poll's own description and from any of its options —
    but not from a different poll's content."""
    option_a, option_b = list(open_window_poll.options.all())[:2]
    image = pollimages.add_poll_image(
        open_window_poll, SimpleUploadedFile("a.png", _PNG), alt_text="", actor=admin_user
    )

    open_window_poll.description_i18n = {"fr": f"![alt](image:{image.short_id})"}
    open_window_poll.save(update_fields=["description_i18n"])
    assert image.file.url in richtext.render_poll_description(open_window_poll)

    option_a.details_i18n = {"fr": f"![alt](image:{image.short_id})"}
    option_a.save(update_fields=["details_i18n"])
    assert image.file.url in richtext.render_option_details(option_a)

    option_b.details_i18n = {"fr": f"![alt](image:{image.short_id})"}
    option_b.save(update_fields=["details_i18n"])
    assert image.file.url in richtext.render_option_details(option_b)

    # A foreign poll's image id is dropped, not followed.
    other_poll = Poll.objects.create(
        title_i18n={"fr": "Autre scrutin"},
        description_i18n={"fr": "…"},
        languages=["fr"],
        opens_at=open_window_poll.opens_at,
        closes_at=open_window_poll.closes_at,
        paper_entry_deadline=open_window_poll.paper_entry_deadline,
    )
    other_poll.description_i18n = {"fr": f"![alt](image:{image.short_id})"}
    other_poll.save(update_fields=["description_i18n"])
    assert image.file.url not in richtext.render_poll_description(other_poll)


def test_image_reference_with_empty_alt_falls_back_to_the_library_alt_text(
    open_window_poll: Poll, admin_user: User
) -> None:
    """``![](image:n)`` takes ``PollImage.alt_text`` as its default — the
    field would otherwise be write-only, since nothing else reads it — while
    ``![texte](image:n)`` still overrides it for that one reference."""
    option = open_window_poll.options.first()
    assert option is not None
    image = pollimages.add_poll_image(
        open_window_poll,
        SimpleUploadedFile("a.png", _PNG),
        alt_text="Vue depuis la mairie",
        actor=admin_user,
    )

    option.details_i18n = {"fr": f"![](image:{image.short_id})"}
    option.save(update_fields=["details_i18n"])
    assert 'alt="Vue depuis la mairie"' in richtext.render_option_details(option)

    option.details_i18n = {"fr": f"![Autre texte](image:{image.short_id})"}
    option.save(update_fields=["details_i18n"])
    html = richtext.render_option_details(option)
    assert 'alt="Autre texte"' in html
    assert "Vue depuis la mairie" not in html


def test_image_reference_size_suffix_selects_a_css_class(
    open_window_poll: Poll, admin_user: User
) -> None:
    """The optional ``:small``/``:medium``/``:large`` suffix on an
    ``image:<n>`` reference (docs/specification-decision-log.md #23) picks a
    display-size class; omitted, the image renders exactly as it always has,
    with no class attribute at all."""
    option = open_window_poll.options.first()
    assert option is not None
    image = pollimages.add_poll_image(
        open_window_poll, SimpleUploadedFile("a.png", _PNG), alt_text="Vue", actor=admin_user
    )

    option.details_i18n = {"fr": f"![](image:{image.short_id}:large)"}
    option.save(update_fields=["details_i18n"])
    html = richtext.render_option_details(option)
    assert 'class="poll-image--large"' in html
    assert 'alt="Vue"' in html
    assert image.file.url in html

    option.details_i18n = {"fr": f"![](image:{image.short_id})"}
    option.save(update_fields=["details_i18n"])
    assert "class=" not in richtext.render_option_details(option)


def test_image_reference_size_suffix_alt_text_is_escaped(
    open_window_poll: Poll, admin_user: User
) -> None:
    """The sized path builds a raw ``<img>`` tag itself (§3.1 bis point 3),
    so an override alt text carrying a quote must not break out of the
    attribute it sits in."""
    option = open_window_poll.options.first()
    assert option is not None
    image = pollimages.add_poll_image(
        open_window_poll, SimpleUploadedFile("a.png", _PNG), alt_text="", actor=admin_user
    )

    option.details_i18n = {"fr": f'![Une "citation"](image:{image.short_id}:small)'}
    option.save(update_fields=["details_i18n"])
    html = richtext.render_option_details(option)
    assert 'alt="Une &quot;citation&quot;"' in html
    assert 'class="poll-image--small"' in html


def test_image_reference_bad_size_suffix_is_not_recognised(
    open_window_poll: Poll, admin_user: User
) -> None:
    """Only the three named sizes are a size suffix at all — anything else
    after the colon is just part of an unresolved reference, dropped like any
    other malformed ``image:`` syntax rather than guessed at."""
    option = open_window_poll.options.first()
    assert option is not None
    image = pollimages.add_poll_image(
        open_window_poll, SimpleUploadedFile("a.png", _PNG), alt_text="", actor=admin_user
    )

    option.details_i18n = {"fr": f"![alt](image:{image.short_id}:huge)"}
    option.save(update_fields=["details_i18n"])
    assert image.file.url not in richtext.render_option_details(option)


def test_a_plain_link_to_an_image_id_is_never_resolved(
    open_window_poll: Poll, admin_user: User
) -> None:
    """§3.1 bis names one syntax, ``![alt](image:<n>)`` — an ordinary link
    written as ``[text](image:<n>)`` is not a request to embed an image and
    must stay exactly what it looks like, an unresolved link."""
    option = open_window_poll.options.first()
    assert option is not None
    image = pollimages.add_poll_image(
        open_window_poll, SimpleUploadedFile("b.png", _PNG), alt_text="", actor=admin_user
    )

    option.details_i18n = {"fr": f"[voir](image:{image.short_id})"}
    option.save(update_fields=["details_i18n"])
    html = richtext.render_option_details(option)
    assert image.file.url not in html
    # The link survives as text; only its `href` is dropped, by the
    # sanitiser's ordinary http/https-only scheme rule (§3.1 bis step 3) —
    # not because anything here recognised `image:` as an embed request.
    assert "voir" in html
    assert 'href="image:' not in html


def test_image_reference_to_a_missing_id_degrades_quietly(open_window_poll: Poll) -> None:
    option = open_window_poll.options.first()
    assert option is not None
    option.details_i18n = {"fr": "![alt](image:999)"}
    option.save(update_fields=["details_i18n"])
    # No exception, no broken <img> pointed nowhere real.
    assert "<img" not in richtext.render_option_details(option)


# --- upload and removal (apps.elections.pollimages) -------------------------


def test_add_poll_image_validates_size_and_type(open_window_poll: Poll, admin_user: User) -> None:
    with pytest.raises(pollimages.InvalidPollImage):
        pollimages.add_poll_image(
            open_window_poll,
            SimpleUploadedFile("x.png", b"not an image"),
            alt_text="",
            actor=admin_user,
        )
    with pytest.raises(pollimages.InvalidPollImage):
        pollimages.add_poll_image(
            open_window_poll,
            SimpleUploadedFile("x.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * pollimages.MAX_IMAGE_SIZE),
            alt_text="",
            actor=admin_user,
        )


def test_add_poll_image_deduplicates_identical_bytes_and_assigns_short_ids(
    open_window_poll: Poll, admin_user: User
) -> None:
    first = pollimages.add_poll_image(
        open_window_poll, SimpleUploadedFile("a.png", _PNG), alt_text="une image", actor=admin_user
    )
    assert first.short_id == 1
    again = pollimages.add_poll_image(
        open_window_poll, SimpleUploadedFile("a-bis.png", _PNG), alt_text="", actor=admin_user
    )
    assert again.pk == first.pk
    assert PollImage.objects.filter(poll=open_window_poll).count() == 1

    other = pollimages.add_poll_image(
        open_window_poll, SimpleUploadedFile("b.png", _OTHER_PNG), alt_text="", actor=admin_user
    )
    assert other.pk != first.pk
    assert other.short_id == 2
    assert PollImage.objects.filter(poll=open_window_poll).count() == 2

    assert AuditEvent.objects.filter(action=Action.POLL_IMAGE_ADDED).count() == 2


def test_add_and_remove_poll_image_refused_outside_draft(
    open_window_poll: Poll, admin_user: User
) -> None:
    image = pollimages.add_poll_image(
        open_window_poll, SimpleUploadedFile("a.png", _PNG), alt_text="", actor=admin_user
    )

    force_open(open_window_poll)

    with pytest.raises(config.ConfigurationLocked):
        pollimages.add_poll_image(
            open_window_poll, SimpleUploadedFile("b.png", _OTHER_PNG), alt_text="", actor=admin_user
        )
    with pytest.raises(config.ConfigurationLocked):
        pollimages.remove_poll_image(image, actor=admin_user)


def test_remove_poll_image_deletes_the_row_and_the_file(
    open_window_poll: Poll, admin_user: User, django_capture_on_commit_callbacks: CaptureOnCommit
) -> None:
    image = pollimages.add_poll_image(
        open_window_poll, SimpleUploadedFile("a.png", _PNG), alt_text="", actor=admin_user
    )
    stored = image.file
    file_name = stored.name
    assert file_name is not None
    assert stored.storage.exists(file_name)

    with django_capture_on_commit_callbacks(execute=True):
        pollimages.remove_poll_image(image, actor=admin_user)

    assert not PollImage.objects.filter(pk=image.pk).exists()
    assert not stored.storage.exists(file_name)
    assert AuditEvent.objects.filter(action=Action.POLL_IMAGE_REMOVED).exists()


def test_a_rolled_back_removal_keeps_the_file(open_window_poll: Poll, admin_user: User) -> None:
    """Review note L1: the file goes only once the row's deletion commits, so
    a rollback cannot leave a restored row naming a file that is gone."""
    image = pollimages.add_poll_image(
        open_window_poll, SimpleUploadedFile("a.png", _PNG), alt_text="", actor=admin_user
    )
    image_pk = image.pk
    file_name = image.file.name
    assert file_name is not None

    class Abort(Exception):
        pass

    with pytest.raises(Abort), transaction.atomic():
        pollimages.remove_poll_image(image, actor=admin_user)
        raise Abort

    assert PollImage.objects.filter(pk=image_pk).exists()
    assert image.file.storage.exists(file_name)


# --- screen 2's write path (apps.elections.config) --------------------------


def test_option_draft_details_round_trip_through_save_configuration(
    open_window_poll: Poll, admin_user: User
) -> None:
    option = open_window_poll.options.first()
    assert option is not None
    draft = config.ConfigDraft(
        scalars={},
        languages=open_window_poll.languages,
        title_i18n=open_window_poll.title_i18n,
        description_i18n=open_window_poll.description_i18n,
        options=[
            config.OptionDraft(
                option_id=row.option_id,
                labels=row.label_i18n,
                details={"fr": "Une description étendue."} if row.pk == option.pk else {},
                pk=str(row.pk),
            )
            for row in open_window_poll.options.all()
        ],
    )
    config.save_configuration(open_window_poll, draft, actor=admin_user)
    option.refresh_from_db()
    assert option.details_i18n == {"fr": "Une description étendue."}


# --- the back-office screens (§6.5.2) ----------------------------------------


def _grant(poll: Poll, user: User, role: Role) -> None:
    PollRole.objects.create(poll=poll, user=user, role=role)


def test_poll_image_upload_and_delete_via_the_screen(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    _grant(open_window_poll, admin_user, Role.POLL_ADMIN)
    client.force_login(admin_user)

    response = client.post(
        f"/fr/mairie/scrutin/{open_window_poll.pk}/configuration/images/",
        {"image": SimpleUploadedFile("a.png", _PNG), "alt_text": "une image"},
    )
    assert response.status_code == 302
    image = PollImage.objects.get(poll=open_window_poll)
    assert image.alt_text == "une image"

    body = client.get(f"/fr/mairie/scrutin/{open_window_poll.pk}/configuration/").content.decode()
    assert f"image:{image.short_id}" in body

    response = client.post(
        f"/fr/mairie/scrutin/{open_window_poll.pk}/configuration/images/{image.pk}/supprimer/"
    )
    assert response.status_code == 302
    assert not PollImage.objects.filter(pk=image.pk).exists()


def test_poll_image_upload_is_refused_to_an_entry_operator(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    """Only the poll admin edits configuration (§3.7) — the same role
    ``poll_config`` itself is gated on."""
    _grant(open_window_poll, admin_user, Role.ENTRY_OPERATOR)
    client.force_login(admin_user)

    response = client.post(
        f"/fr/mairie/scrutin/{open_window_poll.pk}/configuration/images/",
        {"image": SimpleUploadedFile("a.png", _PNG)},
    )
    assert response.status_code == 403
    assert not PollImage.objects.filter(poll=open_window_poll).exists()


def test_the_public_page_renders_the_description_and_extended_description(
    client: Client, open_window_poll: Poll
) -> None:
    option = open_window_poll.options.first()
    assert option is not None
    # Set while still draft — both descriptions are configuration too
    # (§3.1, §3.1 bis), so they have to be written before open_poll freezes
    # them.
    open_window_poll.description_i18n = {"fr": "**Description** du scrutin."}
    open_window_poll.save(update_fields=["description_i18n"])
    option.details_i18n = {"fr": "**Détails** de A."}
    option.save(update_fields=["details_i18n"])
    force_open(open_window_poll)

    body = client.get(f"/fr/scrutin/{open_window_poll.pk}/").content.decode()
    assert "<strong>Description</strong>" in body
    assert "<strong>Détails</strong>" in body
