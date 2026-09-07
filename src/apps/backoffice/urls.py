# SPDX-License-Identifier: 0BSD
from django.urls import path

from . import views

app_name = "backoffice"

# TODO(scaffold): the eleven screens of §6.5 land here. Poll-scoped routes carry
# ``<uuid:poll_id>``, which ``access.require_poll_role`` resolves and gates.
urlpatterns = [
    path("", views.poll_index, name="poll_index"),
    path("connexion/", views.OperatorLoginView.as_view(), name="login"),
    path("deconnexion/", views.OperatorLogoutView.as_view(), name="logout"),
]
