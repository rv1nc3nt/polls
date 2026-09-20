# SPDX-License-Identifier: 0BSD
from django.urls import path

from . import views

app_name = "publicsite"

urlpatterns = [
    path("", views.poll_list, name="poll_list"),
    path("aide/", views.help_page, name="help"),
    path("aide/images/<str:name>", views.manual_image, name="manual_image"),
    path("aide/<slug:slug>/", views.manual_page, name="manual_page"),
    path("scrutin/<uuid:poll_id>/", views.poll_detail, name="poll_detail"),
    path(
        "scrutin/<uuid:poll_id>/apercu/<str:token>/",
        views.poll_preview_shared,
        name="poll_preview_shared",
    ),
    path("scrutin/<uuid:poll_id>/resultats/", views.results, name="results"),
]
