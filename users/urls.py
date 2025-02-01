from django.urls import path
from . import views
from .views import ProfileUpdateView



urlpatterns = [
    path('register/', views.register, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('artist_dashboard/', views.artist_dashboard, name='artist_dashboard'),
    path('fan_dashboard/', views.fan_dashboard, name='fan_dashboard'),
    path('admin_dashboard/', views.admin_dashboard, name='admin_dashboard'),
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
]
