# SPDX-License-Identifier: 0BSD
"""An option's extended description (R-3.12, §3.1 bis): rendering, image
upload/removal, and the screen-2 write path and views built on both.
"""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.audit.models import Action, AuditEvent
from apps.core.models import PollRole, Role, User
from apps.elections import config, optioncontent, optionimages
from apps.elections.models import OptionImage, Poll
from apps.elections.transitions import open_poll

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
_OTHER_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 33


@pytest.fixture
def admin_user(db: None) -> User:
    return User.objects.create_user(username="p.martin", password="x", full_name="P. Martin")


# --- rendering (apps.elections.optioncontent) ------------------------------


def test_details_falls_back_and_is_never_a_blocker(open_window_poll: Poll) -> None:
    option = open_window_poll.options.first()
    assert option is not None
    # No details in any language: an empty string, not an error, and not a
    # gap `missing_translations` reports (§3.8, R-3.12).
    assert optioncontent.render_option_details(option) == ""
    assert f"option:{option.option_id}" not in open_window_poll.missing_translations()


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

    html = optioncontent.render_option_details(option)
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

    html = optioncontent.render_option_details(option)
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

    html = optioncontent.render_option_details(option)
    assert "<iframe" not in html
    assert "DROP TABLE" not in html


def test_image_reference_resolves_only_to_its_own_option(open_window_poll: Poll) -> None:
    option_a, option_b = list(open_window_poll.options.all())[:2]
    image = OptionImage.objects.create(
        option=option_a, content_type="image/png", content_hash="a" * 64
    )
    image.file.save("a.png", SimpleUploadedFile("a.png", _PNG), save=True)

    option_a.details_i18n = {"fr": f"![alt](image:{image.pk})"}
    option_a.save(update_fields=["details_i18n"])
    html_a = optioncontent.render_option_details(option_a)
    assert image.file.url in html_a

    # Same reference, but from a different option: dropped, not followed.
    option_b.details_i18n = {"fr": f"![alt](image:{image.pk})"}
    option_b.save(update_fields=["details_i18n"])
    html_b = optioncontent.render_option_details(option_b)
    assert image.file.url not in html_b

    image.file.delete(save=False)


def test_image_reference_to_a_missing_id_degrades_quietly(open_window_poll: Poll) -> None:
    option = open_window_poll.options.first()
    assert option is not None
    option.details_i18n = {"fr": "![alt](image:00000000-0000-0000-0000-000000000000)"}
    option.save(update_fields=["details_i18n"])
    # No exception, no broken <img> pointed nowhere real.
    assert "<img" not in optioncontent.render_option_details(option)


# --- upload and removal (apps.elections.optionimages) ----------------------


def test_add_option_image_validates_size_and_type(open_window_poll: Poll, admin_user: User) -> None:
    option = open_window_poll.options.first()
    assert option is not None
    with pytest.raises(optionimages.InvalidOptionImage):
        optionimages.add_option_image(
            option,
            SimpleUploadedFile("x.png", b"not an image"),
            alt_text="",
            actor=admin_user,
        )
    with pytest.raises(optionimages.InvalidOptionImage):
        optionimages.add_option_image(
            option,
            SimpleUploadedFile(
                "x.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * optionimages.MAX_IMAGE_SIZE
            ),
            alt_text="",
            actor=admin_user,
        )


def test_add_option_image_deduplicates_identical_bytes(
    open_window_poll: Poll, admin_user: User
) -> None:
    option = open_window_poll.options.first()
    assert option is not None
    first = optionimages.add_option_image(
        option, SimpleUploadedFile("a.png", _PNG), alt_text="une image", actor=admin_user
    )
    again = optionimages.add_option_image(
        option, SimpleUploadedFile("a-bis.png", _PNG), alt_text="", actor=admin_user
    )
    assert again.pk == first.pk
    assert OptionImage.objects.filter(option=option).count() == 1

    other = optionimages.add_option_image(
        option, SimpleUploadedFile("b.png", _OTHER_PNG), alt_text="", actor=admin_user
    )
    assert other.pk != first.pk
    assert OptionImage.objects.filter(option=option).count() == 2

    assert AuditEvent.objects.filter(action=Action.OPTION_IMAGE_ADDED).count() == 2
    for image in OptionImage.objects.filter(option=option):
        image.file.delete(save=False)


def test_add_and_remove_option_image_refused_outside_draft(
    open_window_poll: Poll, admin_user: User
) -> None:
    option = open_window_poll.options.first()
    assert option is not None
    image = optionimages.add_option_image(
        option, SimpleUploadedFile("a.png", _PNG), alt_text="", actor=admin_user
    )

    open_poll(open_window_poll)
    option.refresh_from_db()

    with pytest.raises(config.ConfigurationLocked):
        optionimages.add_option_image(
            option, SimpleUploadedFile("b.png", _OTHER_PNG), alt_text="", actor=admin_user
        )
    with pytest.raises(config.ConfigurationLocked):
        optionimages.remove_option_image(image, actor=admin_user)

    image.file.delete(save=False)


def test_remove_option_image_deletes_the_row_and_the_file(
    open_window_poll: Poll, admin_user: User
) -> None:
    option = open_window_poll.options.first()
    assert option is not None
    image = optionimages.add_option_image(
        option, SimpleUploadedFile("a.png", _PNG), alt_text="", actor=admin_user
    )
    stored = image.file
    file_name = stored.name
    assert file_name is not None
    assert stored.storage.exists(file_name)

    optionimages.remove_option_image(image, actor=admin_user)

    assert not OptionImage.objects.filter(pk=image.pk).exists()
    assert not stored.storage.exists(file_name)
    assert AuditEvent.objects.filter(action=Action.OPTION_IMAGE_REMOVED).exists()


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


# --- the back-office screens (§6.5.2) --------------------------------------


def _grant(poll: Poll, user: User, role: Role) -> None:
    PollRole.objects.create(poll=poll, user=user, role=role)


def test_option_image_upload_and_delete_via_the_screen(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    _grant(open_window_poll, admin_user, Role.POLL_ADMIN)
    client.force_login(admin_user)
    option = open_window_poll.options.first()
    assert option is not None

    response = client.post(
        f"/fr/mairie/scrutin/{open_window_poll.pk}/configuration/propositions/{option.pk}/images/",
        {"image": SimpleUploadedFile("a.png", _PNG), "alt_text": "une image"},
    )
    assert response.status_code == 302
    image = OptionImage.objects.get(option=option)
    assert image.alt_text == "une image"

    body = client.get(f"/fr/mairie/scrutin/{open_window_poll.pk}/configuration/").content.decode()
    assert f"image:{image.pk}" in body

    response = client.post(
        f"/fr/mairie/scrutin/{open_window_poll.pk}/configuration/images/{image.pk}/supprimer/"
    )
    assert response.status_code == 302
    assert not OptionImage.objects.filter(pk=image.pk).exists()


def test_option_image_upload_is_refused_to_an_entry_operator(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    """Only the poll admin edits configuration (§3.7) — the same role
    ``poll_config`` itself is gated on."""
    _grant(open_window_poll, admin_user, Role.ENTRY_OPERATOR)
    client.force_login(admin_user)
    option = open_window_poll.options.first()
    assert option is not None

    response = client.post(
        f"/fr/mairie/scrutin/{open_window_poll.pk}/configuration/propositions/{option.pk}/images/",
        {"image": SimpleUploadedFile("a.png", _PNG)},
    )
    assert response.status_code == 403
    assert not OptionImage.objects.filter(option=option).exists()


def test_the_public_page_renders_the_extended_description(
    client: Client, open_window_poll: Poll
) -> None:
    option = open_window_poll.options.first()
    assert option is not None
    # Set while still draft — an extended description is configuration too
    # (§3.1 bis), so it has to be written before open_poll freezes it.
    option.details_i18n = {"fr": "**Détails** de A."}
    option.save(update_fields=["details_i18n"])
    open_poll(open_window_poll)

    body = client.get(f"/fr/scrutin/{open_window_poll.pk}/").content.decode()
    assert "<strong>Détails</strong>" in body
