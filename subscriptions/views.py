from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from .models import UserSubscription, Payment, SubscriptionPlan, ArtistUploadLimit
from django.core.paginator import Paginator
from django.utils.timezone import now
from datetime import timedelta
from django.contrib.auth.decorators import user_passes_test
from django.http import HttpResponseForbidden


# Helper function to check if the user is an admin
def is_admin(user):
    return user.is_superuser


# List available subscription plans
def subscription_plans(request):
    plans = SubscriptionPlan.objects.all()
    return render(request, 'subscriptions/subscription_plans.html', {'plans': plans})


@login_required
def subscribe(request, plan_id):
    plan = get_object_or_404(SubscriptionPlan, id=plan_id)

    # Check if the user already has an active subscription for this plan
    existing_subscription = UserSubscription.objects.filter(
        user=request.user,
        subscription_type=plan.name,
        is_active=True
    ).exists()

    if existing_subscription:
        messages.warning(request, 'You already have an active subscription for this plan.')
        return redirect('subscriptions:subscription_plans')

    # Create a payment record and set to pending
    payment = Payment.objects.create(
        user=request.user,
        amount=plan.price,
        transaction_id=f"manual-{now().strftime('%Y%m%d%H%M%S')}",
        payment_method='manual',
        payment_status='pending'
    )

    # Create the subscription but keep it inactive until payment is approved
    UserSubscription.objects.create(
        user=request.user,
        subscription_type=plan.name,
        start_date=now(),
        end_date=now() + timedelta(days=plan.duration),
        is_active=False,
        payment=payment
    )

    messages.success(request, 'Your subscription request has been submitted. Please complete the payment offline.')
    return redirect('subscriptions:manage_subscription')


@login_required
def manage_subscription(request):
    subscriptions = UserSubscription.objects.filter(user=request.user)

    # Pagination
    paginator = Paginator(subscriptions, 10)  # 10 items per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = []
    for sub in page_obj:
        context.append({
            'plan_name': sub.subscription_type,
            'start_date': sub.start_date,
            'end_date': sub.end_date,
            'is_active': sub.is_active,
            'remaining_uploads': sub.upload_limit - sub.free_uploads_used,
            'remaining_votes': sub.vote_limit - sub.free_votes_used,
        })

    return render(request, 'subscriptions/manage_subscription.html', {'subscriptions': context, 'page_obj': page_obj})



# Admin view to approve payment and activate the subscription
@user_passes_test(is_admin)
def approve_payment(request, payment_id):
    payment = get_object_or_404(Payment, id=payment_id)

    if request.method == 'POST':
        # Mark payment as completed
        payment.payment_status = 'completed'
        payment.save()

        # Activate the associated subscription
        user_subscription = payment.user_subscription
        user_subscription.activate_subscription()

        messages.success(request, f'Payment approved for {user_subscription.user}. Subscription activated.')
        return redirect('subscriptions:admin_payments')

    return render(request, 'subscriptions/approve_payment.html', {'payment': payment})


# Admin view to manage all payments
@user_passes_test(is_admin)
def admin_payments(request):
    payments = Payment.objects.all().order_by('-date')
    return render(request, 'subscriptions/admin_payments.html', {'payments': payments})


def is_admin(user):
    return user.is_superuser

@user_passes_test(is_admin)
def toggle_limit_suspension(request, user_id, target):
    """
    Admin view to suspend or reinstate upload/vote limits.
    :param user_id: ID of the target user
    :param target: 'artist' or 'fan'
    """
    if request.method == 'POST':
        if target == 'artist':
            upload_limit = get_object_or_404(ArtistUploadLimit, artist_id=user_id)
            upload_limit.suspended_by_admin = not upload_limit.suspended_by_admin
            upload_limit.save()
            status = "suspended" if upload_limit.suspended_by_admin else "reinstated"
            messages.success(request, f"Upload limits for {upload_limit.artist.username} have been {status}.")
        elif target == 'fan':
            subscription = get_object_or_404(UserSubscription, user_id=user_id)
            subscription.suspended_by_admin = not subscription.suspended_by_admin
            subscription.save()
            status = "suspended" if subscription.suspended_by_admin else "reinstated"
            messages.success(request, f"Voting limits for {subscription.user.username} have been {status}.")

        return redirect('dashboard')

    return render(request, 'subscriptions/confirm_toggle_limit.html', {'user_id': user_id, 'target': target})


def confirm_toggle_limit(request, user_id, target):
    print(f"User ID: {user_id}, Target: {target}")  # Debugging

    if target == 'artist':
        user_limit = get_object_or_404(ArtistUploadLimit, artist_id=user_id)
        user = user_limit.artist  # Use `artist` for artists
    elif target == 'fan':
        user_limit = get_object_or_404(UserSubscription, user_id=user_id)
        user = user_limit.user  # Use `user` for fans
    else:
        messages.error(request, "Invalid user type.")
        return redirect('admin_dashboard')

    print(f"User Limit: {user_limit}")  # Debugging
    print(f"User ID: {user.id}, Username: {user.username}")  # Debugging

    return render(request, 'subscriptions/confirm_toggle_limit.html', {
        'user_limit': user_limit,
        'target': target,
        'user': user,  # Pass the user object to the template
    })


