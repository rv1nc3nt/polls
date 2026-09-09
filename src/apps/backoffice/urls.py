# SPDX-License-Identifier: 0BSD
from django.urls import path

from . import views

app_name = "backoffice"

# Commune-level routes carry no ``<uuid:poll_id>`` and go through
# ``access.require_commune_admin``; poll-scoped routes carry ``<uuid:poll_id>``,
# which ``access.require_poll_role`` resolves and gates — a poll-scoped route
# that does not is a screen open to anyone signed in.
# TODO(scaffold): screen 11 of §6.5 — première installation — lands here, but
# before any account exists, so it is gated on there being no account rather
# than on the commune-admin flag.
urlpatterns = [
    path("", views.poll_index, name="poll_index"),
    path("connexion/", views.OperatorLoginView.as_view(), name="login"),
    path("deconnexion/", views.OperatorLogoutView.as_view(), name="logout"),
    path("comptes/", views.account_admin, name="account_admin"),
    path("comptes/roles/", views.role_admin, name="role_admin"),
    path("scrutin/<uuid:poll_id>/", views.poll_dashboard, name="dashboard"),
    path("scrutin/<uuid:poll_id>/configuration/", views.poll_config, name="poll_config"),
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
    path(
        "scrutin/<uuid:poll_id>/bulletin-papier/",
        views.paper_entry,
        name="paper_entry",
    ),
    path(
        "scrutin/<uuid:poll_id>/bulletins-papier/",
        views.paper_ballot_list,
        name="paper_ballot_list",
    ),
    path(
        "scrutin/<uuid:poll_id>/bulletin-papier/<uuid:ballot_id>/",
        views.paper_ballot,
        name="paper_ballot",
    ),
    path(
        "scrutin/<uuid:poll_id>/bulletin-papier/<uuid:ballot_id>/recu/",
        views.paper_receipt,
        name="paper_receipt",
    ),
    path(
        "scrutin/<uuid:poll_id>/contreseing/",
        views.countersign_queue,
        name="countersign_queue",
    ),
    path(
        "scrutin/<uuid:poll_id>/depouillement/",
        views.results_publish,
        name="results_publish",
    ),
]
