# SPDX-License-Identifier: 0BSD
"""Upload and removal of a poll's shared images (R-3.12, §3.1 bis).

Both are screen 2 actions and so governed by the same rule as every other
configuration edit: only while the poll is ``draft`` (R-3.3). Migration
0011's ``inv6_pollimage_*_frozen`` triggers are what actually hold that
outside the application; the check here is the one that produces a message
an operator can act on, before anything is read into memory.
"""

from __future__ import annotations

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.db.models import Max
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.audit.models import Action
from apps.core import images
from apps.core.models import User

from .config import ConfigurationLocked
from .models import Poll, PollImage, PollState

#: 5 MiB: generous for a photograph or a screenshot, small enough that the
#: mairie's nightly ``VACUUM INTO`` (§14) does not notice a poll acquiring a
#: handful of these.
MAX_IMAGE_SIZE = 5 * 1024 * 1024


class InvalidPollImage(Exception):
    """The upload is not usable: too large, or not a recognised image type."""


@transaction.atomic
def add_poll_image(
    poll: Poll, upload: UploadedFile[bytes], *, alt_text: str, actor: User
) -> PollImage:
    """Validate, hash and store one image.

    Re-uploading bytes already attached to this poll returns the existing
    row rather than raising: the ``uniq_poll_image_content`` constraint would
    refuse a duplicate insert anyway, but the operator only meant "yes, this
    one again", not an error. ``short_id`` is assigned here, sequential per
    poll, rather than left to the database: the next value and the
    hash-dedupe check both need to be decided under the same transaction.
    """
    if poll.state != PollState.DRAFT:
        raise ConfigurationLocked(
            _("La configuration est figée : le scrutin n'est plus en brouillon.")
        )
    try:
        data, content_type, digest = images.read_validated(
            upload, sniff=images.sniff_raster, max_size=MAX_IMAGE_SIZE
        )
    except images.UploadTooLarge:
        raise InvalidPollImage(_("Image trop volumineuse (5 Mo maximum).")) from None
    except images.UploadFormatUnrecognised:
        raise InvalidPollImage(
            _("Format d'image non reconnu (PNG, JPEG, GIF ou WebP attendus).")
        ) from None

    existing = PollImage.objects.filter(poll=poll, content_hash=digest).first()
    if existing is not None:
        return existing

    next_short_id = (
        PollImage.objects.filter(poll=poll).aggregate(Max("short_id"))["short_id__max"] or 0
    ) + 1
    image = PollImage(
        poll=poll, short_id=next_short_id, content_type=content_type, content_hash=digest
    )
    image.file.save(digest, ContentFile(data), save=False)
    image.alt_text = alt_text
    image.save()
    audit.record(
        action=Action.POLL_IMAGE_ADDED,
        poll=poll,
        actor=actor,
        object_ref=audit.ref(image),
        after={"short_id": next_short_id},
    )
    return image


@transaction.atomic
def remove_poll_image(image: PollImage, *, actor: User) -> None:
    """The mirror of ``add_poll_image`` above, same ``draft``-only rule.

    The file is removed from storage too: the path is content-addressed per
    poll (``uniq_poll_image_content``), so no other row can be pointing at it.
    """
    poll = image.poll
    if poll.state != PollState.DRAFT:
        raise ConfigurationLocked(
            _("La configuration est figée : le scrutin n'est plus en brouillon.")
        )
    ref = audit.ref(image)
    short_id = image.short_id
    file_name = image.file.name
    image.delete()
    if file_name:
        image.file.storage.delete(file_name)
    audit.record(
        action=Action.POLL_IMAGE_REMOVED,
        poll=poll,
        actor=actor,
        object_ref=ref,
        after={"short_id": short_id},
    )
