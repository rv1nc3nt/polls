# SPDX-License-Identifier: 0BSD
from django.urls import path

from . import views

app_name = "backoffice"

# TODO(scaffold): screens 2, 5–7 and 9–11 of §6.5 land here. Poll-scoped routes
# carry ``<uuid:poll_id>``, which ``access.require_poll_role`` resolves and
# gates — a route that does not is a screen open to anyone signed in.
urlpatterns = [
    path("", views.poll_index, name="poll_index"),
    path("connexion/", views.OperatorLoginView.as_view(), name="login"),
    path("deconnexion/", views.OperatorLogoutView.as_view(), name="logout"),
    path("scrutin/<uuid:poll_id>/", views.poll_dashboard, name="dashboard"),
    path("scrutin/<uuid:poll_id>/journal/", views.audit_log, name="audit_log"),
    path(
        "scrutin/<uuid:poll_id>/inscriptions/",
        views.registration_queue,
        name="registration_queue",
    ),
    path(
        "scrutin/<uuid:poll_id>/inscriptions/decision/",
        views.registration_decide,
        name="registration_decide",
    ),
    path(
        "scrutin/<uuid:poll_id>/liste-electorale/",
        views.roll_import,
        name="roll_import",
    ),
    path(
        "scrutin/<uuid:poll_id>/liste-electorale/verification/",
        views.roll_import_review,
        name="roll_import_review",
    ),
]
