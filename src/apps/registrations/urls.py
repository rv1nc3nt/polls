# SPDX-License-Identifier: 0BSD
from django.urls import path

from . import views

app_name = "registrations"

urlpatterns = [
    path("<uuid:poll_id>/", views.register, name="register"),
    path("<uuid:poll_id>/recu/<str:outcome>/", views.submitted, name="submitted"),
    # The token appears in this one URL and nowhere else. nginx must suppress
    # request-URI logging for the prefix (§6.3); the redirect below is what
    # keeps it out of every subsequent request.
    path("<uuid:poll_id>/confirmation/<str:token>/", views.confirm, name="confirm"),
    path("<uuid:poll_id>/confirmee/", views.confirmed, name="confirmed"),
]
