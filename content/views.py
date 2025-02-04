# content/views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from .models import Content, Vote, LivePerformance, ArtistUploadLimit, Comment
from .forms import ContentUploadForm, CommentForm
from django.db.models import Avg
from django.views import View
from django.utils.timezone import now
from django.core.paginator import Paginator
from django.db.models import Count, Q
from datetime import timedelta
from users.utils import send_notification  # Ensure this is correctly imported
import random
from django.db.models import F
import string
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
import logging
import json

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
            content.save()
            form.save_m2m()  # Save tags or other many-to-many fields

            # Update uploads used if not suspended by admin
            if upload_limit and not upload_limit.suspended_by_admin:
                upload_limit.uploads_used += 1
                upload_limit.save()

            messages.success(request, "Content uploaded successfully!")
            return redirect('content_list')

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

    # Get only approved content
    contents = Content.objects.filter(is_approved=True).order_by('-upload_date')


    if content_id:
        # If content_id is provided, show only one content item
        contents = Content.objects.filter(id=content_id, is_approved=True)
    else:
        # Get all approved content
        contents = Content.objects.filter(is_approved=True).order_by('-upload_date')

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

    # Paginate results (10 per page)
    paginator = Paginator(contents, 10)
    page_number = request.GET.get('page')
    page_contents = paginator.get_page(page_number)

    return render(request, 'content/list.html', {
        'contents': page_contents,
        'query': query,  # Pass query back to template
        'filter_tag': filter_tag,
        'all_tags': Tag.objects.all(),
        'single_content': content_id is not None  # Flag for single content view
    })







def content_detail(request, content_id):
    """
    Display a single content item with detailed information.
    """
    content = get_object_or_404(Content, id=content_id, is_approved=True)
    related_contents = Content.objects.filter(is_approved=True).exclude(id=content_id)[:4]  # Show 4 related items
    comments = Comment.objects.filter(content=content).order_by('-timestamp')  # Fetch comments for the content
    average_vote = Vote.objects.filter(content=content).aggregate(Avg('value'))['value__avg'] or 0  # Calculate average vote

    return render(request, 'content/detail.html', {
        'content': content,
        'related_contents': related_contents,
        'comments': comments,
        'average_vote': round(average_vote, 1),  # Round to 1 decimal place
    })


def increment_views(request, content_id):
    """
    Increments the view count of a content item.
    """
    if request.method == "POST":
        logger.info(f"Incrementing views for content ID: {content_id}")
        content = get_object_or_404(Content, id=content_id)
        content.views = F('views') + 1
        content.save()
        content.refresh_from_db()  # Ensure updated value is fetched
        logger.info(f"Updated views for content ID: {content_id}. New views: {content.views}")
        return JsonResponse({"status": "success", "new_views": content.views})
    
    logger.error(f"Invalid request method for content ID: {content_id}")
    return JsonResponse({"status": "error", "message": "Invalid request method"}, status=400)

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
    """
    Starts a live stream and redirects the artist directly to the live room.
    """
    if not request.user.is_artist():
        messages.error(request, "You don't have permission to start a live stream.")
        return redirect('dashboard')

    # Automatically create a new live performance
    stream_key = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
    performance = LivePerformance.objects.create(
        title=f"{request.user.username}'s Live Stream",
        artist=request.user,
        start_time=now(),
        stream_key=stream_key,
        use_camera=True,
        is_active=True,
    )

    # Redirect directly to the live room
    return redirect('live_stream_room', room_name=performance.stream_key)


@login_required
def live_stream_room(request, room_name):
    """
    Render the live stream room with ZegoCloud integration.
    """
    performance = get_object_or_404(LivePerformance, stream_key=room_name, is_active=True)

    # Ensure only fans or the artist can join
    if not request.user.is_fan() and request.user != performance.artist:
        messages.error(request, "You do not have permission to join this live stream.")
        return redirect('dashboard')

    # Determine the user's role for ZegoCloud
    role = 'Host' if request.user == performance.artist else 'Audience'
    return render(request, 'content/live_stream_room.html', {
        'room_name': room_name,
        'role': role,
    })



@csrf_exempt
def vote_content(request, content_id):
    if not request.user.is_authenticated:
        return JsonResponse({'status': 'error', 'message': 'You must be logged in to vote.'}, status=403)

    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            vote_value = data.get('vote_value')

            if not vote_value or not (1 <= int(vote_value) <= 5):
                return JsonResponse({'status': 'error', 'message': 'Invalid vote value.'}, status=400)

            content = Content.objects.get(id=content_id)
            Vote.objects.update_or_create(
                content=content,
                fan=request.user,
                defaults={'value': int(vote_value), 'timestamp': now()},
            )

            return JsonResponse({'status': 'success', 'message': 'Vote submitted successfully!'})
        except Content.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Content not found.'}, status=404)
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    return JsonResponse({'status': 'error', 'message': 'Invalid request method.'}, status=400)


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




@login_required
def notifications(request):
    user_notifications = request.user.notifications.order_by('-created_at')
    return render(request, "users/notifications.html", {"notifications": user_notifications})



def home(request):
    """
    Renders the welcome page as the home page.
    """
    # Add any context data you want to pass to the template
    context = {
        'featured_contents': Content.objects.filter(is_approved=True).order_by('-upload_date')[:6]  # Example: Show 6 featured contents
    }
    return render(request, 'content/welcome.html', context)