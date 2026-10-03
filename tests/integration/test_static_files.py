# SPDX-License-Identifier: 0BSD
"""Static files under content-hashed names in production (review A-9).

nginx lets browsers keep ``/static/`` for good, which is only safe if a file
that changes changes its name. Production collects through
``ManifestStaticFilesStorage``; this runs that collection and renders pages
through it, as ``collectstatic`` at deploy would, so a ``{% static %}`` naming
a file that does not exist, or a stylesheet ``url()`` that does not resolve,
fails here instead of on the server.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.core.management import call_command
from django.test import Client, override_settings

PROD_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"},
}


def test_pages_name_their_assets_by_content(client: Client, db: None, tmp_path: Path) -> None:
    with override_settings(STATIC_ROOT=tmp_path, STORAGES=PROD_STORAGES):
        call_command("collectstatic", interactive=False, verbosity=0)
        assert (tmp_path / "staticfiles.json").exists()
        for url in ("/fr/", "/fr/mairie/installation/"):
            body = client.get(url).content.decode()
            assets = re.findall(r'(?:href|src)="(/static/[^"]+)"', body)
            assert assets, url
            for asset in assets:
                assert re.search(r"\.[0-9a-f]{12}\.(css|js|png|ico|svg|woff2)$", asset), asset
                assert (tmp_path / asset.removeprefix("/static/")).exists(), asset


def test_the_stylesheet_points_at_hashed_fonts(db: None, tmp_path: Path) -> None:
    with override_settings(STATIC_ROOT=tmp_path, STORAGES=PROD_STORAGES):
        call_command("collectstatic", interactive=False, verbosity=0)
        css = next(tmp_path.glob("css/app.*.css")).read_text()
        fonts = re.findall(r"url\(['\"]?([^'\")]+)", css)
        assert fonts
        assert all(re.search(r"\.[0-9a-f]{12}\.woff2$", f) for f in fonts), fonts
