# SPDX-License-Identifier: 0BSD
"""Root URL configuration.

Django admin is deliberately absent (§14). Voter-facing and back-office URLs
are wrapped in ``i18n_patterns`` so that a ballot link is language-explicit and
shareable (§3.8); ``/sante`` is not, since monitoring should not be redirected.
"""

from django.conf import settings
from django.conf.urls.i18n import i18n_patterns
from django.conf.urls.static import static
from django.urls import include, path

from apps.publicsite.views import health

urlpatterns = [
    path("sante", health, name="health"),
    path("i18n/", include("django.conf.urls.i18n")),
]

urlpatterns += i18n_patterns(
    path("", include("apps.publicsite.urls")),
    path("bulletin/", include("apps.ballots.urls")),
    path("inscription/", include("apps.registrations.urls")),
    path("mairie/", include("apps.backoffice.urls")),
)

# §15: in production nginx serves MEDIA_URL directly, the same way it serves
# STATIC_URL — see ansible/roles/polls/templates/nginx-vhost.conf.j2. This is
# only for `manage.py runserver`, hence the DEBUG guard; gunicorn behind
# nginx never reaches it.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
