from __future__ import annotations

from django.urls import path

from . import views

urlpatterns = [
    path(
        "control/organizer/<str:organizer>/ebics/",
        views.ConnectionListView.as_view(),
        name="list",
    ),
    path(
        "control/organizer/<str:organizer>/ebics/add/",
        views.ConnectionCreateView.as_view(),
        name="add",
    ),
    path(
        "control/organizer/<str:organizer>/ebics/<int:pk>/edit/",
        views.ConnectionUpdateView.as_view(),
        name="edit",
    ),
    path(
        "control/organizer/<str:organizer>/ebics/<int:pk>/delete/",
        views.ConnectionDeleteView.as_view(),
        name="delete",
    ),
    path(
        "control/organizer/<str:organizer>/ebics/<int:pk>/action/",
        views.ConnectionActionView.as_view(),
        name="action",
    ),
    path(
        "control/organizer/<str:organizer>/ebics/<int:pk>/ini-letter/",
        views.IniLetterView.as_view(),
        name="iniletter",
    ),
]
