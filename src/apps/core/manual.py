# SPDX-License-Identifier: 0BSD
"""Renders ``docs/manuel/*.md`` for display on the public site and in the
mairie area.

The manual is the single source of the prose: a page reads its Markdown
straight off disk and renders it at request time, never at a build or deploy
step, so a served page can never drift from what a maintainer last edited in
``docs/manuel/``. This mirrors, for the manual, the reasoning
``apps.elections.richtext`` gives for rendering a poll's own description at
display time rather than at save time — except the allow-list here is wider
(headings, tables, code blocks) since this content is authored by whoever
maintains the manual, not typed by an operator into a form.

``docs/manuel/README.md`` states that French is the manual's only reference
language; an English translation nonetheless exists, as a sibling file
suffixed ``-en`` next to each French one — the same convention
`requirements-en.md` uses next to `cahier-des-charges.md` at the repository
root. Which language is read follows the request's own ``LANGUAGE_CODE``
(``django.middleware.locale.LocaleMiddleware``), not a separate switch: the
site's existing language selector already covers this page like any other.

``faq.md`` answers three different audiences in one file, under three
top-level (``##``) headings lettered A/B/C. Splitting it by audience reads
one lettered section out with `for_section`, matched on the letter — which
is identical between the French and English files — rather than on the
heading text, which is translated.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import markdown as _markdown
import nh3
from django.conf import settings
from django.utils.safestring import SafeString, mark_safe
from markdown.extensions.toc import slugify_unicode

_MANUAL_DIR: Path = settings.BASE_DIR / "docs" / "manuel"
_IMG_DIR: Path = _MANUAL_DIR / "captures" / "img"
_IMAGE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.png$")

#: Deliberately wider than ``apps.elections.richtext``'s allow-list: this
#: content comes from a file under version control, not from a form an
#: operator fills in, so headings, tables and code blocks are safe to allow.
#: Still no ``<script>``, no ``on*`` attribute, no scheme but ``http``/
#: ``https`` on a link or an image — ``nh3`` enforces that regardless of what
#: reaches it.
_ALLOWED_TAGS = {
    "p",
    "br",
    "strong",
    "em",
    "a",
    "ul",
    "ol",
    "li",
    "h1",
    "h2",
    "h3",
    "h4",
    "blockquote",
    "img",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "code",
    "pre",
    "hr",
}
_ALLOWED_ATTRIBUTES = {
    "a": {"href", "title"},
    "img": {"src", "alt", "title"},
    "h1": {"id"},
    "h2": {"id"},
    "h3": {"id"},
    "h4": {"id"},
}

_H1 = re.compile(r"(?m)^#[ \t]+(.+?)[ \t]*$")
_H2 = re.compile(r"(?m)^##[ \t]+(.+?)[ \t]*$")
_ANY_H2 = re.compile(r"(?m)^##[ \t]")
_DOC_LINK = re.compile(r"\]\((?P<name>[a-z][a-z-]*)\.md(?P<fragment>#[^)]*)?\)")


@dataclass(frozen=True)
class ManualDoc:
    """One document, or one lettered section of one, served from the manual.

    ``stem`` is the source file's base name, with neither the ``-en`` suffix
    nor the ``.md`` extension — ``read()`` adds both according to the
    requested language. ``section`` is the letter of a top-level heading to
    extract (``faq.md``'s audience split); ``None`` serves the whole file.
    """

    stem: str
    section: str | None = None


@dataclass(frozen=True)
class ManualPage:
    """One rendered manual page: ``title`` as ``read`` derives it and the
    nh3-sanitised body as ``html``, safe to insert into a template unescaped."""

    title: str
    html: SafeString


def _source_path(stem: str, language: str) -> Path:
    suffix = "-en" if language == "en" else ""
    return _MANUAL_DIR / f"{stem}{suffix}.md"


def _extract_section(text: str, letter: str) -> str:
    """The ``## <letter>. …`` section of ``text``, from its own heading up to
    the next top-level heading or end of file — the letter is stable across
    languages, the heading text that follows it is not (module docstring).
    """
    heading = re.compile(rf"(?m)^##[ \t]+{re.escape(letter)}\.[ \t]")
    start_match = heading.search(text)
    if start_match is None:
        raise LookupError(f"no {letter!r} section in manual text")
    following = _ANY_H2.search(text, start_match.end())
    end = following.start() if following else len(text)
    section = text[start_match.start() : end]
    # Audience sections are separated by a `---` rule in the combined file
    # (faq.md); trailing, it belongs to the split, not to either page.
    section = re.sub(r"\n{2,}-{3,}[ \t]*\n*\Z", "\n", section)
    return section.strip("\n") + "\n"


def read(doc: ManualDoc, language: str) -> tuple[str, str]:
    """The ``(title, body)`` of ``doc`` in ``language`` — ``body`` is raw
    Markdown, not yet rendered, with its own leading ``#`` title line
    stripped: callers show the title through their own template heading, and
    a second, redundant ``<h1>`` in the body would misorder the page for a
    screen reader (RGAA, cited throughout the manual itself).

    A lettered section (``doc.section``) has its own ``##`` heading stripped
    too, the same way and for the same reason: a page ever shows one such
    section on its own, never alongside a sibling it needs distinguishing
    from, so repeating "C. Électeur" as a lone ``<h2>`` right under an
    ``<h1>`` that already ends in "— Électeur" said the same thing twice.
    """
    text = _source_path(doc.stem, language).read_text(encoding="utf-8")
    document_title_match = _H1.search(text)
    if document_title_match is None:
        raise LookupError(f"no top-level heading in {doc.stem!r}")
    document_title = document_title_match.group(1)
    if doc.section is None:
        body = _H1.sub("", text, count=1).lstrip("\n")
        return document_title, body
    section = _extract_section(text, doc.section)
    section_heading_match = _H2.match(section)
    assert section_heading_match is not None  # _extract_section starts on this heading
    section_title = re.sub(
        rf"^{re.escape(doc.section)}\.[ \t]*", "", section_heading_match.group(1)
    )
    body = _H2.sub("", section, count=1).lstrip("\n")
    return f"{document_title} — {section_title}", body


def image_path(name: str) -> Path:
    """The on-disk path of one manual screenshot under
    ``docs/manuel/captures/img/``, or raise ``LookupError``.

    ``name`` comes straight off a URL path segment, so anything but a bare
    ``<name>.png`` — no ``..``, no path separator, no other extension — is
    refused before it ever reaches the filesystem.
    """
    if not _IMAGE_NAME.match(name):
        raise LookupError(name)
    path = _IMG_DIR / name
    if not path.is_file():
        raise LookupError(name)
    return path


def rewrite_doc_links(text: str, urls: Mapping[str, str]) -> str:
    """Replace a cross-reference to another manual document — written in the
    source as a bare ``guide-electeur.md`` or ``verifier.md`` target, kept
    that way so the manual's own prose never hardcodes a route — with the
    URL that actually serves it, fragment (in-page anchor) preserved. A name
    absent from ``urls`` is left untouched rather than guessed at.
    """

    def _sub(match: re.Match[str]) -> str:
        url = urls.get(match.group("name"))
        if url is None:
            return match.group(0)
        return f"]({url}{match.group('fragment') or ''})"

    return _DOC_LINK.sub(_sub, text)


def rewrite_image_paths(text: str, base_url: str) -> str:
    """Point a screenshot reference (``captures/img/…``, as the manual's
    source has it) at ``base_url``, which must end in ``/`` — the route that
    actually serves the manual's images for the current audience.
    """
    return text.replace("(captures/img/", f"({base_url}")


def render(
    doc: ManualDoc,
    language: str,
    *,
    doc_links: Mapping[str, str] | None = None,
    image_base_url: str | None = None,
) -> ManualPage:
    """The rendered page for ``doc`` in ``language``, links and image
    references resolved to real URLs for the calling site.
    """
    title, body = read(doc, language)
    if doc_links:
        body = rewrite_doc_links(body, doc_links)
    if image_base_url:
        body = rewrite_image_paths(body, image_base_url)
    html = _markdown.markdown(
        body,
        extensions=["tables", "fenced_code", "toc"],
        extension_configs={"toc": {"slugify": slugify_unicode}},
    )
    clean = nh3.clean(
        html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRIBUTES,
        link_rel="noopener noreferrer nofollow ugc",
        url_schemes={"http", "https"},
    )
    return ManualPage(title=title, html=mark_safe(clean))  # noqa: S308 — nh3's own sanitised output
