# SPDX-License-Identifier: 0BSD
"""Upload and removal of an option's images (R-3.12, §3.1 bis).

Both are screen 2 actions and so governed by the same rule as every other
configuration edit: only while the poll is ``draft`` (R-3.3). Migration 0008's
``inv6_optionimage_*_frozen`` triggers are what actually hold that outside the
application; the check here is the one that produces a message an operator
can act on, before anything is read into memory.
"""

from __future__ import annotations

import hashlib

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.audit.models import Action
from apps.core import images
from apps.core.models import User

from .config import ConfigurationLocked
from .models import OptionImage, PollOption, PollState

#: 5 MiB: generous for a photograph or a screenshot, small enough that the
#: mairie's nightly ``VACUUM INTO`` (§14) does not notice a poll acquiring a
#: handful of these.
MAX_IMAGE_SIZE = 5 * 1024 * 1024


class InvalidOptionImage(Exception):
    """The upload is not usable: too large, or not a recognised image type."""


@transaction.atomic
def add_option_image(
    option: PollOption, upload: UploadedFile[bytes], *, alt_text: str, actor: User
) -> OptionImage:
    """Validate, hash and store one image.

    Re-uploading bytes already attached to this option returns the existing
    row rather than raising: the ``uniq_option_image_content`` constraint
    would refuse a duplicate insert anyway, but the operator only meant "yes,
    this one again", not an error.
    """
    poll = option.poll
    if poll.state != PollState.DRAFT:
        raise ConfigurationLocked(
            _("La configuration est figée : le scrutin n'est plus en brouillon.")
        )
    if upload.size is not None and upload.size > MAX_IMAGE_SIZE:
        raise InvalidOptionImage(_("Image trop volumineuse (5 Mo maximum)."))
    data = upload.read()
    if len(data) > MAX_IMAGE_SIZE:
        raise InvalidOptionImage(_("Image trop volumineuse (5 Mo maximum)."))
    content_type = images.sniff_raster(data)
    if content_type is None:
        raise InvalidOptionImage(_("Format d'image non reconnu (PNG, JPEG, GIF ou WebP attendus)."))
    digest = hashlib.sha256(data).hexdigest()

    existing = OptionImage.objects.filter(option=option, content_hash=digest).first()
    if existing is not None:
        return existing

    image = OptionImage(option=option, content_type=content_type, content_hash=digest)
    image.file.save(digest, ContentFile(data), save=False)
    image.alt_text = alt_text
    image.save()
    audit.record(
        action=Action.OPTION_IMAGE_ADDED,
        poll=poll,
        actor=actor,
        object_ref=audit.ref(image),
        after={"option_id": option.option_id},
    )
    return image


@transaction.atomic
def remove_option_image(image: OptionImage, *, actor: User) -> None:
    """The mirror of ``add_option_image``, same ``draft``-only rule.

    The file is removed from storage too: the path is content-addressed per
    option (``uniq_option_image_content``), so no other row can be pointing
    at it.
    """
    poll = image.option.poll
    if poll.state != PollState.DRAFT:
        raise ConfigurationLocked(
            _("La configuration est figée : le scrutin n'est plus en brouillon.")
        )
    ref = audit.ref(image)
    option_id = image.option.option_id
    file_name = image.file.name
    image.delete()
    if file_name:
        image.file.storage.delete(file_name)
    audit.record(
        action=Action.OPTION_IMAGE_REMOVED,
        poll=poll,
        actor=actor,
        object_ref=ref,
        after={"option_id": option_id},
    )
