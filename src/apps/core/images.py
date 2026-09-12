# SPDX-License-Identifier: 0BSD
"""Content-sniffed image validation, shared by every upload that accepts one:
the option-image attachment of R-3.12 (``apps.elections.optionimages``) and
the commune branding — logo and favicon — of §6.5.14
(``apps.backoffice.communesettings``).

Recognised by a fixed-position signature, never by the upload's declared
content-type or filename extension — both are the caller's word for it, not
the file's (§14; the same reasoning §6.1 gives for not trusting a CSV's
claimed encoding).
"""

from __future__ import annotations

_RASTER_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)

#: Windows/browser icon format. Meaningful only as a favicon — a proposition's
#: image or a header logo never has a reason to be one — so it is not part of
#: ``sniff_raster``.
_ICO_SIGNATURE = b"\x00\x00\x01\x00"

#: The extension each recognised content type is stored under. Never SVG:
#: deliberately not a recognised type anywhere here, since an uploaded SVG can
#: carry a `<script>` and this application has no sanitiser to strip one
#: before serving it back (§14).
EXTENSIONS: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/x-icon": ".ico",
}


def sniff_raster(data: bytes) -> str | None:
    """PNG, JPEG, GIF or WebP — the formats a proposition's image (R-3.12) or
    a commune logo (§6.5.14) can be."""
    for signature, content_type in _RASTER_SIGNATURES:
        if data.startswith(signature):
            return content_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def sniff_favicon(data: bytes) -> str | None:
    """Everything ``sniff_raster`` accepts, plus ``.ico`` — the one format
    that makes sense only here."""
    if data.startswith(_ICO_SIGNATURE):
        return "image/x-icon"
    return sniff_raster(data)
