from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.contrib import messages
from .forms import UserRegistrationForm, LoginForm, ProfileUpdateForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import UpdateView
from django.urls import reverse_lazy
from .models import CustomUser, Role, Follow
from content.models import Content, Comment
from subscriptions.models import UserSubscription, ArtistUploadLimit
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import  Notification
from content.models import Vote
from django.http import JsonResponse



# Utility function for role-based redirection
def role_based_redirect(user):
    if user.is_admin():
        return redirect('admin_dashboard')
    elif user.is_artist():
        return redirect('artist_dashboard')
    elif user.is_fan():
        return redirect('fan_dashboard')
    return redirect('dashboard')


# User Registration View
def register(request):
    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return role_based_redirect(user)  # Redirect to role-specific dashboard
    else:
        form = UserRegistrationForm()
    return render(request, 'users/register.html', {'form': form})


# User Login View
def login_view(request):
    if request.method == 'POST':
        form = LoginForm(data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            next_url = request.GET.get('next')
            return redirect(next_url) if next_url else role_based_redirect(user)
    else:
        form = LoginForm()
    return render(request, 'users/login.html', {'form': form})

def logout_view(request):
    logout(request)
    messages.success(request, "You have been logged out successfully.")
    return redirect('login')

# Admin Dashboard
@login_required
def admin_dashboard(request):
    if not request.user.has_role(Role.ADMIN):
        return redirect('dashboard')

    # Admin-specific data
    artists = ArtistUploadLimit.objects.select_related('artist').all()
    fans = UserSubscription.objects.select_related('user').all()
    content_query = Content.objects.all()
    query = request.GET.get('q', '')
    filter_status = request.GET.get('status', 'all')

    if query:
        content_query = content_query.filter(Q(title__icontains=query) | Q(artist__username__icontains=query))
    if filter_status == 'approved':
        content_query = content_query.filter(is_approved=True)
    elif filter_status == 'pending':
        content_query = content_query.filter(is_approved=False)

    if request.method == "POST":
        action = request.POST.get('action')
        content_ids = request.POST.getlist('content_ids')
        artist_ids = request.POST.getlist('artist_ids')

        if action == 'approve' and content_ids:
            Content.objects.filter(id__in=content_ids).update(is_approved=True)
            messages.success(request, f"Approved {len(content_ids)} content items.")
        elif action == 'disapprove' and content_ids:
            Content.objects.filter(id__in=content_ids).update(is_approved=False)
            messages.success(request, f"Disapproved {len(content_ids)} content items.")
        elif action == 'reset_limit' and artist_ids:
            artist_limits = ArtistUploadLimit.objects.filter(artist_id__in=artist_ids)
            for limit in artist_limits:
                limit.reset_limit()  # Calling the reset_limit method
            messages.success(request, f"Reset upload limits for {len(artist_limits)} artist(s).")

    context = {
        'artists': artists,
        'fans': fans,
        'recent_uploads': content_query.order_by('-upload_date')[:10],
        'query': query,
        'filter_status': filter_status,
        'statistics': {
            'total_users': CustomUser.objects.count(),
            'total_content': Content.objects.count(),
            'approved_content': Content.objects.filter(is_approved=True).count(),
            'pending_content': Content.objects.filter(is_approved=False).count(),
        },
    }
    return render(request, 'users/admin_dashboard.html', context)


# Artist Dashboard
@login_required
def artist_dashboard(request):
    if not request.user.has_role(Role.ARTIST):
        return redirect('dashboard')

    artist = request.user
    upload_limit, _ = ArtistUploadLimit.objects.get_or_create(artist=artist)
    context = {
        'total_uploads': Content.objects.filter(artist=artist).count(),
        'approved_content': Content.objects.filter(artist=artist, is_approved=True).count(),
        'pending_content': Content.objects.filter(artist=artist, is_approved=False).count(),
        'remaining_slots': max(0, upload_limit.upload_limit - upload_limit.uploads_used),
        'upload_limit': upload_limit.upload_limit,
    }
    return render(request, 'users/artist_dashboard.html', context)



@login_required
def artist_list(request):
    """
    View to display a list of all artists.
    """
    # Fetch all users with the role of 'artist'
    artists = CustomUser.objects.filter(role=Role.ARTIST)

    # Pass the artists to the template
    context = {
        'artists': artists,
    }
    return render(request, 'users/artist_list.html', context)


@login_required
def artist_content(request, artist_id):
    """
    View to display the content of a specific artist.
    """
    # Fetch the artist or return a 404 error if not found
    artist = get_object_or_404(CustomUser, id=artist_id, role=Role.ARTIST)

    # Fetch all content uploaded by the artist
    artist_content = Content.objects.filter(artist=artist)

    # Pass the artist and their content to the template
    context = {
        'artist': artist,
        'artist_content': artist_content,
    }
    return render(request, 'users/artist_content.html', context)


# Fan Dashboard
@login_required
def fan_dashboard(request):
    if not request.user.has_role(Role.FAN):
        return redirect('dashboard')

    fan = request.user
    context = {
        'total_votes': fan.user_votes.count(),
        'voted_content': fan.user_votes.select_related('content').order_by('-timestamp')[:10],
    }
    return render(request, 'users/fan_dashboard.html', context)


# Unified Dashboard Redirect
@login_required
def dashboard(request):
    return role_based_redirect(request.user)



@login_required
def profile(request):
    user_subscription = UserSubscription.objects.filter(user=request.user).first()
    subscription_status = "Inactive"
    upload_limit = 0
    vote_limit = 0

    if user_subscription and user_subscription.is_active:
        subscription_status = "Active"
        upload_limit = user_subscription.upload_limit
        vote_limit = user_subscription.vote_limit

    if request.method == 'POST':
        form = ProfileUpdateForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated successfully.")
            return redirect('profile')
    else:
        form = ProfileUpdateForm(instance=request.user)

    context = {
        'form': form,
        'subscription_status': subscription_status,
        'upload_limit': upload_limit,
        'vote_limit': vote_limit,
    }
    return render(request, 'users/profile.html', context)


@login_required
def user_profile(request, user_id):
    user = get_object_or_404(CustomUser, id=user_id)
    is_following = Follow.objects.filter(follower=request.user, following=user).exists()

    # Handle Follow/Unfollow action
    if 'follow' in request.POST:
        if is_following:
            Follow.objects.filter(follower=request.user, following=user).delete()
            messages.success(request, f'You have unfollowed {user.username}.')
        else:
            Follow.objects.create(follower=request.user, following=user)
            messages.success(request, f'You are now following {user.username}.')
        return redirect('user_profile', user_id=user.id)

    # Handle Profile Update action
    if 'update_profile' in request.POST:
        form = ProfileUpdateForm(request.POST, request.FILES, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated successfully.")
            return redirect('user_profile', user_id=user.id)
    else:
        form = ProfileUpdateForm(instance=user)

    # Prepare context data
    context = {
        'profile_user': user,
        'is_following': is_following,
        'form': form,
    }

    # Add artist-specific data if the user is an artist
    if user.is_artist():
        user_content = Content.objects.filter(artist=user)
        context.update({
            'user_content': user_content,
            'is_artist': True,
        })
    else:
        followed_artists = user.following.filter(following__role=Role.ARTIST)
        context.update({
            'followed_artists': followed_artists,
            'is_artist': False,
        })

    return render(request, 'users/profile.html', context)


@login_required
def follow_user(request, user_id):
    user_to_follow = get_object_or_404(CustomUser, id=user_id)
    if request.user != user_to_follow:
        Follow.objects.get_or_create(follower=request.user, following=user_to_follow)
        messages.success(request, f'You are now following {user_to_follow.username}.')
    return redirect('user_profile', user_id=user_id)


@login_required
def unfollow_user(request, user_id):
    user_to_unfollow = get_object_or_404(CustomUser, id=user_id)
    Follow.objects.filter(follower=request.user, following=user_to_unfollow).delete()
    messages.success(request, f'You have unfollowed {user_to_unfollow.username}.')
    return redirect('user_profile', user_id=user_id)





@receiver(post_save, sender=Vote)
def notify_artist_on_vote(sender, instance, **kwargs):
    """
    Send a notification to the artist when their content is voted on.
    """
    content = instance.content
    artist = content.artist
    message = f"{instance.fan.username} voted {instance.value} on your content: {content.title}"

    # Create a notification for the artist
    Notification.objects.create(user=artist, message=message)




@receiver(post_save, sender=Comment)
def notify_artist_on_comment(sender, instance, **kwargs):
    """
    Send a notification to the artist when their content is commented on.
    """
    content = instance.content
    artist = content.artist
    message = f"{instance.user.username} commented on your content: {content.title}"

    # Create a notification for the artist
    Notification.objects.create(user=artist, message=message)





# @receiver(post_save, sender=Content)
# def notify_subscribers_on_new_content(sender, instance, **kwargs):
#     """
#     Send a notification to all subscribers when an artist uploads new content.
#     """
#     artist = instance.artist
#     subscribers = ArtistSubscription.objects.filter(artist=artist)

#     for subscription in subscribers:
#         message = f"{artist.username} uploaded new content: {instance.title}"
#         Notification.objects.create(user=subscription.fan, message=message)



@login_required
def notifications_view(request):
    """
    View to display notifications for the logged-in user.
    """
    notifications = Notification.objects.filter(user=request.user, is_read=False).order_by('-created_at')
    return render(request, 'users/notifications.html', {'notifications': notifications})



@login_required
def mark_notifications_as_read(request):
    """
    Mark all unread notifications as read for the logged-in user.
    """
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return JsonResponse({'status': 'success'})


class ProfileUpdateView(LoginRequiredMixin, UpdateView):
    model = CustomUser
    form_class = ProfileUpdateForm
    template_name = 'users/profile.html'  # Template for the profile update form
    success_url = reverse_lazy('profile')  # Redirect to the profile page after successful update

    def get_object(self, queryset=None):
        return self.request.user  # Ensure the logged-in user is the one being updated


