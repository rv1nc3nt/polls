# SPDX-License-Identifier: 0BSD
from django.urls import path

from . import views

app_name = "ballots"

# The token appears in ``access`` and nowhere else. nginx suppresses
# request-URI logging for this prefix (§6.3, R-7.4 ter); every other route here
# is token-free, and ``access`` redirects to one as soon as it can.
urlpatterns = [
    path("<uuid:poll_id>/acces/<str:token>/", views.access, name="access"),
    path("<uuid:poll_id>/modifier/", views.modify, name="modify"),
    path("<uuid:poll_id>/recu/", views.receipt, name="receipt"),
    path("<uuid:poll_id>/info/<str:kind>/", views.notice, name="notice"),
]
