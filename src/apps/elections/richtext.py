# SPDX-License-Identifier: 0BSD
"""Renders a poll's own description and each option's extended description
(R-3.12, §3.1 bis).

``Poll.description_i18n`` and ``PollOption.details_i18n`` both store raw
Markdown. It is rendered to sanitised HTML here, at *display* time, never at
save time: a fix to the allowed-tag set or the YouTube pattern below then
reaches every poll's content immediately, past and present, with no backfill
migration.

Three pieces of untrusted input, handled in a fixed order so each is closed
off before the next could reopen it:

1. An ``image:<short_id>`` reference is resolved to a real media URL before
   the text ever reaches the Markdown parser, and only to an image that
   belongs to *this* poll's shared library — a reference to another poll's
   image id, or to one that does not exist, is silently dropped rather than
   followed. ``![](image:<short_id>)``, with nothing between the brackets,
   takes the library's own ``PollImage.alt_text`` rather than emitting an
   image with no alt text: that field is the default, reused everywhere the
   image is embedded; writing something inside the brackets overrides it for
   that one reference only. An optional ``:small``/``:medium``/``:large``
   suffix on the reference (``image:<short_id>:large``) picks a display size;
   omitted, the image renders at its natural size, unchanged from before this
   suffix existed (docs/specification-decision-log.md #23).
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
from html import escape as _escape_attr

import markdown as _markdown
import nh3
from django.utils.safestring import SafeString, mark_safe

from .models import Poll, PollImage, PollOption

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
#: Only the image syntax §3.1 bis names, ``![alt](image:<short_id>)``, plus
#: the optional ``:small``/``:medium``/``:large`` size suffix (decision log
#: #23) — not a bare ``(image:<short_id>)`` inside an ordinary link like
#: ``[text](image:<short_id>)``, which the unanchored form used to match too.
_IMAGE_REF = re.compile(r"!\[([^\]]*)\]\(image:(\d+)(?::(small|medium|large))?\)")

#: CSS classes the size suffix selects between (static/css/app.css). Not part
#: of the sanitiser's general allow-list — ``class`` is only ever emitted here,
#: from this fixed table, never from operator-supplied text.
_IMAGE_SIZE_CLASSES = {
    "small": "poll-image--small",
    "medium": "poll-image--medium",
    "large": "poll-image--large",
}

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
_ALLOWED_ATTRIBUTES = {"a": {"href", "title"}, "img": {"src", "alt", "title", "class"}}


def render_poll_description(poll: Poll, language: str | None = None) -> SafeString:
    """The sanitised HTML for a poll's own description (R-3.1, R-3.12)."""
    return _render(poll, poll.description(language))


def render_option_details(option: PollOption, language: str | None = None) -> SafeString:
    """The sanitised HTML for one option's extended description.

    An empty string where the option has none in any available language —
    never an error and never, per R-3.12, a reason to block anything: absent
    content here is a normal outcome, not a gap the dashboard names.
    """
    return _render(option.poll, option.details(language))


def _render(poll: Poll, raw: str) -> SafeString:
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
    text = _IMAGE_REF.sub(lambda m: _resolve_image(poll, m), raw)
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


def _resolve_image(poll: Poll, match: re.Match[str]) -> str:
    alt = match.group(1)
    short_id = int(match.group(2))
    size = match.group(3)
    image = PollImage.objects.filter(poll=poll, short_id=short_id).first()
    if image is None:
        return ""
    if not alt:
        alt = image.alt_text
    if size is None:
        return f"![{alt}]({image.file.url})"
    # A raw <img> rather than Markdown image syntax: the size suffix needs a
    # `class`, which Markdown's own `![]()` form has no way to carry. Safe to
    # emit unparsed — nh3.clean() sanitises the whole document afterwards
    # regardless of how a tag reached it (§3.1 bis point 3).
    css_class = _IMAGE_SIZE_CLASSES[size]
    return f'<img src="{image.file.url}" alt="{_escape_attr(alt, quote=True)}" class="{css_class}">'


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
