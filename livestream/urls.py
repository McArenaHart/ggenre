from django.urls import path

from . import views

app_name = "livestream"

urlpatterns = [
    path("", views.stream_list, name="index"),
    path("create/", views.create_stream, name="create"),
    path("<uuid:stream_key>/", views.stream_room, name="room"),
    path("<uuid:stream_key>/start/", views.start_stream, name="start"),
    path("<uuid:stream_key>/end/", views.end_stream, name="end"),
    path("<uuid:stream_key>/access/", views.manage_access, name="manage_access"),
    path("<uuid:stream_key>/access/<int:grant_id>/revoke/", views.revoke_access, name="revoke_access"),
]
