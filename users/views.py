from django.shortcuts import render, redirect, get_object_or_404, HttpResponse
from django.contrib.auth import login, authenticate, logout, get_user_model
from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Q
from django.contrib import messages
from .forms import UserRegistrationForm, LoginForm, ProfileUpdateForm, AnnouncementForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import UpdateView
from django.urls import reverse_lazy, reverse
from django.contrib.auth.tokens import default_token_generator
import random
from django.http import JsonResponse
from .models import Announcement, DismissedAnnouncement
import logging
from django.db.models import Avg, Sum, Count, When, IntegerField, Case
from django.core.mail import send_mail, BadHeaderError
from django.utils.timezone import now
from datetime import timedelta
from .models import CustomUser, Role, Follow, OTP, TermsAndConditions
from content.models import Content, Comment, Badge, Voucher
from subscriptions.models import UserSubscription
from content.models import ArtistUploadLimit, LivePerformance
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import  Notification
from content.models import Vote
from django.http import HttpResponseForbidden
from django.http import JsonResponse
from content.views import calculate_final_ranking
from django.utils import timezone
import csv
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from io import BytesIO




logger = logging.getLogger(__name__)


# Utility function for role-based redirection
def role_based_redirect(user):
    if user.is_admin():
        return redirect('admin_dashboard')
    elif user.is_artist():
        return redirect('artist_dashboard')
    elif user.is_fan():
        return redirect('fan_dashboard')
    return redirect('dashboard')



CustomUser = get_user_model()  # Ensure correct user model

# Generate OTP
def generate_otp():
    return str(random.randint(100000, 999999))



def send_otp_email(user, otp):
    subject = "Your OTP Code"
    message = f"Hello {user.username},\n\nYour OTP code is: {otp}\n\nUse this code to verify your account. It expires in 5 minutes."
    
    try:
        send_mail(subject, message, settings.EMAIL_HOST_USER, [user.email])
        logger.info(f"✅ OTP {otp} sent to {user.email}")
    except BadHeaderError:
        logger.error("❌ Invalid header found while sending OTP email.")
    except Exception as e:
        logger.error(f"❌ Failed to send OTP email: {e}")


# Register with OTP Verification (via Email)
def register(request):
    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_active = False  # User inactive until OTP verification
            user.save()

            otp_code = generate_otp()
            OTP.objects.create(user=user, otp_code=otp_code)
            send_otp_email(user, otp_code)

            messages.info(request, "OTP sent to your email. Verify to activate your account.")
            return redirect(reverse('verify_otp', args=[user.id]))  # ✅ FIXED
    else:
        form = UserRegistrationForm()
    
    return render(request, 'users/register.html', {'form': form})


def terms_and_conditions(request):
    return render(request, 'users/terms_and_conditions.html')

# OTP Verification
def verify_otp(request, user_id):
    user = get_object_or_404(CustomUser, id=user_id)  # ✅ FIXED

    if request.method == 'POST':
        entered_otp = request.POST.get('otp')
        otp_record = OTP.objects.filter(user=user).first()

        if otp_record and otp_record.otp_code == entered_otp and not otp_record.is_expired():  # ✅ FIXED
            user.is_active = True
            user.save()
            otp_record.delete()
            messages.success(request, "OTP verified! You can now log in.")
            return redirect('login')
        else:
            messages.error(request, "Invalid or expired OTP.")

    return render(request, 'users/verify_otp.html', {'user_id': user.id})

# Resend OTP (via Email)
def resend_otp(request, user_id):
    user = get_object_or_404(CustomUser, id=user_id)  # ✅ FIXED
    otp_record = OTP.objects.filter(user=user).first()
    
    if otp_record:
        otp_record.delete()
    
    otp_code = generate_otp()
    OTP.objects.create(user=user, otp_code=otp_code)
    send_otp_email(user, otp_code)
    
    messages.info(request, "A new OTP has been sent to your email.")
    return redirect(reverse('verify_otp', args=[user.id]))

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

@login_required
def admin_dashboard(request):
    if not request.user.has_role(Role.ADMIN):
        return redirect('dashboard')

    # Admin-specific data
    fans = CustomUser.objects.filter(role=Role.FAN).order_by('username')
    generated_otp = None  # Store OTP to display in template
    generated_voucher = None #Store OTP to display in template




    # Fetch announcements for admin review
    announcements = Announcement.objects.all().order_by('-created_at')

    # Handle Announcement POST request
    if request.method == "POST" and request.POST.get("action") == "create_announcement":
        form = AnnouncementForm(request.POST)
        if form.is_valid():
            announcement = form.save(commit=False)
            announcement.created_by = request.user
            announcement.save()
            messages.success(request, "Announcement posted successfully!")
            return redirect('admin_dashboard')
        else:
            messages.error(request, "Failed to create announcement.")
    else:
        form = AnnouncementForm()

    # Initialize content_ranking with an empty queryset
    content_ranking = Content.objects.none()

    # Calculate voting statistics for display, even if no form is submitted
    try:
        content_ranking = Content.objects.annotate(
            total_points=Sum('votes__value'),
            total_votes=Count('votes'),
            badge_votes=Count(
                Case(
                    When(votes__is_badge_vote=True, then=1),
                    output_field=IntegerField()
                )
            )
        ).order_by('-total_points')
    except Exception as e:
        logger.error(f"Error calculating voting statistics: {str(e)}")
        messages.error(request, "An error occurred while calculating voting statistics.")

    # Fetch artists and recent uploads
    artists = ArtistUploadLimit.objects.select_related('artist').all()
    recent_uploads = Content.objects.all()
    live_performances = LivePerformance.objects.all().order_by('-start_time')

    # Apply filters for recent_uploads
    query = request.GET.get('q', '')
    filter_status = request.GET.get('status', 'all')
    category_filter = request.GET.get('category', '')

    if query:
        recent_uploads = recent_uploads.filter(Q(title__icontains=query) | Q(artist__username__icontains=query))
    if filter_status == 'approved':
        recent_uploads = recent_uploads.filter(is_approved=True)
    elif filter_status == 'pending':
        recent_uploads = recent_uploads.filter(is_approved=False)
    if category_filter:
        recent_uploads = recent_uploads.filter(category=category_filter)

    # Handle POST requests
    if request.method == "POST":
        action = request.POST.get('action')
        content_ids = request.POST.getlist('content_ids')
        artist_ids = request.POST.getlist('artist_ids')
        category = request.POST.get('category')

        if action == 'approve_for_voting' and content_ids:
            Content.objects.filter(id__in=content_ids).update(is_approved_for_voting=True)
            messages.success(request, f"Approved {len(content_ids)} content items for voting.")
        elif action == 'disapprove_for_voting' and content_ids:
            Content.objects.filter(id__in=content_ids).update(is_approved_for_voting=False)
            messages.success(request, f"Disapproved {len(content_ids)} content items for voting.")

        if action == 'approve' and content_ids:
            Content.objects.filter(id__in=content_ids).update(is_approved=True)
            messages.success(request, f"Approved {len(content_ids)} content items.")
        elif action == 'disapprove' and content_ids:
            Content.objects.filter(id__in=content_ids).update(is_approved=False)
            messages.success(request, f"Disapproved {len(content_ids)} content items.")
        elif action == 'reset_limit' and artist_ids:
            artist_limits = ArtistUploadLimit.objects.filter(artist_id__in=artist_ids)
            for limit in artist_limits:
                limit.reset_limit()  # This will now work
            messages.success(request, f"Reset upload limits for {len(artist_limits)} artist(s).")
        elif action == 'assign_category' and content_ids and category:
            Content.objects.filter(id__in=content_ids).update(category=category)
            messages.success(request, f"Assigned category '{category}' to {len(content_ids)} content items.")

    # Handle OTP access controls
    if request.method == "POST" and request.POST.get('otp_action'):
        otp_action = request.POST.get('otp_action')
        user_id = request.POST.get('user_id')
        vote_count_raw = request.POST.get('vote_count', '1')
        regenerate_code = request.POST.get('regenerate_code') == '1'

        try:
            vote_count = max(1, int(vote_count_raw))
        except (TypeError, ValueError):
            vote_count = 1

        fan = get_object_or_404(CustomUser, id=user_id, role=Role.FAN)
        otp, _ = OTP.objects.get_or_create(
            user=fan,
            defaults={
                'otp_code': generate_otp(),
                'remaining_votes': 0,
                'is_active': True,
            }
        )

        if otp_action == 'grant':
            otp.reset_votes(votes=vote_count, regenerate_code=generate_otp())
            generated_otp = otp.otp_code
            messages.success(request, f"OTP access granted to {fan.username} with {vote_count} vote(s).")
        elif otp_action == 'extend':
            otp.grant_votes(votes=vote_count)
            messages.success(request, f"Extended {fan.username}'s OTP by {vote_count} vote(s).")
        elif otp_action == 'cancel':
            otp.cancel_access()
            messages.warning(request, f"Cancelled OTP access for {fan.username}.")
        elif otp_action == 'reset':
            new_code = generate_otp() if regenerate_code else None
            otp.reset_votes(votes=vote_count, regenerate_code=new_code)
            generated_otp = otp.otp_code
            messages.success(request, f"Reset OTP votes for {fan.username} to {vote_count}.")
        else:
            messages.error(request, "Invalid OTP action.")

        return redirect('admin_dashboard')


    if request.method == "POST" and 'generate_voucher' in request.POST:
         user_id = request.POST.get('user_id')
         performance_id = request.POST.get('performance_id')
         user = get_object_or_404(CustomUser, id=user_id)
         performance = get_object_or_404(LivePerformance, id=performance_id)
         code = generate_otp()
         Voucher.objects.create(
             code=code,
             performance=performance,
             created_by=request.user
         )
         messages.success(request, f"Voucher generated for {user.username}: {code}")
         generated_voucher = code

    # Handle Badge Assignment and Removal
    if request.method == "POST" and ("assign_badge" in request.POST or "remove_badge" in request.POST):
        user_id = request.POST.get('user_id')

        if not user_id:
            messages.error(request, "No user selected.")
            return redirect('admin_dashboard')

        fan = get_object_or_404(CustomUser, id=user_id)

        if "assign_badge" in request.POST:
            badge_level = int(request.POST.get('badge_level', 1))
            badge, created = Badge.objects.get_or_create(user=fan)
            badge.level = badge_level
            badge.save()
            messages.success(request, f"Badge level {badge_level} assigned to {fan.username}.")

        elif "remove_badge" in request.POST:
            deleted, _ = Badge.objects.filter(user=fan).delete()
            if deleted:
                messages.success(request, f"Badge removed from {fan.username}.")
            else:
                messages.warning(request, f"{fan.username} does not have a badge to remove.")   

    otp_by_user = {
        otp.user_id: otp for otp in OTP.objects.filter(user__in=fans).select_related('user')
    }
    fan_otp_statuses = [
        {'fan': fan, 'otp': otp_by_user.get(fan.id)} for fan in fans
    ]

    # Prepare context
    context = {
        'announcements': announcements,
        'artists': artists,
        'fans': fans,
        'generated_otp': generated_otp,
        'fan_otp_statuses': fan_otp_statuses,
        'generated_voucher': generated_voucher,
        'recent_uploads': recent_uploads.order_by('-upload_date')[:10],
        'query': query,
        'filter_status': filter_status,
        'category_filter': category_filter,
        'all_categories': Content.CATEGORY_CHOICES,  # Pass category choices to template
        'statistics': {
            'total_users': CustomUser.objects.count(),
            'total_content': Content.objects.count(),
            'approved_content': Content.objects.filter(is_approved=True).count(),
            'pending_content': Content.objects.filter(is_approved=False).count(),
        },
        'content_ranking': content_ranking,  # Add voting statistics to context
        'performances': LivePerformance.objects.all(),
        'live_performances': live_performances,
        'vouchers_by_perf': {
            perf.id: perf.vouchers.all() for perf in LivePerformance.objects.all()
        },
    }

    return render(request, 'users/admin_dashboard.html', context)



def export_data(request):
    format_type = request.GET.get("format")  # Get format from request

    if format_type == "csv":
        return generate_csv()
    elif format_type == "pdf":
        return generate_pdf()
    else:
        return HttpResponse("Invalid format", status=400)


def generate_csv():
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="data.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Column1', 'Column2', 'Column3'])  # Header
    writer.writerow(['Data1', 'Data2', 'Data3'])  # Example row

    return response


def generate_pdf():
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="data.pdf"'

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # Generate logo as text with styling
    pdf.setFont("Helvetica-Bold", 20)
    pdf.drawCentredString(width / 2, height - 50, "Genre Genius")
    
    pdf.setFillColorRGB(1, 0.8, 0)  # Orange Gradient effect simulation
    pdf.rect((width / 2) - 50, height - 55, 100, 5, fill=True, stroke=False)  # Underline effect

    pdf.setFont("Helvetica", 12)
    pdf.drawString(100, height - 100, "Sample Data")
    
    pdf.save()
    buffer.seek(0)

    response.write(buffer.read())
    return response


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

    # Fetch content uploaded by each artist
    artists_with_content = []
    for artist in artists:
        content = Content.objects.filter(artist=artist)  # Fetch content for the artist
        artists_with_content.append({
            'artist': artist,
            'content': content,
        })


    # Pass the artists to the template
    context = {
        'content': content,
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

    # Artists can see all of their uploads, including pending admin approval.
    # Other users can only see approved content.
    artist_content = Content.objects.filter(artist=artist).order_by('-upload_date')
    if request.user != artist and not request.user.is_admin():
        artist_content = artist_content.filter(is_approved=True)

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

    badge = Badge.objects.filter(user=request.user).first()

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
        'badge': badge,
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

    # Get follower/following counts
    followers_count = Follow.objects.filter(following=user).count()
    following_count = Follow.objects.filter(follower=user).count()

    # Get followers and following users
    followers = user.followers.all().select_related('follower')  # Users following this user
    following = user.following.all().select_related('following')  # Users this user follows

    # Prepare context data
    context = {
        'profile_user': user,
        'is_following': is_following,
        'form': form,
        'followers_count': followers_count,
        'following_count': following_count,
        'followers': followers,
        'following': following,
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


@login_required
def toggle_content_voting(request, content_id, action):
    if not request.user.has_role(Role.ADMIN):
        return HttpResponseForbidden()
    
    content = get_object_or_404(Content, id=content_id)
    content.is_approved_for_voting = (action == 'approve')
    content.save()
    return redirect('admin_dashboard')


def voting_statistics(request):
    if not request.user.has_role(Role.ADMIN):
        return redirect('dashboard')

    content_ranking = Content.objects.annotate(
        total_points=Sum('votes__value'),
        total_votes=Count('votes'),
        badge_votes=Count('votes', filter=Q(votes__is_badge_vote=True))
    ).order_by('-total_points')

    context = {
        'content_ranking': content_ranking,
    }
    return render(request, 'users/voting_statistics.html', context)



def search_results(request):
    query = request.GET.get('q', '').strip()
    
    users, content = [], []

    if query:
        # Search for users (Check if users exist)
        users = CustomUser.objects.filter(
            Q(username__icontains=query) | 
            Q(email__icontains=query)
        )
        
        # Debugging output
        print("Query:", query)
        print("Users found:", users)  # Check if users are being retrieved
        
        # Search for content
        content = Content.objects.filter(
            Q(title__icontains=query) | 
            Q(description__icontains=query)
        )

    return render(request, 'users/search_results.html', {
        'query': query,
        'users': users,
        'content': content,
    })



from django.core.paginator import Paginator

@login_required
def get_announcements(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "User not authenticated"}, status=401)

    dismissed = DismissedAnnouncement.objects.filter(user=request.user).values_list("announcement_id", flat=True)
    announcements = Announcement.objects.exclude(id__in=dismissed).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
    ).order_by("-created_at").values("id", "title", "message")

    return JsonResponse({"announcements": list(announcements)})


@login_required
def dismiss_announcement(request, announcement_id):
    announcement = Announcement.objects.get(id=announcement_id)
    DismissedAnnouncement.objects.get_or_create(user=request.user, announcement=announcement)
    return JsonResponse({"status": "dismissed"})

@login_required
def delete_announcement(request, announcement_id):
    if not request.user.has_role(Role.ADMIN):
        return redirect('dashboard')

    announcement = get_object_or_404(Announcement, id=announcement_id)
    announcement.delete()
    messages.success(request, "Announcement deleted successfully.")
    return redirect('admin_dashboard')



def terms_and_conditions(request):
    terms = TermsAndConditions.objects.filter(is_active=True).first()
    
    # Safely check permissions for authenticated users
    can_manage = False
    if request.user.is_authenticated:
        can_manage = (request.user.has_perm('users.manage_terms') or 
                     (hasattr(request.user, 'is_admin') and request.user.is_admin()))
    
    context = {
        'terms': terms,
        'can_manage_terms': can_manage
    }
    return render(request, 'users/terms_and_conditions.html', context)

@login_required
@permission_required('app_name.manage_terms', raise_exception=True)
def manage_terms(request):
    # Add view for managing terms if needed
    pass


