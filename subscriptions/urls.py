from django.urls import path
from . import views

app_name = 'subscriptions'

urlpatterns = [
    path('', views.subscription_plans, name='subscription_plans'),
    path('subscribe/<int:plan_id>/', views.subscribe, name='subscribe'),
    path('manage/', views.manage_subscription, name='manage_subscription'),
    path('admin/approve_payment/<int:payment_id>/', views.approve_payment, name='approve_payment'),
    path('confirm_toggle_limit/<int:user_id>/<str:target>/', views.confirm_toggle_limit, name='confirm_toggle_limit'),
    path('toggle_limit_suspension/<int:user_id>/<str:target>/', views.toggle_limit_suspension, name='toggle_limit_suspension'),

]
