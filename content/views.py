# content/views.py
# In content/views.py
from users.utils import send_notification_to_followers
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.forms import modelform_factory
from .models import Content, Vote, LivePerformance, ArtistUploadLimit, Comment, Badge, Voucher
from users.models import OTP, CustomUser, VotingTokenPolicy
from .forms import ContentUploadForm, CommentForm, StartLiveStreamForm, VoucherEntryForm
from django.db.models import Avg, Sum, Max
from django.views import View
from django.contrib.auth.models import User
from django.utils.timezone import now
from django.core.paginator import Paginator
from django.db.models import Count, Q, Case, When, IntegerField, Value
from datetime import timedelta
from users.utils import send_notification  # Ensure this is correctly imported
import random
from django.db.models import F
import string
from django.urls import reverse
from django.http import Http404, HttpResponseForbidden, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.core.mail import send_mail
from django.conf import settings
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils.timezone import now
from .forms import ContentUploadForm
from subscriptions.models import UserSubscription
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST
from django.middleware.csrf import get_token
import logging
import json
import uuid
from django.db import transaction
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

# Set up logging configuration
logger = logging.getLogger(__name__)


def public_content_queryset():
    return Content.objects.filter(is_approved=True, is_visible=True)


def can_view_content(user, content):
    if content.is_approved and content.is_visible:
        return True
    if not user.is_authenticated:
        return False
    return user.is_admin() or content.artist_id == user.id


def track_content_view(content, user):
    """
    Record a unique view for an authenticated user and return the latest count.
    """
    if not user.is_authenticated:
        return content.viewers.count()

    content.viewers.add(user)
    return content.viewers.count()


def get_up_next_contents(content, user=None, limit=4):
    """
    Return the ordered Up Next list without section metadata.
    """
    return get_up_next_sections(content, user=user, limit=limit)["all_items"]


def _empty_up_next_sections():
    return {
        "personalized": [],
        "same_creator": [],
        "related_creators": [],
        "fallback": [],
        "all_items": [],
    }


def _user_interest_profile(user, current_content, sample_size=50):
    profile = {
        "followed_artist_ids": set(),
        "genre_ids": set(),
        "tag_names": set(),
    }

    if not user or not user.is_authenticated:
        return profile

    profile["followed_artist_ids"] = set(
        user.following.values_list("following_id", flat=True)
    )

    interest_contents = (
        public_content_queryset().filter(Q(viewers=user) | Q(votes__fan=user))
        .exclude(id=current_content.id)
        .select_related("genre")
        .prefetch_related("tags")
        .distinct()
        .order_by("-upload_date")[:sample_size]
    )

    for item in interest_contents:
        if item.genre_id:
            profile["genre_ids"].add(item.genre_id)
        profile["tag_names"].update(item.tags.names())

    return profile


def _personalized_up_next_ids(base_queryset, content, user, limit):
    if limit <= 0:
        return []

    profile = _user_interest_profile(user, content)
    followed_artist_ids = list(profile["followed_artist_ids"])
    user_genre_ids = list(profile["genre_ids"])
    user_tag_names = list(profile["tag_names"])

    if not followed_artist_ids and not user_genre_ids and not user_tag_names:
        return []

    personalized_filter = Q()
    if followed_artist_ids:
        personalized_filter |= Q(artist_id__in=followed_artist_ids)
    if user_genre_ids:
        personalized_filter |= Q(genre_id__in=user_genre_ids)
    if user_tag_names:
        personalized_filter |= Q(tags__name__in=user_tag_names)

    current_tag_names = list(content.tags.names())
    followed_artist_match = (
        Case(
            When(artist_id__in=followed_artist_ids, then=1),
            default=0,
            output_field=IntegerField(),
        )
        if followed_artist_ids
        else Value(0, output_field=IntegerField())
    )
    user_genre_match = (
        Case(
            When(genre_id__in=user_genre_ids, then=1),
            default=0,
            output_field=IntegerField(),
        )
        if user_genre_ids
        else Value(0, output_field=IntegerField())
    )
    same_current_genre_match = (
        Case(
            When(genre_id=content.genre_id, then=1),
            default=0,
            output_field=IntegerField(),
        )
        if content.genre_id
        else Value(0, output_field=IntegerField())
    )
    interest_tag_count = (
        Count("tags", filter=Q(tags__name__in=user_tag_names), distinct=True)
        if user_tag_names
        else Value(0, output_field=IntegerField())
    )
    shared_tag_count = (
        Count("tags", filter=Q(tags__name__in=current_tag_names), distinct=True)
        if current_tag_names
        else Value(0, output_field=IntegerField())
    )

    return list(
        base_queryset.filter(personalized_filter)
        .annotate(
            followed_artist_match=followed_artist_match,
            user_genre_match=user_genre_match,
            same_current_genre_match=same_current_genre_match,
            interest_tag_count=interest_tag_count,
            shared_tag_count=shared_tag_count,
            vote_count=Count("votes", distinct=True),
            viewer_count=Count("viewers", distinct=True),
        )
        .order_by(
            "-followed_artist_match",
            "-user_genre_match",
            "-interest_tag_count",
            "-same_current_genre_match",
            "-shared_tag_count",
            "-vote_count",
            "-viewer_count",
            "-upload_date",
        )
        .distinct()
        .values_list("id", flat=True)[:limit]
    )


def get_up_next_sections(content, user=None, limit=4):
    """
    Return grouped "Up next" content for rendering a structured sidebar.
    Logged-in users first get recommendations from follows, viewed content,
    and voting history before the generic current-content fallbacks.
    """
    if limit <= 0:
        return _empty_up_next_sections()

    base_queryset = (
        public_content_queryset()
        .exclude(id=content.id)
        .select_related("artist", "genre")
        .prefetch_related("votes")
    )

    personalized_ids = _personalized_up_next_ids(base_queryset, content, user, limit)
    selected_ids = list(personalized_ids)
    remaining = limit - len(selected_ids)

    same_creator_ids = list(
        base_queryset.filter(artist=content.artist)
        .exclude(id__in=selected_ids)
        .order_by("-upload_date")
        .values_list("id", flat=True)[:remaining]
    )
    selected_ids.extend(same_creator_ids)

    content_tag_names = list(content.tags.names())
    related_creator_ids = []
    remaining = limit - len(selected_ids)
    if remaining > 0:
        related_filter = Q()
        if content.genre_id:
            related_filter |= Q(genre_id=content.genre_id)
        if content_tag_names:
            related_filter |= Q(tags__name__in=content_tag_names)

        if related_filter:
            same_genre_match = Case(
                When(genre_id=content.genre_id, then=1),
                default=0,
                output_field=IntegerField(),
            )
            related_creator_ids = list(
                base_queryset.filter(related_filter)
                .exclude(artist=content.artist)
                .exclude(id__in=selected_ids)
                .annotate(same_genre_match=same_genre_match)
                .annotate(shared_tag_count=Count("tags", filter=Q(tags__name__in=content_tag_names), distinct=True))
                .annotate(shared_vote_count=Count("votes", distinct=True))
                .order_by(
                    "-same_genre_match",
                    "-shared_tag_count",
                    "-shared_vote_count",
                    "-upload_date",
                )
                .distinct()
                .values_list("id", flat=True)[:remaining]
            )

    selected_ids.extend(related_creator_ids)
    fallback_ids = []
    remaining = limit - len(selected_ids)
    if remaining > 0:
        fallback_ids = list(
            base_queryset.exclude(id__in=selected_ids)
            .order_by("-upload_date")
            .values_list("id", flat=True)[:remaining]
        )
        selected_ids.extend(fallback_ids)

    items_by_id = {
        item.id: item
        for item in base_queryset.filter(id__in=selected_ids)
    }

    personalized_items = [items_by_id[item_id] for item_id in personalized_ids if item_id in items_by_id]
    same_creator_items = [items_by_id[item_id] for item_id in same_creator_ids if item_id in items_by_id]
    related_creator_items = [items_by_id[item_id] for item_id in related_creator_ids if item_id in items_by_id]
    fallback_items = [items_by_id[item_id] for item_id in fallback_ids if item_id in items_by_id]

    return {
        "personalized": personalized_items,
        "same_creator": same_creator_items,
        "related_creators": related_creator_items,
        "fallback": fallback_items,
        "all_items": personalized_items + same_creator_items + related_creator_items + fallback_items,
    }




@login_required
def upload_content(request):
    """
    Allows artists to upload content if they have sufficient quota.
    Displays an error message if the user lacks permission or exceeds their limit.
    """
    if not request.user.is_artist():
        messages.error(request, "You don't have permission to upload content.")
        return redirect('dashboard')

    # Retrieve the artist's upload limit
    upload_limit = ArtistUploadLimit.objects.filter(artist=request.user).first()

    if upload_limit and not upload_limit.has_upload_quota():  # Fixed method name
        messages.error(request, "You have reached your upload limit. Contact admin for assistance.")
        return redirect('dashboard')

    if request.method == 'POST':
        form = ContentUploadForm(request.POST, request.FILES)
        if form.is_valid():
            content = form.save(commit=False)
            content.artist = request.user
            content.is_approved = False  # Needs admin approval
            content.is_visible = True    # Visible to artist immediately
            content.save()
            form.save_m2m()  # Save tags or other many-to-many fields

            # Update uploads used if not suspended by admin
            if upload_limit and not upload_limit.suspended_by_admin:
                upload_limit.uploads_used += 1
                upload_limit.save()

            
            messages.success(request, "Content uploaded successfully and is pending review.")
            return redirect('artist_content', artist_id=request.user.id)

    else:
        form = ContentUploadForm()

    return render(request, 'content/upload.html', {'form': form})





@login_required
@require_POST
def add_comment(request, content_id):
    content = get_object_or_404(Content, id=content_id)
    if not can_view_content(request.user, content):
        return JsonResponse({"status": "error", "message": "Content is not available."}, status=404)

    text = request.POST.get("text", "").strip()

    if not text:
        return JsonResponse({"status": "error", "message": "Comment text cannot be empty."}, status=400)

    comment = Comment.objects.create(
        content=content,
        user=request.user,
        text=text,
        timestamp=now()
    )

    # Send notification to content owner (if commenter isn't the owner)
    if request.user != content.artist:
        send_notification(content.artist, f"{request.user.username} commented on your content: {content.title}")

    # Return JSON response with new comment count
    return JsonResponse({
        "status": "success",
        "comment": {
            "user": request.user.username,
            "user_id": request.user.id,
            "user_profile": request.user.get_profile_picture(),
            "text": comment.text,
            "timestamp": comment.timestamp.strftime("%b %d, %Y %H:%M"),
        },
        "comment_count": content.comments.count()
    })




@login_required
def reset_artist_upload_limit(request, artist_id):
    if not request.user.is_admin():  # Ensure only admins can reset
        messages.error(request, "You don't have permission to reset upload limits.")
        return redirect('dashboard')

    upload_limit = get_object_or_404(ArtistUploadLimit, artist_id=artist_id)
    
    # ✅ Reset upload count and limit
    upload_limit.uploads_used = 0  
    upload_limit.save()

    send_upload_reset_notification(upload_limit.artist)

    messages.success(request, f"{upload_limit.artist.username}'s upload limit has been reset.")
    return redirect('dashboard')




def send_upload_reset_notification(artist):
    """
    Notify the artist via email about the upload limit reset.
    """
    try:
        send_mail(
            subject="Your Upload Limit Has Been Reset",
            message="Your upload limit has been successfully reset. You can now upload new content.",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[artist.email],
        )
    except Exception as e:
        logger.error(f"Error sending email to {artist.email}: {e}")




def get_featured_contents(limit=50):
    return (
        public_content_queryset()
        .select_related('artist', 'genre')
        .prefetch_related('votes')
        .order_by('-upload_date')[:limit]
    )


def list_content(request, content_id=None):
    """
    Display the same featured content experience used on the home page.
    """
    return render(request, 'content/welcome.html', {
        'featured_contents': get_featured_contents(),
    })






@login_required
def content_detail(request, content_id):
    """
    Display a single content item with detailed information.
    """
    content = get_object_or_404(Content, id=content_id)
    if not can_view_content(request.user, content):
        messages.error(request, "This content is not available.")
        return redirect("content_list")

    track_content_view(content, request.user)
    up_next = get_up_next_sections(content, user=request.user, limit=4)
    comments = Comment.objects.filter(content=content).order_by('-timestamp')  # Fetch comments for the content
    average_vote = Vote.objects.filter(content=content).aggregate(Avg('value'))['value__avg'] or 0  # Calculate average vote
    voting_suspended = VotingTokenPolicy.voting_is_suspended()

    return render(request, 'content/detail.html', {
        'content': content,
        'related_contents': up_next['all_items'],
        'up_next_personalized': up_next['personalized'],
        'up_next_same_creator': up_next['same_creator'],
        'up_next_related_creators': up_next['related_creators'],
        'up_next_fallback': up_next['fallback'],
        'comments': comments,
        'average_vote': round(average_vote, 1),  # Round to 1 decimal place
        'tokens_paused': VotingTokenPolicy.tokens_are_paused() or request.user.has_free_pass,
        'voting_suspended': voting_suspended,
        'can_vote': (
            content.is_approved
            and content.is_visible
            and content.is_approved_for_voting
            and not voting_suspended
        ),
    })


@require_POST
@never_cache
def increment_views(request, content_id):
    """
    Tracks unique viewers of a content item.
    Returns JSON response with status and new viewer count.
    """
    try:
        if not request.user.is_authenticated:
            return JsonResponse({
                "status": "error",
                "message": "Authentication required to track viewers"
            }, status=401)

        with transaction.atomic():
            content = get_object_or_404(Content, id=content_id)
            if not can_view_content(request.user, content):
                return JsonResponse({
                    "status": "error",
                    "message": "Content is not available"
                }, status=404)
            viewer_count = track_content_view(content, request.user)
            
            logger.info(
                f"Viewer tracked - Content: {content_id}, "
                f"Total viewers: {viewer_count}, "
                f"User: {request.user.id}"
            )
            
            return JsonResponse({
                "status": "success", 
                "new_viewers": viewer_count
            })
            
    except Exception as e:
        logger.error(
            f"Viewer tracking failed - Content: {content_id}, "
            f"Error: {str(e)}"
        )
        return JsonResponse(
            {"status": "error", "message": "Internal server error"},
            status=500
        )

# Content Detail View
class ContentDetailView(View):
    """
    Handles displaying detailed content view.
    """
    def get(self, request, content_id):
        content = get_object_or_404(Content, id=content_id)
        return render(request, 'content_detail.html', {'content': content})



def live_stream_index(request):
    """
    List all live performances with pagination.
    """
    performances = LivePerformance.objects.filter(is_active=True, start_time__lte=now())
    paginator = Paginator(performances, 10)
    page_number = request.GET.get('page')
    page_performances = paginator.get_page(page_number)

    return render(request, "content/live_stream_index.html", {"performances": page_performances})


@login_required
def start_live_stream(request):
    if not request.user.is_artist():
        messages.error(request, "You don't have permission to start a live stream.")
        return redirect('dashboard')

    if request.method == "POST":
        form = StartLiveStreamForm(request.POST)
        if form.is_valid():
            stream_key = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
            performance = LivePerformance.objects.create(
            title=form.cleaned_data['title'],
            artist=request.user,
            start_time=now(),
            stream_key=stream_key,
            use_camera=True,
            is_active=True,
            is_restricted=form.cleaned_data['restrict_access'] 
        )


            # If restricted, admin will generate vouchers manually via dashboard
            if form.cleaned_data['restrict_access']:
                messages.info(request, "This stream is now voucher-restricted. Don't forget to generate vouchers!")

            return redirect('live_stream_room', room_name=performance.stream_key)
    else:
        form = StartLiveStreamForm()

    return render(request, "content/start_live_stream.html", {"form": form})



@login_required
def live_stream_room(request, room_name):
    """
    Render the live stream room with ZegoCloud integration.
    Enforces voucher if required.
    """
    performance = get_object_or_404(LivePerformance, stream_key=room_name, is_active=True)
    voucher_code = request.GET.get("voucher")

    # Artist always allowed
    if request.user == performance.artist:
        role = 'Host'
        return render(request, 'content/live_stream_room.html', {
            'room_name': room_name,
            'role': role,
        })

    # Check if stream is restricted (any active vouchers exist)
    is_restricted = performance.is_restricted


    # Restricted: enforce valid voucher
    if is_restricted:
        if voucher_code:
            try:
                voucher = Voucher.objects.get(code=voucher_code, performance=performance, is_used=False)
                # Optionally mark as used
                voucher.is_used = True
                voucher.used_by = request.user
                voucher.used_at = now()
                voucher.save()
            except Voucher.DoesNotExist:
                messages.error(request, "Invalid or expired voucher.")
                return redirect('voucher_entry', room_name=room_name)
        else:
            messages.error(request, "This stream requires a valid voucher.")
            return redirect('voucher_entry', room_name=room_name)
    else:
        # Public: only fans allowed
        if not request.user.is_fan():
            messages.error(request, "Only fans can join this live stream.")
            return redirect('dashboard')

    role = 'Audience'
    return render(request, 'content/live_stream_room.html', {
        'room_name': room_name,
        'role': role,
    })


@login_required
def voucher_entry(request, room_name):
    performance = get_object_or_404(LivePerformance, stream_key=room_name, is_active=True)
    form = VoucherEntryForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        code = form.cleaned_data['code']
        return redirect(f"{reverse('live_stream_room', args=[room_name])}?voucher={code}")

    return render(request, 'content/voucher_entry.html', {
        'form': form,
        'room_name': room_name,
        'performance': performance
    })


    




@require_POST
def vote_content(request, content_id):
    if not request.user.is_authenticated:
        return JsonResponse({'status': 'error', 'message': 'Authentication required'}, status=403)
    if getattr(request.user, "is_suspended_by_admin", False):
        return JsonResponse({'status': 'error', 'message': 'Your account is suspended.'}, status=403)

    def vote_error(message, status_code=200):
        return JsonResponse({'status': 'error', 'message': message}, status=status_code)

    try:
        if (request.content_type or "").startswith("application/json"):
            try:
                data = json.loads(request.body or "{}")
            except json.JSONDecodeError:
                return vote_error('Invalid vote payload', status_code=400)
        else:
            data = request.POST

        try:
            vote_value = int(data.get('vote_value'))
        except (TypeError, ValueError):
            return vote_error('Invalid rating (1-10 only)')

        otp_code = data.get('otp_code', '').strip()
        voter_tag = data.get('voter_tag', '').strip()
        content = get_object_or_404(Content, id=content_id)

        if not can_view_content(request.user, content):
            return vote_error('Content is not available', status_code=404)

        if not content.is_approved_for_voting:
            return vote_error('Voting is not open for this content')

        if VotingTokenPolicy.voting_is_suspended():
            return vote_error('Voting is suspended by admin')

        if vote_value not in range(1, 11):
            return vote_error('Invalid rating (1-10 only)')

        if not voter_tag:
            return vote_error('Voter tag is required')

        tokens_paused = VotingTokenPolicy.tokens_are_paused() or request.user.has_free_pass
        otp = None
        if not tokens_paused:
            otp = OTP.objects.filter(
                user=request.user,
                otp_code=otp_code,
                is_active=True,
                remaining_votes__gt=0
            ).first()
            if not otp:
                return vote_error('Invalid/expired OTP')

        active_vote_cutoff = now() - timedelta(days=1)
        active_votes = Vote.objects.filter(
            fan=request.user,
            content__genre=content.genre,
            timestamp__gte=active_vote_cutoff,
        )
        existing_vote = active_votes.filter(base_value=vote_value).exists()
        if existing_vote:
            return vote_error(f'Rank {vote_value} already used in this genre')

        highest_previous_vote = active_votes.aggregate(Max('base_value'))['base_value__max'] or 10
        if vote_value > highest_previous_vote:
            return vote_error(f'You must rank lower than or equal to {highest_previous_vote}')

        badge = getattr(request.user, 'badge', None)
        vote_multiplier = badge.vote_multiplier() if badge else 1
        calculated_value = vote_value * vote_multiplier

        chat_url = None
        with transaction.atomic():
            if otp:
                locked_otp = OTP.objects.select_for_update().filter(
                    pk=otp.pk,
                    user=request.user,
                    is_active=True,
                    remaining_votes__gt=0,
                ).first()
                if not locked_otp or not locked_otp.use_vote():
                    return vote_error('OTP vote limit reached')

            vote, created = Vote.objects.update_or_create(
                content=content,
                fan=request.user,
                defaults={
                    'base_value': vote_value,
                    'value': calculated_value,
                    'otp_code': "FREE" if tokens_paused else otp_code,
                    'tag': voter_tag,
                    'is_badge_vote': bool(badge)
                }
            )
            if not created:
                Vote.objects.filter(pk=vote.pk).update(timestamp=now())
                vote.refresh_from_db(fields=["timestamp"])

            assign_or_upgrade_badge_for_user(request.user)
            if content.artist_id != request.user.id and not request.user.is_admin():
                try:
                    from chatapp.services import record_match_rating

                    chat_result = record_match_rating(
                        rater=request.user,
                        rated=content.artist,
                        score=vote_value,
                        source_content=content,
                    )
                    if chat_result.get("thread"):
                        chat_url = reverse("chatapp:direct", args=[content.artist_id])
                except ValueError:
                    pass

        return JsonResponse(
            {
                'status': 'success',
                'message': f'Vote {vote_value} recorded!',
                'chat_url': chat_url,
                'inbox_url': reverse("chatapp:index") if chat_url else None,
            }
        )

    except Http404:
        raise
    except Exception as e:
        logger.error(f"Error in vote_content: {str(e)}", exc_info=True)
        return JsonResponse({'status': 'error', 'message': f'Something went wrong: {str(e)}'}, status=500)



def assign_or_upgrade_badge_for_user(user, level=None):
    badge, created = Badge.objects.get_or_create(user=user)

    if level is not None:
        badge.level = level
        badge.save()

    return badge


@staff_member_required
def assign_or_upgrade_badge(request, user_id, level=None):
    user = get_object_or_404(CustomUser, id=user_id)  # ✅ FIXED MODEL
    badge, created = Badge.objects.get_or_create(user=user)

    if level is not None:
        badge.level = level
        badge.save()

    return JsonResponse({
        "status": "success",
        "message": f"Badge updated for {user.username}"
    })



def calculate_final_ranking():
    # Calculate total points for each content item
    content_ranking = Content.objects.annotate(
        total_points=Sum('votes__value')
    ).order_by('-total_points')

    # Assign badges to fans whose votes match the final ranking
    for rank, content in enumerate(content_ranking, start=1):
        matching_votes = Vote.objects.filter(content=content, base_value=rank)
        for vote in matching_votes:
            assign_or_upgrade_badge_for_user(vote.fan)  # Upgrade badge for matching votes

@login_required
@require_POST
def delete_content(request, pk):
    content = get_object_or_404(Content, pk=pk)

    # Check if the logged-in user is the content's artist
    if content.artist == request.user:
        content.delete()
        messages.success(request, "Content deleted successfully.")
    else:
        messages.error(request, "You do not have permission to delete this content.")
    
    return redirect('content_list')  # Redirect to the content list page



@login_required
@require_POST
def toggle_content_approval(request, content_id, action):
    if not request.user.is_admin():
        messages.error(request, "You do not have permission to manage content approval.")
        return redirect('dashboard')

    content = get_object_or_404(Content, id=content_id)

    if action == "approve":
        if not content.is_approved:
            content.is_approved = True
            content.save()
            send_notification_to_followers(
                content.artist,
                f"{content.artist.username} just published new content: {content.title}",
            )
            messages.success(request, f'Content "{content.title}" has been approved.')
    elif action == "disapprove":
        if content.is_approved:
            content.is_approved = False
            content.save()
            messages.success(request, f'Content "{content.title}" has been disapproved.')
    else:
        messages.error(request, "Invalid action.")
    
    return redirect('dashboard')


@login_required
@require_POST
def toggle_content_visibility(request, content_id, action):
    if not request.user.is_admin():
        messages.error(request, "You do not have permission to manage content visibility.")
        return redirect('dashboard')

    content = get_object_or_404(Content, id=content_id)

    if action == "show":
        content.is_visible = True
        content.save(update_fields=["is_visible"])
        messages.success(request, f'Content "{content.title}" is now visible.')
    elif action == "hide":
        content.is_visible = False
        content.save(update_fields=["is_visible"])
        messages.success(request, f'Content "{content.title}" is now hidden.')
    else:
        messages.error(request, "Invalid action.")

    return redirect('admin_dashboard')






def recommend_content(request):
    """
    Recommend content based on tags and artist followers.
    """
    if not request.user.is_authenticated:
        return JsonResponse([])

    user_tags = request.user.tags.values_list('name', flat=True)

    recommendations = (
    public_content_queryset()
    .filter(Q(tags__name__in=user_tags))
    .annotate(vote_count=Count('votes'))
    .order_by('-vote_count')[:10]
    )


    return render(request, 'content/recommendations.html', {'contents': recommendations})




def watermark_video(video_file, username):
    """
    Adds a dynamic watermark with the viewer's username to the video.
    """
    import ffmpeg
    watermark_text = f'Watermarked for {username}'

    try:
        ffmpeg.input(video_file.path).output(
            video_file.path,
            vf=f"drawtext=text='{watermark_text}':fontsize=24:fontcolor=white:x=10:y=10"
        ).run()
    except Exception as e:
        raise ValueError(f"Watermarking failed: {e}")




def home(request):
    """
    Renders the welcome page as the home page.
    """
    context = {
        'featured_contents': get_featured_contents()
    }
    return render(request, 'content/welcome.html', context)



@login_required
@staff_member_required
def classify_content(request, content_id):
    content = get_object_or_404(Content, id=content_id)
    
    ContentClassificationForm = modelform_factory(Content, fields=['category'])
    
    if request.method == 'POST':
        form = ContentClassificationForm(request.POST, instance=content)
        if form.is_valid():
            form.save()
            messages.success(request, "Content classified successfully.")
            return redirect('content_list')
    else:
        form = ContentClassificationForm(instance=content)

    return render(request, 'content/classify.html', {'form': form, 'content': content})







