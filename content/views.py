# content/views.py
# In content/views.py
from users.utils import send_notification_to_followers
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.forms import modelform_factory
from .models import Content, Vote, LivePerformance, ArtistUploadLimit, Comment, Badge, Voucher, Genre
from users.models import  OTP, CustomUser
from .forms import ContentUploadForm, CommentForm, StartLiveStreamForm, VoucherEntryForm
from django.db.models import Avg, Sum, Max
from django.views import View
from django.contrib.auth.models import User
from django.utils.timezone import now
from django.core.paginator import Paginator
from django.db.models import Count, Q
from datetime import timedelta
from users.utils import send_notification  # Ensure this is correctly imported
import random
from django.db.models import F
import string
from django.urls import reverse
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.core.mail import send_mail
from django.conf import settings
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils.timezone import now
from .forms import ContentUploadForm
from taggit.models import Tag
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

            
            # Send notifications to followers
            message = f"{request.user.username} just uploaded new content: {content.title}"
            send_notification_to_followers(request.user, message)

            messages.success(request, "Content uploaded successfully!")
            return redirect('artist_content', artist_id=request.user.id)

    else:
        form = ContentUploadForm()

    return render(request, 'content/upload.html', {'form': form})





@login_required
def add_comment(request, content_id):
    content = get_object_or_404(Content, id=content_id)

    if request.method == "POST":
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
            "comment_count": content.comments.count()  # Send updated comment count
        })

    return JsonResponse({"status": "error", "message": "Invalid request method."}, status=405)




@login_required
def reset_artist_upload_limit(request, artist_id):
    if not request.user.is_admin:  # Ensure only admins can reset
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




def list_content(request, content_id=None):
    """
    Display approved content with search and filtering.
    Fans can search by content title, description, or artist name.
    They can also filter by tags.
    """
    query = request.GET.get('q', '').strip()
    filter_tag = request.GET.get('tag', '').strip()
    selected_genre = request.GET.get('genre', '').strip()

    base_contents = Content.objects.select_related('artist', 'genre').prefetch_related('votes')

    if request.user.is_authenticated and request.user.is_artist():
        contents = base_contents.filter(Q(is_approved=True) | Q(artist=request.user)).order_by('-upload_date')
    else:
        contents = base_contents.filter(is_approved=True).order_by('-upload_date')

    if content_id:
        contents = contents.filter(id=content_id)

    # Search by title, description, or artist username
    if query:
        contents = contents.filter(
            Q(title__icontains=query) | 
            Q(description__icontains=query) | 
            Q(artist__username__icontains=query)
        )

    # Filter by tag if provided
    if filter_tag:
        contents = contents.filter(tags__name=filter_tag)

    if selected_genre:
        contents = contents.filter(genre__name__iexact=selected_genre)

    # Paginate results (10 per page)
    paginator = Paginator(contents, 10)
    page_number = request.GET.get('page')
    page_contents = paginator.get_page(page_number)

    popular_contents = (
        Content.objects.filter(is_approved=True)
        .select_related('artist', 'genre')
        .prefetch_related('votes')
        .annotate(total_votes=Count('votes'))
        .order_by('-total_votes', '-upload_date')[:8]
    )

    available_genres = (
        Genre.objects.filter(contents__is_approved=True)
        .order_by('name')
        .distinct()
    )

    return render(request, 'content/list.html', {
        'contents': page_contents,
        'query': query,
        'filter_tag': filter_tag,
        'selected_genre': selected_genre,
        'available_genres': available_genres,
        'popular_contents': popular_contents,
        'all_tags': Tag.objects.all(),
        'single_content': content_id is not None
    })






@login_required
def content_detail(request, content_id):
    """
    Display a single content item with detailed information.
    """
    content = get_object_or_404(Content, id=content_id)
    related_contents = Content.objects.filter(is_approved=True).exclude(id=content_id)[:4]  # Show 4 related items
    comments = Comment.objects.filter(content=content).order_by('-timestamp')  # Fetch comments for the content
    average_vote = Vote.objects.filter(content=content).aggregate(Avg('value'))['value__avg'] or 0  # Calculate average vote

    return render(request, 'content/detail.html', {
        'content': content,
        'related_contents': related_contents,
        'comments': comments,
        'average_vote': round(average_vote, 1),  # Round to 1 decimal place
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
            
            # Add user to viewers if not already there
            content.viewers.add(request.user)
            
            viewer_count = content.viewers.count()
            
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

    try:
        data = json.loads(request.body)
        vote_value = int(data.get('vote_value'))
        otp_code = data.get('otp_code', '').strip()
        voter_tag = data.get('voter_tag', '').strip()
        content = get_object_or_404(Content, id=content_id)

        if vote_value not in range(1, 9):
            return JsonResponse({'status': 'error', 'message': 'Invalid rank (1-8 only)'}, status=400)

        otp = OTP.objects.filter(
            user=request.user,
            otp_code=otp_code,
            is_active=True,
            remaining_votes__gt=0
        ).first()
        if not otp:
            return JsonResponse({'status': 'error', 'message': 'Invalid/expired OTP'}, status=403)

        existing_vote = Vote.objects.filter(fan=request.user, content__genre=content.genre, base_value=vote_value).exists()
        if existing_vote:
            return JsonResponse({'status': 'error', 'message': f'Rank {vote_value} already used in this genre'}, status=409)

        highest_previous_vote = Vote.objects.filter(fan=request.user, content__genre=content.genre).aggregate(Max('base_value'))['base_value__max'] or 9
        if vote_value > highest_previous_vote:
            return JsonResponse({'status': 'error', 'message': f'You must rank lower than or equal to {highest_previous_vote}'}, status=409)

        badge = getattr(request.user, 'badge', None)
        vote_multiplier = badge.vote_multiplier() if badge else 1
        calculated_value = vote_value * vote_multiplier

        vote, created = Vote.objects.update_or_create(
            content=content,
            fan=request.user,  
            defaults={
                'base_value': vote_value,
                'value': calculated_value,
                'otp_code': otp_code,
                'tag': voter_tag,
                'is_badge_vote': bool(badge)
            }
        )

        if not otp.use_vote():
            return JsonResponse({'status': 'error', 'message': 'OTP vote limit reached'}, status=403)
        assign_or_upgrade_badge(request, request.user.id)

        return JsonResponse({'status': 'success', 'message': f'Vote {vote_value} recorded!'})

    except Exception as e:
        logger.error(f"Error in vote_content: {str(e)}", exc_info=True)
        return JsonResponse({'status': 'error', 'message': f'Something went wrong: {str(e)}'}, status=500)



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
            assign_or_upgrade_badge(vote.fan)  # Upgrade badge for matching votes

@login_required
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
def toggle_content_approval(request, content_id, action):
    if not request.user.is_admin():
        messages.error(request, "You do not have permission to manage content approval.")
        return redirect('dashboard')

    content = get_object_or_404(Content, id=content_id)

    if action == "approve":
        if not content.is_approved:
            content.is_approved = True
            content.save()
            messages.success(request, f'Content "{content.title}" has been approved.')
    elif action == "disapprove":
        if content.is_approved:
            content.is_approved = False
            content.save()
            messages.success(request, f'Content "{content.title}" has been disapproved.')
    else:
        messages.error(request, "Invalid action.")
    
    return redirect('dashboard')






def recommend_content(request):
    """
    Recommend content based on tags and artist followers.
    """
    if not request.user.is_authenticated:
        return JsonResponse([])

    user_tags = request.user.tags.values_list('name', flat=True)

    recommendations = (
    Content.objects.filter(is_approved=True)
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
    # Add any context data you want to pass to the template
    context = {
        'featured_contents': Content.objects.filter(is_approved=True).order_by('-upload_date')[:6]  # Example: Show 6 featured contents
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

    return render(request, 'users/classify.html', {'form': form, 'content': content})







