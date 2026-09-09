# SPDX-License-Identifier: 0BSD
from django.urls import path

from . import views

app_name = "registrations"

urlpatterns = [
    path("<uuid:poll_id>/", views.register, name="register"),
    path("<uuid:poll_id>/recu/<str:outcome>/", views.submitted, name="submitted"),
    # The confirmation-mail link lands on ``ballots:access``: one link confirms
    # the mailbox and opens the ballot (§6.3). The token rules of R-7.4 ter are
    # applied there.
]
