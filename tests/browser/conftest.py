# SPDX-License-Identifier: 0BSD
"""A real browser against the live test server (review C-8).

Marked ``browser`` and left out of the default run, which stays fast and needs
no browser: ``uv run playwright install --only-shell chromium`` once, ``npm
ci`` for axe-core, then ``uv run pytest -m browser``. CI's "browser" job does
the same.

Each page also records two things the HTTP tests cannot see: a script error,
and a Content-Security-Policy violation. Django's dev server never sends the
policy (``core/headers.py`` skips it under ``DEBUG``); the live server here
runs the test settings, ``DEBUG`` off, so it is the policy production sends.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from django.db import connection
from playwright.sync_api import Browser, ConsoleMessage, Page, sync_playwright

AXE = Path(__file__).resolve().parents[2] / "node_modules" / "axe-core" / "axe.min.js"

#: WCAG 2.1 A and AA, the level RGAA 4 (R-14.1) is built on.
AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]

_RECORD_CSP = """
window.__cspViolations = [];
document.addEventListener("securitypolicyviolation", function (event) {
  window.__cspViolations.push(event.violatedDirective + " " + event.blockedURI);
});
"""


@pytest.fixture(scope="session")
def browser() -> Iterator[Browser]:
    # The sync API runs its own event loop in this thread, which Django's
    # async-safety check mistakes for async code calling the ORM.
    os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


#: Every trigger's SQL, as the migrations installed it; filled on first use.
_TRIGGERS: dict[str, str] = {}


@pytest.fixture
def _flushable_db(transactional_db: None) -> Iterator[None]:
    """The live server needs committed data, and pytest-django then empties
    every table after the test. The invariant triggers refuse exactly that
    (INV-3 on the audit log and on polls, INV-7 on the roll snapshot), so
    they are dropped just before the flush and put back before the next
    test: each test runs with all of them in force."""
    with connection.cursor() as cursor:
        if not _TRIGGERS:
            cursor.execute("SELECT name, sql FROM sqlite_master WHERE type = 'trigger'")
            _TRIGGERS.update(cursor.fetchall())
        cursor.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")
        present = {name for (name,) in cursor.fetchall()}
        for name, sql in _TRIGGERS.items():
            if name not in present:
                cursor.execute(sql)
    yield
    with connection.cursor() as cursor:
        for name in _TRIGGERS:
            cursor.execute(f'DROP TRIGGER IF EXISTS "{name}"')


@pytest.fixture
def page(browser: Browser, live_server: Any, _flushable_db: None) -> Iterator[Page]:
    context = browser.new_context(base_url=live_server.url, locale="fr-FR")
    context.add_init_script(_RECORD_CSP)
    page = context.new_page()
    errors: list[str] = []

    def on_console(message: ConsoleMessage) -> None:
        if message.type == "error":
            errors.append(message.text)

    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", on_console)
    setattr(page, "script_errors", errors)  # noqa: B010 — read back by check_page
    yield page
    context.close()


def check_page(page: Page) -> None:
    """No script error, no CSP violation, and no WCAG 2.1 AA violation axe can
    detect, on the page as it now stands."""
    assert getattr(page, "script_errors") == []  # noqa: B009
    assert page.evaluate("window.__cspViolations") == []
    if not AXE.exists():
        pytest.fail("axe-core is missing: run `npm ci` first")
    # Evaluated, not injected as a <script>: the CSP would rightly block that.
    result = page.evaluate(
        AXE.read_text(encoding="utf-8")
        + f"; axe.run(document, {{runOnly: {{type: 'tag', values: {AXE_TAGS!r}}}}})"
    )
    violations = [
        f"{v['id']} ({v['impact']}): {v['help']} — "
        + ", ".join(node["target"][0] for node in v["nodes"][:3])
        for v in result["violations"]
    ]
    assert violations == [], f"{page.url}\n" + "\n".join(violations)
    assert result["passes"], "axe checked nothing: the page did not load as expected"
