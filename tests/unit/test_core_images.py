# SPDX-License-Identifier: 0BSD
"""Content-sniffed image validation (``apps.core.images``), shared by the
option-image attachment of R-3.12 and the commune branding of §6.5.14 — never
trusted by a declared content-type or a filename extension, only by the
bytes' own fixed-position signature (§14)."""

from __future__ import annotations

from apps.core import images

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG = b"\xff\xd8\xff" + b"\x00" * 16
GIF87 = b"GIF87a" + b"\x00" * 16
GIF89 = b"GIF89a" + b"\x00" * 16
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 8
ICO = b"\x00\x00\x01\x00" + b"\x00" * 16


def test_sniff_raster_recognises_every_raster_format() -> None:
    assert images.sniff_raster(PNG) == "image/png"
    assert images.sniff_raster(JPEG) == "image/jpeg"
    assert images.sniff_raster(GIF87) == "image/gif"
    assert images.sniff_raster(GIF89) == "image/gif"
    assert images.sniff_raster(WEBP) == "image/webp"


def test_sniff_raster_rejects_ico_and_garbage() -> None:
    """ICO only means something as a favicon (§6.5.14): a proposition's image
    or a logo has no reason to be one."""
    assert images.sniff_raster(ICO) is None
    assert images.sniff_raster(b"not an image") is None


def test_sniff_favicon_accepts_ico_and_every_raster_format() -> None:
    assert images.sniff_favicon(ICO) == "image/x-icon"
    assert images.sniff_favicon(PNG) == "image/png"
    assert images.sniff_favicon(b"not an image") is None


def test_svg_is_recognised_by_neither_sniffer() -> None:
    """Deliberate (§14): an uploaded SVG can carry a ``<script>``, and this
    application has no sanitiser to strip one before serving it back."""
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>1</script></svg>'
    assert images.sniff_raster(svg) is None
    assert images.sniff_favicon(svg) is None


def test_a_declared_content_type_is_not_trusted_over_the_bytes() -> None:
    """The filename/content-type an upload declares is the caller's word for
    it, not the file's (§14, the same reasoning §6.1 gives for a CSV's
    claimed encoding) — only the signature decides."""
    disguised_as_png = b"not-a-png-despite-the-name"
    assert images.sniff_raster(disguised_as_png) is None
