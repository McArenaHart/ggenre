from django.urls import path
from . import views



urlpatterns = [
    path('upload/', views.upload_content, name='upload_content'),
    path('list/', views.list_content, name='content_list'),
    path("increment-views/<int:content_id>/", views.increment_views, name="increment_views"),
    path('content/<int:content_id>/', views.content_detail, name='content_detail'), 
    path('vote_content/<int:content_id>/', views.vote_content, name='vote_content'),
    path('delete/<int:pk>/', views.delete_content, name='delete_content'),  # New URL for content deletion
    path('content/toggle/<int:content_id>/<str:action>/', views.toggle_content_approval, name='toggle_content_approval'),
    path('live/', views.live_stream_index, name="live_stream_index"),
    path('live/start/', views.start_live_stream, name='start_live_stream'),
    path('live/<str:room_name>/', views.live_stream_room, name="live_stream_room"),
    path('upload/reset/<int:artist_id>/', views.reset_artist_upload_limit, name='reset_upload_limit'),
    path('comment/add/<int:content_id>/', views.add_comment, name='add_comment'),
    path('classify/<int:content_id>/', views.classify_content, name='classify_content'),
 
]
