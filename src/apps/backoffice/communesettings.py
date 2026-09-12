# SPDX-License-Identifier: 0BSD
"""Screen 14 — paramètres de la commune (§6.5.14).

Commune-level, like screens 10, 12 and 13: it goes through
``require_commune_admin``, not ``require_poll_role`` — one commune record
serves every poll, the same reason mail settings (§6.5.12) live outside any
poll's own menu.

The first-run wizard (§6.5.11, ``firstrun.install``) is the only other writer,
and only ever at creation: this is the screen an adopting commune reaches for
when its name, its data-protection referent, or the site's own address
changes afterwards. ``save`` logs which fields moved — never their values,
the same restraint §10 applies to poll configuration
(``elections.config.save_configuration``) and to the mail relay
(``mailsettings.save``).

The logo and favicon are optional and sit outside that form (``set_logo``,
``set_favicon`` and their ``remove_*`` mirrors): a blank file input does not
mean "keep the current one" the way a blank password does on screen 12, so
there is no value to diff against and an upload always replaces, exactly like
a proposition's image (R-3.12, ``apps.elections.optionimages``), whose
content-sniffing (``apps.core.images``) this reuses.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.audit.models import Action
from apps.core import images
from apps.core.models import Commune, User

#: The fields a save can change, and the only names ``save``'s audit event
#: ever names (§10).
_FIELDS = ("name", "data_protection_referent", "data_protection_contact", "public_base_url")


@dataclass(frozen=True)
class CommuneSettingsDraft:
    """A validated screen-14 submission, ready to apply."""

    name: str
    data_protection_referent: str
    data_protection_contact: str
    public_base_url: str = ""


def current() -> Commune | None:
    return Commune.current()


@transaction.atomic
def save(draft: CommuneSettingsDraft, *, actor: User) -> Commune:
    """Apply a screen-14 edit and log which fields changed (§10).

    The row always exists by the time this screen is reachable — the
    first-run wizard creates it in the same transaction as the first account,
    and ``require_commune_admin`` needs an account to grant the flag to — so,
    unlike ``mailsettings.save``, there is no "create if absent" branch here.
    """
    config = Commune.objects.select_for_update().get(pk=1)
    changed = {name for name in _FIELDS if getattr(config, name) != getattr(draft, name)}
    for name in _FIELDS:
        setattr(config, name, getattr(draft, name))
    config.save()
    if changed:
        audit.record(
            action=Action.COMMUNE_SETTINGS_CHANGED,
            poll=None,
            actor=actor,
            object_ref=audit.ref(config),
            after={"changed": sorted(changed)},
        )
    return config


# --- Logo and favicon (§6.5.14, both optional) -----------------------------

#: 2 MiB: shown small, in a page header, never at full size.
MAX_LOGO_SIZE = 2 * 1024 * 1024
#: 256 KiB: a favicon is a few dozen pixels square; anything past this is the
#: wrong file, not a legitimate one that happens to be large.
MAX_FAVICON_SIZE = 256 * 1024


class InvalidBrandingImage(Exception):
    """The upload is not usable: too large, or not a recognised image type."""


def _set_branding(
    commune: Commune,
    upload: UploadedFile[bytes],
    *,
    field: str,
    sniff: Callable[[bytes], str | None],
    max_size: int,
    size_error: str,
    format_error: str,
    actor: User,
) -> Commune:
    """Shared by ``set_logo`` and ``set_favicon``: sniff, size-check, store
    content-addressed (``commune_logo_path``/``commune_favicon_path`` read the
    ``*_content_type``/``*_content_hash`` fields set here before the field
    file itself is saved), and delete whatever the field held before."""
    if upload.size is not None and upload.size > max_size:
        raise InvalidBrandingImage(size_error)
    data = upload.read()
    if len(data) > max_size:
        raise InvalidBrandingImage(size_error)
    content_type = sniff(data)
    if content_type is None:
        raise InvalidBrandingImage(format_error)
    digest = sha256(data).hexdigest()

    old_name = getattr(commune, field).name
    setattr(commune, f"{field}_content_type", content_type)
    setattr(commune, f"{field}_content_hash", digest)
    getattr(commune, field).save(digest, ContentFile(data), save=False)
    commune.save()
    if old_name and old_name != getattr(commune, field).name:
        getattr(commune, field).storage.delete(old_name)

    audit.record(
        action=Action.COMMUNE_BRANDING_CHANGED,
        poll=None,
        actor=actor,
        object_ref=audit.ref(commune),
        after={"field": field},
    )
    return commune


def _remove_branding(commune: Commune, *, field: str, actor: User) -> Commune:
    """The mirror of ``_set_branding``: no-op where the field is already
    empty, so a stray remove POST logs nothing that did not happen."""
    old_name = getattr(commune, field).name
    if not old_name:
        return commune
    getattr(commune, field).storage.delete(old_name)
    setattr(commune, field, "")
    setattr(commune, f"{field}_content_type", "")
    setattr(commune, f"{field}_content_hash", "")
    commune.save()
    audit.record(
        action=Action.COMMUNE_BRANDING_REMOVED,
        poll=None,
        actor=actor,
        object_ref=audit.ref(commune),
        after={"field": field},
    )
    return commune


@transaction.atomic
def set_logo(commune: Commune, upload: UploadedFile[bytes], *, actor: User) -> Commune:
    """Screen 14's logo upload: shown in the page header in place of the
    plain commune name (``base.html``) where one is set."""
    return _set_branding(
        commune,
        upload,
        field="logo",
        sniff=images.sniff_raster,
        max_size=MAX_LOGO_SIZE,
        size_error=_("Image trop volumineuse (2 Mo maximum)."),
        format_error=_("Format d'image non reconnu (PNG, JPEG, GIF ou WebP attendus)."),
        actor=actor,
    )


@transaction.atomic
def remove_logo(commune: Commune, *, actor: User) -> Commune:
    return _remove_branding(commune, field="logo", actor=actor)


@transaction.atomic
def set_favicon(commune: Commune, upload: UploadedFile[bytes], *, actor: User) -> Commune:
    """Screen 14's favicon upload: the browser-tab icon (``base.html``),
    accepting ``.ico`` in addition to every raster format the logo does."""
    return _set_branding(
        commune,
        upload,
        field="favicon",
        sniff=images.sniff_favicon,
        max_size=MAX_FAVICON_SIZE,
        size_error=_("Image trop volumineuse (256 Ko maximum)."),
        format_error=_("Format d'image non reconnu (ICO, PNG, JPEG, GIF ou WebP attendus)."),
        actor=actor,
    )


@transaction.atomic
def remove_favicon(commune: Commune, *, actor: User) -> Commune:
    return _remove_branding(commune, field="favicon", actor=actor)
