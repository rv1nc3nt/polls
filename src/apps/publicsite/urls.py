# SPDX-License-Identifier: 0BSD
from django.urls import path

from . import views

app_name = "publicsite"

urlpatterns = [
    path("", views.poll_list, name="poll_list"),
    path("scrutin/<uuid:poll_id>/", views.poll_detail, name="poll_detail"),
    path("scrutin/<uuid:poll_id>/resultats/", views.results, name="results"),
]
