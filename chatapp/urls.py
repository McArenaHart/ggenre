from django.urls import path

from . import views

app_name = "chatapp"

urlpatterns = [
    path("", views.chat_index, name="index"),
    path("admin-inbox/", views.admin_inbox, name="admin_inbox"),
    path("admin-inbox/unread-count/", views.admin_unread_count, name="admin_unread_count"),
    path("admin-contact/unread-count/", views.admin_contact_unread_count, name="admin_contact_unread_count"),
    path("admin-contact/mark-read/", views.mark_admin_contact_read, name="mark_admin_contact_read"),
    path("rate/<int:user_id>/", views.rate_user, name="rate_user"),
    path("u/<int:user_id>/", views.direct_chat, name="direct"),
]
