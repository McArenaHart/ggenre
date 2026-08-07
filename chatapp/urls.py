from django.urls import path

from . import views

app_name = "chatapp"

urlpatterns = [
    path("", views.chat_index, name="index"),
    path("admin-inbox/", views.admin_inbox, name="admin_inbox"),
    path(
        "admin-inbox/missions/<int:mission_id>/claim/",
        views.admin_claim_mission_request,
        name="admin_claim_mission_request",
    ),
    path(
        "admin-inbox/missions/<int:mission_id>/assign-opponent/",
        views.admin_assign_mission_opponent,
        name="admin_assign_mission_opponent",
    ),
    path(
        "admin-inbox/missions/<int:mission_id>/control/",
        views.admin_mission_control_action,
        name="admin_mission_control_action",
    ),
    path("admin-inbox/review-center/", views.admin_review_center, name="admin_review_center"),
    path(
        "admin-inbox/review-center/route-mode/",
        views.admin_review_route_mode_update,
        name="admin_review_route_mode_update",
    ),
    path(
        "admin-inbox/review-center/missions/<int:evidence_id>/",
        views.admin_review_mission_action,
        name="admin_review_mission_action",
    ),
    path(
        "admin-inbox/review-center/token-requests/<int:request_id>/",
        views.admin_review_token_action,
        name="admin_review_token_action",
    ),
    path(
        "admin-inbox/review-center/token-requests/bulk/",
        views.admin_review_bulk_token_action,
        name="admin_review_bulk_token_action",
    ),
    path("admin-inbox/unread-count/", views.admin_unread_count, name="admin_unread_count"),
    path("admin-contact/unread-count/", views.admin_contact_unread_count, name="admin_contact_unread_count"),
    path("admin-contact/mark-read/", views.mark_admin_contact_read, name="mark_admin_contact_read"),
    path("missions/request/", views.mission_request, name="mission_request"),
    path("missions/my/", views.mission_center, name="mission_center"),
    path("missions/latest/", views.mission_latest, name="mission_latest"),
    path("missions/<int:mission_id>/", views.mission_detail, name="mission_detail"),
    path("missions/<int:mission_id>/action/", views.mission_action, name="mission_action"),
    path("token-purchases/request/", views.token_purchase_create, name="token_purchase_create"),
    path("token-purchases/<int:request_id>/review/", views.token_purchase_review, name="token_purchase_review"),
    path("rate/<int:user_id>/", views.rate_user, name="rate_user"),
    path("u/<int:user_id>/history/", views.direct_chat_history, name="direct_history"),
    path("u/<int:user_id>/", views.direct_chat, name="direct"),
]
