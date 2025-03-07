from django.urls import path
from . import views
from .views import ProfileUpdateView



urlpatterns = [
    path('register/', views.register, name='register'),
    path('verify-otp/<int:user_id>/', views.verify_otp, name='verify_otp'),  # ✅ Add this line
    path('resend-otp/<int:user_id>/', views.resend_otp, name='resend_otp'),  # Ensure resend-otp is also present
    path('terms-and-conditions/', views.terms_and_conditions, name='terms_and_conditions'),
    path('export/', views.export_data, name='export_data'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('artist_dashboard/', views.artist_dashboard, name='artist_dashboard'),
    path('fan_dashboard/', views.fan_dashboard, name='fan_dashboard'),
    path('admin_dashboard/', views.admin_dashboard, name='admin_dashboard'),
    # Approve/Disapprove Content for Voting
    path('toggle_content_voting/<int:content_id>/<str:action>/', views.toggle_content_voting, name='toggle_content_voting'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('profile/', views.profile, name='profile'),  # Profile page for logged-in user
    path('profile/<int:user_id>/', views.user_profile, name='user_profile'),  # Profile page for any user
    path('profile/update/', ProfileUpdateView.as_view(), name='update_profile'),
    path('follow/<int:user_id>/', views.follow_user, name='follow_user'),
    path('unfollow/<int:user_id>/', views.unfollow_user, name='unfollow_user'),
    path('artists/', views.artist_list, name='artist_list'),
    path('artists/<int:artist_id>/', views.artist_content, name='artist_content'),
    path('notifications/', views.notifications_view, name='notifications'),
    path('notifications/mark-as-read/', views.mark_notifications_as_read, name='mark_notifications_as_read'),
    path('api/announcements/', views.get_announcements, name='get_announcements'),
    path('api/announcements/dismiss/<int:announcement_id>/', views.dismiss_announcement, name='dismiss_announcement'),
    path('announcements/delete/<int:announcement_id>/', views.delete_announcement, name='delete_announcement'),
    path('search/', views.search_results, name='search_results'),
]
