# SPDX-License-Identifier: 0BSD
"""Renders an option's extended description (R-3.12, §3.1 bis).

``PollOption.details_i18n`` stores raw Markdown. It is rendered to sanitised
HTML here, at *display* time, never at save time: a fix to the allowed-tag
set or the YouTube pattern below then reaches every poll's content
immediately, past and present, with no backfill migration.

Three pieces of untrusted input, handled in a fixed order so each is closed
off before the next could reopen it:

1. An ``image:<uuid>`` reference is resolved to a real media URL before the
   text ever reaches the Markdown parser, and only to an image that belongs
   to *this* option — a reference to another option's or another poll's
   image id is silently dropped rather than followed.
2. A YouTube embed is never markup the operator wrote. It is recognised in
   one of two forms — a fenced ``youtube`` block carrying a bare video id, or
   a ``youtube.com``/``youtu.be`` URL standing alone on its own line — by a
   fixed pair of regular expressions, pulled out of the raw text and replaced
   with an opaque placeholder before Markdown or the sanitiser ever see it,
   then swapped back in afterwards for an ``<iframe>`` *this module* builds
   from a validated eleven-character video id — never for anything the
   operator supplied. A link that is part of a sentence, or written as
   ``[text](url)``, stays a link: only a line that is nothing but the URL is
   taken as a request to embed. This is the one place in the pipeline
   allowed to emit an iframe.
3. Everything else goes through ``markdown`` and then ``nh3.clean`` with a
   fixed allow-list: no ``<iframe>``, no ``<script>``, no ``on*`` attribute,
   no scheme but ``http``/``https`` on a link or an image.
"""

from __future__ import annotations

import re
import uuid

import markdown as _markdown
import nh3
from django.utils.safestring import SafeString, mark_safe

from .models import OptionImage, PollOption

#: YouTube video ids are exactly eleven characters of this alphabet. Anything
#: else — in the fenced block or captured from a URL — is not a video id, and
#: dropped rather than guessed at.
_YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YOUTUBE_BLOCK = re.compile(r"```youtube[ \t]*\n[ \t]*([^\n`]+?)[ \t]*\n```")
#: A youtube.com/youtu.be URL alone on its line — not `[text](url)`, and not
#: a link mentioned mid-sentence, both of which stay ordinary links (point 2
#: of the module docstring). `v=` is matched wherever it falls in the query
#: string, since a pasted watch link often carries `list=`/`t=` ahead of it.
_YOUTUBE_URL_LINE = re.compile(
    r"^[ \t]*https?://(?:www\.|m\.)?"
    r"(?:youtube(?:-nocookie)?\.com/(?:watch\?(?:[^\s]*&)?v=|embed/)(?P<id1>[A-Za-z0-9_-]{11})(?:[&?]\S*)?"
    r"|youtu\.be/(?P<id2>[A-Za-z0-9_-]{11})(?:\?\S*)?)"
    r"[ \t]*$",
    re.MULTILINE,
)
#: Only the image syntax §3.1 bis names, ``![alt](image:<uuid>)`` — not a bare
#: ``(image:<uuid>)`` inside an ordinary link like ``[text](image:<uuid>)``,
#: which the unanchored form used to match too. Harmless in practice (the
#: resolved target is always this option's own self-hosted file), but wider
#: than the syntax the spec and T-79 describe.
_IMAGE_REF = re.compile(r"!\[([^\]]*)\]\(image:([0-9a-fA-F-]{36})\)")

_ALLOWED_TAGS = {
    "p",
    "br",
    "strong",
    "em",
    "a",
    "ul",
    "ol",
    "li",
    "h2",
    "h3",
    "h4",
    "blockquote",
    "img",
}
_ALLOWED_ATTRIBUTES = {"a": {"href", "title"}, "img": {"src", "alt", "title"}}


def render_option_details(option: PollOption, language: str | None = None) -> SafeString:
    """The sanitised HTML for one option's extended description.

    An empty string where the option has none in any available language —
    never an error and never, per R-3.12, a reason to block anything: absent
    content here is a normal outcome, not a gap the dashboard names.
    """
    raw = option.details(language)
    if not raw:
        return mark_safe("")

    embeds: dict[str, str] = {}

    def _embed_token(video_id: str) -> str:
        token = f"YOUTUBEEMBED{uuid.uuid4().hex}ENDEMBED"
        embeds[token] = video_id
        return token

    def _extract_embed(match: re.Match[str]) -> str:
        video_id = match.group(1).strip()
        if not _YOUTUBE_ID.match(video_id):
            return ""
        return _embed_token(video_id)

    def _extract_url_embed(match: re.Match[str]) -> str:
        video_id = match.group("id1") or match.group("id2")
        if video_id is None or not _YOUTUBE_ID.match(video_id):
            return match.group(0)
        return _embed_token(video_id)

    # Images resolved first, matching the fixed order §3.1 bis specifies: each
    # step closes off a category of untrusted input before the next is given
    # a chance to reopen it. Inert either way today — a resolved image URL
    # can never itself satisfy `_YOUTUBE_URL_LINE`'s "alone on its own line"
    # test — but a future change to either pattern should not have to
    # rediscover that the order was supposed to matter.
    text = _IMAGE_REF.sub(lambda m: _resolve_image(option, m), raw)
    text = _YOUTUBE_BLOCK.sub(_extract_embed, text)
    text = _YOUTUBE_URL_LINE.sub(_extract_url_embed, text)

    html = _markdown.markdown(text)
    clean = nh3.clean(
        html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRIBUTES,
        link_rel="noopener noreferrer nofollow ugc",
        url_schemes={"http", "https"},
    )

    for token, video_id in embeds.items():
        iframe = _youtube_iframe(video_id)
        clean = clean.replace(f"<p>{token}</p>", iframe).replace(token, iframe)

    return mark_safe(clean)  # noqa: S308 — `clean` is nh3's own output, sanitised just above


def _resolve_image(option: PollOption, match: re.Match[str]) -> str:
    alt = match.group(1)
    try:
        image_id = uuid.UUID(match.group(2))
    except ValueError:
        return ""
    image = OptionImage.objects.filter(pk=image_id, option=option).first()
    if image is None:
        return ""
    return f"![{alt}]({image.file.url})"


def _youtube_iframe(video_id: str) -> str:
    """The one and only iframe this pipeline ever emits, built from a
    validated eleven-character id — never from operator-supplied markup
    (§3.1 bis). ``youtube-nocookie.com`` and a fixed ``sandbox`` keep the
    embed to playing the video: no top-level navigation, no popups, no access
    to this page's own storage or DOM."""
    return (
        '<div class="youtube-embed">'
        f'<iframe src="https://www.youtube-nocookie.com/embed/{video_id}" '
        'loading="lazy" referrerpolicy="strict-origin-when-cross-origin" '
        'sandbox="allow-scripts allow-same-origin allow-presentation" '
        'allowfullscreen title="Vidéo YouTube"></iframe></div>'
    )
