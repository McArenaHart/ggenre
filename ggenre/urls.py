"""
URL configuration for ggenre project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.contrib.auth import views as auth_views
from django.conf.urls.static import static
from content.views import home  # Import the home view

urlpatterns = [
    path('support/', admin.site.urls),
    path('', home, name='home'),  # Home page at the root URL
    path('users/', include('users.urls')),
    path('content/', include('content.urls')),
    path('subscriptions/', include('subscriptions.urls')),

    # Password change URLs
    path('password-change/', 
         auth_views.PasswordChangeView.as_view(
             template_name='users/password_change.html',
             success_url='/password-change-done/'
         ), 
         name='password_change'),
    
    path('password-change-done/', 
         auth_views.PasswordChangeDoneView.as_view(
             template_name='users/password_change_done.html'
         ), 
         name='password_change_done'),

]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

