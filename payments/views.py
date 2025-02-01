import stripe
from django.shortcuts import render, redirect
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Subscription
from users.models import Profile

stripe.api_key = settings.STRIPE_SECRET_KEY

@login_required
def subscribe_artist(request):
    if request.user.profile.role != 'artist':
        return redirect('fan_dashboard')

    if request.method == 'POST':
        # Stripe payment handling
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': 'Artist Subscription',
                    },
                    'unit_amount': 1000,  # $10.00
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=request.build_absolute_uri('/success/'),
            cancel_url=request.build_absolute_uri('/cancel/'),
        )
        return redirect(session.url, code=303)
    return render(request, 'payments/subscribe.html')

@login_required
def payment_success(request):
    # Activate subscription
    Subscription.objects.create(user=request.user, is_active=True)
    request.user.profile.subscription_active = True
    request.user.profile.save()
    messages.success(request, "Subscription activated!")
    return redirect('artist_dashboard')
