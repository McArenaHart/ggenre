from django.shortcuts import render, redirect, get_object_or_404, HttpResponse
from django.contrib.auth import login, authenticate, logout, get_user_model
from django.contrib.auth.decorators import login_required, permission_required
from django.views.decorators.http import require_POST
from django.db.models import F, Q
from django.contrib import messages
from .forms import UserRegistrationForm, LoginForm, ProfileUpdateForm, AnnouncementForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import UpdateView
from django.urls import reverse_lazy
from django.contrib.auth.tokens import default_token_generator
import random
from django.http import JsonResponse
from .models import Announcement, DismissedAnnouncement
import logging
import smtplib
import socket
import ssl
import time
from django.db.models import Avg, Sum, Count, Max
from django.db.models.functions import Coalesce
from django.core.mail import send_mail, BadHeaderError
from django.core.cache import cache
from django.utils.timezone import now
from datetime import timedelta
from .models import CustomUser, Role, Follow, OTP, TermsAndConditions, VotingTokenPolicy
from content.models import Content, Comment, Badge, Voucher
from subscriptions.models import UserSubscription
from content.models import ArtistUploadLimit, LivePerformance
from chatapp.models import AdminChatThread, PeerChatThread
from chatapp.services import (
    allow_peer_chat_by_admin,
    reset_content_rating_chat_access,
    revoke_admin_peer_chat,
)
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Notification
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


def get_content_ranking_queryset():
    return Content.objects.annotate(
        total_points=Coalesce(Sum("votes__value"), 0),
        total_votes=Count("votes"),
        badge_votes=Count("votes", filter=Q(votes__is_badge_vote=True)),
    ).order_by("-total_points", "-total_votes", "-upload_date")


# Utility function for role-based redirection
def role_based_redirect(user):
    if user.is_admin():
        return redirect("admin_dashboard")
    elif user.is_artist():
        return redirect("artist_dashboard")
    elif user.is_fan():
        return redirect("fan_dashboard")
    return redirect("dashboard")


CustomUser = get_user_model()  # Ensure correct user model


REGISTER_THROTTLE_SCOPE = "register"
LOGIN_THROTTLE_SCOPE = "login"
OTP_DISABLED_MESSAGE = "OTP is disabled. Please log in with password."


def _positive_int(value, default):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _deliver_otp_admin_contact(user, admin_user, otp, action_label):
    thread, created = AdminChatThread.objects.get_or_create(
        admin=admin_user,
        user=user,
        defaults={
            "user_unread_count": 1,
            "last_contact_at": timezone.now(),
        },
    )
    if not created:
        AdminChatThread.objects.filter(pk=thread.pk).update(
            user_unread_count=F("user_unread_count") + 1,
            last_contact_at=timezone.now(),
        )
    Notification.objects.create(
        user=user,
        message=(
            f"Admin {action_label} your voting OTP: {otp.otp_code} "
            f"({otp.remaining_votes} vote(s) available)."
        ),
    )


def _apply_otp_management_action(user, admin_user, action, vote_count, regenerate_code=False):
    otp, _ = OTP.objects.get_or_create(
        user=user,
        defaults={
            "otp_code": generate_otp(),
            "remaining_votes": 0,
            "is_active": True,
        },
    )

    generated_code = None
    should_deliver = False
    action_label = "updated"
    if action == "grant":
        otp.reset_votes(votes=vote_count, regenerate_code=generate_otp())
        generated_code = otp.otp_code
        should_deliver = True
        action_label = "generated"
    elif action == "extend":
        otp.grant_votes(votes=vote_count)
        generated_code = otp.otp_code
        should_deliver = True
        action_label = "extended"
    elif action == "cancel":
        otp.cancel_access()
    elif action == "reset":
        new_code = generate_otp() if regenerate_code else None
        otp.reset_votes(votes=vote_count, regenerate_code=new_code)
        generated_code = otp.otp_code
        should_deliver = True
        action_label = "reset"
    else:
        raise ValueError("Invalid OTP action.")

    if should_deliver:
        _deliver_otp_admin_contact(user, admin_user, otp, action_label)
    return otp, generated_code


def _auth_throttle_config(scope):
    window_seconds = _positive_int(
        getattr(settings, "AUTH_THROTTLE_WINDOW_SECONDS", 300), 300
    )
    if scope == REGISTER_THROTTLE_SCOPE:
        limit = _positive_int(getattr(settings, "AUTH_REGISTER_MAX_ATTEMPTS", 5), 5)
    else:
        limit = _positive_int(getattr(settings, "AUTH_LOGIN_MAX_ATTEMPTS", 10), 10)
    return limit, window_seconds


def _client_identifier(request):
    forwarded_for = (
        (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
    )
    if forwarded_for:
        return forwarded_for

    remote_addr = (request.META.get("REMOTE_ADDR") or "").strip()
    if remote_addr:
        return remote_addr

    return "unknown"


def _auth_throttle_key(request, scope):
    return f"auth-throttle:{scope}:{_client_identifier(request)}"


def _is_auth_throttled(request, scope):
    limit, _ = _auth_throttle_config(scope)
    attempts = cache.get(_auth_throttle_key(request, scope), 0) or 0
    return _positive_int(attempts, 0) >= limit


def _record_auth_attempt(request, scope):
    _, window_seconds = _auth_throttle_config(scope)
    key = _auth_throttle_key(request, scope)
    if cache.add(key, 1, timeout=window_seconds):
        return
    try:
        cache.incr(key)
    except Exception:
        attempts = _positive_int(cache.get(key, 0), 0) + 1
        cache.set(key, attempts, timeout=window_seconds)


def _reset_auth_throttle(request, scope):
    cache.delete(_auth_throttle_key(request, scope))


def _throttled_form_response(request, form, message, template_name):
    messages.error(request, message)
    response = render(request, template_name, {"form": form})
    response.status_code = 429
    return response


def _redirect_otp_disabled(request):
    messages.info(request, OTP_DISABLED_MESSAGE)
    return redirect("login")


# Generate OTP
def generate_otp():
    return str(random.randint(100000, 999999))


def send_otp_email(user, otp):
    subject = "Your OTP Code"
    message = (
        f"Hello {user.username},\n\n"
        f"Your OTP code is: {otp}\n\n"
        "Use this code to verify your account. It expires in 5 minutes."
    )
    email_backend = getattr(settings, "EMAIL_BACKEND", "")

    if not user.email:
        logger.error("OTP email skipped because user %s has no email.", user.pk)
        return False

    if email_backend == "django.core.mail.backends.console.EmailBackend":
        logger.warning(
            "OTP email for user %s is using console backend (no real delivery).",
            user.pk,
        )

    max_attempts = max(1, int(getattr(settings, "OTP_EMAIL_MAX_RETRIES", 3)))
    retry_delay_seconds = float(getattr(settings, "OTP_EMAIL_RETRY_DELAY_SECONDS", 1.5))
    transient_errors = (
        TimeoutError,
        socket.timeout,
        ssl.SSLError,
        smtplib.SMTPConnectError,
        smtplib.SMTPServerDisconnected,
    )

    for attempt in range(1, max_attempts + 1):
        try:
            sent_count = send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                fail_silently=False,
            )
            if sent_count != 1:
                logger.error(
                    "OTP email send_mail returned %s for user %s via %s.",
                    sent_count,
                    user.pk,
                    email_backend,
                )
                return False

            logger.info(
                "OTP email sent to user %s (%s) via %s.",
                user.pk,
                user.email,
                email_backend,
            )
            return True
        except transient_errors as e:
            if attempt < max_attempts:
                logger.warning(
                    "Transient OTP email failure for user %s (attempt %s/%s): %s. Retrying...",
                    user.pk,
                    attempt,
                    max_attempts,
                    e,
                )
                time.sleep(retry_delay_seconds * attempt)
                continue

            logger.exception(
                "Failed to send OTP email to user %s via %s after %s attempts: %s",
                user.pk,
                email_backend,
                max_attempts,
                e,
            )
            return False
        except BadHeaderError:
            logger.exception(
                "Invalid header while sending OTP email to user %s.", user.pk
            )
            return False
        except Exception as e:
            logger.exception(
                "Failed to send OTP email to user %s via %s: %s",
                user.pk,
                email_backend,
                e,
            )
            return False


def register(request):
    if request.method == "POST":
        form = UserRegistrationForm(request.POST)
        if _is_auth_throttled(request, REGISTER_THROTTLE_SCOPE):
            return _throttled_form_response(
                request,
                form,
                "Too many registration attempts. Please try again later.",
                "users/register.html",
            )

        if (request.POST.get("website") or "").strip():
            _record_auth_attempt(request, REGISTER_THROTTLE_SCOPE)
            messages.error(request, "Registration failed. Please try again.")
            response = render(request, "users/register.html", {"form": form})
            response.status_code = 400
            return response

        if form.is_valid():
            user = form.save(commit=False)
            user.is_active = True
            user.save()
            _reset_auth_throttle(request, REGISTER_THROTTLE_SCOPE)
            messages.success(request, "Account created successfully. Please sign in.")
            return redirect("login")

        _record_auth_attempt(request, REGISTER_THROTTLE_SCOPE)
    else:
        form = UserRegistrationForm()

    return render(request, "users/register.html", {"form": form})


def verify_otp(request, user_id):
    return _redirect_otp_disabled(request)


def resend_otp(request, user_id):
    return _redirect_otp_disabled(request)


# User Login View
def login_view(request):
    if request.method == "POST":
        form = LoginForm(data=request.POST)
        if _is_auth_throttled(request, LOGIN_THROTTLE_SCOPE):
            return _throttled_form_response(
                request,
                form,
                "Too many login attempts. Please try again later.",
                "users/login.html",
            )

        if form.is_valid():
            user = form.get_user()
            if user.is_suspended_by_admin and not user.is_admin():
                _record_auth_attempt(request, LOGIN_THROTTLE_SCOPE)
                messages.error(request, "Your account is suspended. Contact support for access.")
                return render(request, "users/login.html", {"form": form})
            login(request, user)
            _reset_auth_throttle(request, LOGIN_THROTTLE_SCOPE)
            next_url = request.GET.get("next")
            return redirect(next_url) if next_url else role_based_redirect(user)

        _record_auth_attempt(request, LOGIN_THROTTLE_SCOPE)
        messages.error(request, "Invalid username or password.")
    else:
        form = LoginForm()
    return render(request, "users/login.html", {"form": form})


def logout_view(request):
    logout(request)
    messages.success(request, "You have been logged out successfully.")
    return redirect("login")


@login_required
def admin_dashboard(request):
    if not request.user.has_role(Role.ADMIN):
        return redirect("dashboard")

    # Admin-specific data
    fans = CustomUser.objects.filter(role=Role.FAN).order_by("username")
    managed_users = CustomUser.objects.exclude(role=Role.ADMIN).order_by("role", "username")
    otp_users = managed_users.filter(is_active=True, is_suspended_by_admin=False)
    generated_otp = None  # Store OTP to display in template
    generated_voucher = None  # Store OTP to display in template
    voting_token_policy = VotingTokenPolicy.current()

    # Fetch announcements for admin review
    announcements = Announcement.objects.all().order_by("-created_at")

    # Handle Announcement POST request
    if request.method == "POST" and request.POST.get("action") == "create_announcement":
        form = AnnouncementForm(request.POST)
        if form.is_valid():
            announcement = form.save(commit=False)
            announcement.created_by = request.user
            announcement.save()
            messages.success(request, "Announcement posted successfully!")
            return redirect("admin_dashboard")
        else:
            messages.error(request, "Failed to create announcement.")
    else:
        form = AnnouncementForm()

    # Initialize content_ranking with an empty queryset
    content_ranking = Content.objects.none()

    # Calculate voting statistics for display, even if no form is submitted
    try:
        content_ranking = get_content_ranking_queryset()
    except Exception as e:
        logger.error(f"Error calculating voting statistics: {str(e)}")
        messages.error(
            request, "An error occurred while calculating voting statistics."
        )

    # Fetch artists and recent uploads
    artists = ArtistUploadLimit.objects.select_related("artist").all()
    recent_uploads = Content.objects.all()
    live_performances = LivePerformance.objects.all().order_by("-start_time")

    # Apply filters for recent_uploads
    query = request.GET.get("q", "")
    filter_status = request.GET.get("status", "all")
    category_filter = request.GET.get("category", "")

    if query:
        recent_uploads = recent_uploads.filter(
            Q(title__icontains=query) | Q(artist__username__icontains=query)
        )
    if filter_status == "approved":
        recent_uploads = recent_uploads.filter(is_approved=True)
    elif filter_status == "pending":
        recent_uploads = recent_uploads.filter(is_approved=False)
    if category_filter:
        recent_uploads = recent_uploads.filter(category=category_filter)

    # Handle POST requests
    if request.method == "POST":
        action = request.POST.get("action")
        content_ids = request.POST.getlist("content_ids")
        artist_ids = request.POST.getlist("artist_ids")
        category = request.POST.get("category")

        if action == "approve_for_voting" and content_ids:
            Content.objects.filter(id__in=content_ids).update(
                is_approved_for_voting=True
            )
            messages.success(
                request, f"Approved {len(content_ids)} content items for voting."
            )
        elif action == "disapprove_for_voting" and content_ids:
            Content.objects.filter(id__in=content_ids).update(
                is_approved_for_voting=False
            )
            messages.success(
                request, f"Disapproved {len(content_ids)} content items for voting."
            )
        elif action == "reset_content_votes" and content_ids:
            contents = Content.objects.filter(id__in=content_ids)
            vote_count = Vote.objects.filter(content__in=contents).delete()[0]
            rating_count = 0
            for content in contents:
                rating_count += reset_content_rating_chat_access(content)
            messages.success(
                request,
                (
                    f"Reset {vote_count} vote(s) and {rating_count} chat unlock(s) "
                    "for selected content."
                ),
            )

        if action == "approve" and content_ids:
            Content.objects.filter(id__in=content_ids).update(is_approved=True)
            messages.success(request, f"Approved {len(content_ids)} content items.")
        elif action == "disapprove" and content_ids:
            Content.objects.filter(id__in=content_ids).update(is_approved=False)
            messages.success(request, f"Disapproved {len(content_ids)} content items.")
        elif action == "reset_limit" and artist_ids:
            artist_limits = ArtistUploadLimit.objects.filter(artist_id__in=artist_ids)
            for limit in artist_limits:
                limit.reset_limit()  # This will now work
            messages.success(
                request, f"Reset upload limits for {len(artist_limits)} artist(s)."
            )
        elif action == "assign_category" and content_ids and category:
            Content.objects.filter(id__in=content_ids).update(category=category)
            messages.success(
                request,
                f"Assigned category '{category}' to {len(content_ids)} content items.",
            )

    # Handle OTP access controls
    if request.method == "POST" and request.POST.get("token_policy_action"):
        token_policy_action = request.POST.get("token_policy_action")
        if token_policy_action == "pause":
            voting_token_policy.tokens_paused = True
            voting_token_policy.updated_by = request.user
            voting_token_policy.save(update_fields=["tokens_paused", "updated_by", "updated_at"])
            messages.success(request, "Voting tokens paused. Fans can vote without OTP codes.")
        elif token_policy_action == "resume":
            voting_token_policy.tokens_paused = False
            voting_token_policy.updated_by = request.user
            voting_token_policy.save(update_fields=["tokens_paused", "updated_by", "updated_at"])
            messages.success(request, "Voting tokens resumed. Fans must use OTP codes to vote.")
        elif token_policy_action == "suspend_voting":
            voting_token_policy.voting_suspended = True
            voting_token_policy.updated_by = request.user
            voting_token_policy.save(update_fields=["voting_suspended", "updated_by", "updated_at"])
            messages.warning(request, "Voting suspended. Fans cannot vote until voting is resumed.")
        elif token_policy_action == "resume_voting":
            voting_token_policy.voting_suspended = False
            voting_token_policy.updated_by = request.user
            voting_token_policy.save(update_fields=["voting_suspended", "updated_by", "updated_at"])
            messages.success(request, "Voting resumed.")
        elif token_policy_action == "message_retention":
            try:
                retention_hours = int(request.POST.get("message_retention_hours", 24))
            except (TypeError, ValueError):
                retention_hours = 24
            retention_hours = max(1, min(retention_hours, 168))
            voting_token_policy.message_retention_hours = retention_hours
            voting_token_policy.updated_by = request.user
            voting_token_policy.save(
                update_fields=["message_retention_hours", "updated_by", "updated_at"]
            )
            messages.success(
                request,
                f"Ephemeral chat messages will remain in browser storage for {retention_hours} hour(s).",
            )
        else:
            messages.error(request, "Invalid token policy action.")
        return redirect("admin_dashboard")

    if request.method == "POST" and request.POST.get("user_access_action"):
        access_action = request.POST.get("user_access_action")
        user = get_object_or_404(
            CustomUser.objects.exclude(role=Role.ADMIN),
            id=request.POST.get("user_id"),
        )

        if access_action == "grant_free_pass":
            user.has_free_pass = True
            user.save(update_fields=["has_free_pass"])
            messages.success(request, f"Free pass granted to {user.username}.")
        elif access_action == "revoke_free_pass":
            user.has_free_pass = False
            user.save(update_fields=["has_free_pass"])
            messages.success(request, f"Free pass revoked for {user.username}.")
        elif access_action == "suspend":
            user.is_suspended_by_admin = True
            user.save(update_fields=["is_suspended_by_admin"])
            messages.warning(request, f"{user.username} has been suspended.")
        elif access_action == "reinstate":
            user.is_suspended_by_admin = False
            user.save(update_fields=["is_suspended_by_admin"])
            messages.success(request, f"{user.username} has been reinstated.")
        else:
            messages.error(request, "Invalid user access action.")

        return redirect("admin_dashboard")

    if request.method == "POST" and request.POST.get("peer_chat_action"):
        peer_chat_action = request.POST.get("peer_chat_action")
        first_user = get_object_or_404(
            CustomUser.objects.exclude(role=Role.ADMIN),
            id=request.POST.get("first_user_id"),
        )
        second_user = get_object_or_404(
            CustomUser.objects.exclude(role=Role.ADMIN),
            id=request.POST.get("second_user_id"),
        )

        try:
            if peer_chat_action == "allow":
                allow_peer_chat_by_admin(first_user, second_user, request.user)
                messages.success(
                    request,
                    f"Chat unlocked for {first_user.username} and {second_user.username}.",
                )
            elif peer_chat_action == "revoke":
                revoke_admin_peer_chat(first_user, second_user)
                messages.warning(
                    request,
                    (
                        f"Admin chat override revoked for {first_user.username} "
                        f"and {second_user.username}."
                    ),
                )
            else:
                messages.error(request, "Invalid peer chat action.")
        except ValueError as exc:
            messages.error(request, str(exc))

        return redirect("admin_dashboard")

    if request.method == "POST" and request.POST.get("artist_limit_action"):
        limit = get_object_or_404(
            ArtistUploadLimit.objects.select_related("artist"),
            artist_id=request.POST.get("artist_id"),
        )
        limit_action = request.POST.get("artist_limit_action")

        if limit_action == "suspend_uploads":
            limit.suspended_by_admin = True
            limit.save(update_fields=["suspended_by_admin"])
            messages.warning(request, f"Uploads suspended for {limit.artist.username}.")
        elif limit_action == "reinstate_uploads":
            limit.suspended_by_admin = False
            limit.save(update_fields=["suspended_by_admin"])
            messages.success(request, f"Uploads reinstated for {limit.artist.username}.")
        else:
            messages.error(request, "Invalid artist upload action.")

        return redirect("admin_dashboard")

    # Handle OTP access controls
    if request.method == "POST" and request.POST.get("otp_action"):
        otp_action = request.POST.get("otp_action")
        user_id = request.POST.get("user_id")
        vote_count_raw = request.POST.get("vote_count", "1")
        regenerate_code = request.POST.get("regenerate_code") == "1"

        try:
            vote_count = max(1, int(vote_count_raw))
        except (TypeError, ValueError):
            vote_count = 1

        otp_user = get_object_or_404(otp_users, id=user_id)

        try:
            otp, generated_otp = _apply_otp_management_action(
                user=otp_user,
                admin_user=request.user,
                action=otp_action,
                vote_count=vote_count,
                regenerate_code=regenerate_code,
            )
        except ValueError:
            messages.error(request, "Invalid OTP action.")
            return redirect("admin_dashboard")

        if otp_action == "cancel":
            messages.warning(request, f"Cancelled OTP access for {otp_user.username}.")
        else:
            messages.success(
                request,
                (
                    f"OTP {otp_action} applied to {otp_user.username}: "
                    f"{otp.otp_code} with {otp.remaining_votes} vote(s)."
                ),
            )

        return redirect("admin_dashboard")

    if request.method == "POST" and request.POST.get("bulk_otp_action"):
        bulk_action = request.POST.get("bulk_otp_action")
        selected_ids = request.POST.getlist("bulk_user_ids")
        vote_count = _positive_int(request.POST.get("bulk_vote_count"), 1)
        regenerate_code = request.POST.get("bulk_regenerate_code") == "1"
        selected_users = list(otp_users.filter(id__in=selected_ids))

        if not selected_users:
            messages.error(request, "Select at least one active non-admin user.")
            return redirect("admin_dashboard")

        updated_count = 0
        for selected_user in selected_users:
            try:
                _apply_otp_management_action(
                    user=selected_user,
                    admin_user=request.user,
                    action=bulk_action,
                    vote_count=vote_count,
                    regenerate_code=regenerate_code,
                )
                updated_count += 1
            except ValueError:
                messages.error(request, "Invalid bulk OTP action.")
                return redirect("admin_dashboard")

        messages.success(
            request,
            f"Bulk OTP {bulk_action} completed for {updated_count} user(s).",
        )
        return redirect("admin_dashboard")

    if request.method == "POST" and "generate_voucher" in request.POST:
        user_id = request.POST.get("user_id")
        performance_id = request.POST.get("performance_id")
        user = get_object_or_404(CustomUser, id=user_id)
        performance = get_object_or_404(LivePerformance, id=performance_id)
        code = generate_otp()
        Voucher.objects.create(
            code=code, performance=performance, created_by=request.user
        )
        messages.success(request, f"Voucher generated for {user.username}: {code}")
        generated_voucher = code

    # Handle Badge Assignment and Removal
    if request.method == "POST" and (
        "assign_badge" in request.POST or "remove_badge" in request.POST
    ):
        user_id = request.POST.get("user_id")

        if not user_id:
            messages.error(request, "No user selected.")
            return redirect("admin_dashboard")

        fan = get_object_or_404(CustomUser, id=user_id)

        if "assign_badge" in request.POST:
            badge_level = int(request.POST.get("badge_level", 1))
            badge, created = Badge.objects.get_or_create(user=fan)
            badge.level = badge_level
            badge.save()
            messages.success(
                request, f"Badge level {badge_level} assigned to {fan.username}."
            )

        elif "remove_badge" in request.POST:
            deleted, _ = Badge.objects.filter(user=fan).delete()
            if deleted:
                messages.success(request, f"Badge removed from {fan.username}.")
            else:
                messages.warning(
                    request, f"{fan.username} does not have a badge to remove."
                )

    otp_by_user = {
        otp.user_id: otp
        for otp in OTP.objects.filter(user__in=otp_users).select_related("user")
    }
    otp_user_statuses = [{"user": user, "otp": otp_by_user.get(user.id)} for user in otp_users]

    # Prepare context
    recent_badge_votes = Vote.objects.filter(is_badge_vote=True).select_related('fan', 'content').order_by('-timestamp')[:10]

    context = {
        "announcements": announcements,
        "artists": artists,
        "fans": fans,
        "otp_users": otp_users,
        "managed_users": managed_users,
        "peer_chat_overrides": PeerChatThread.objects.filter(
            admin_approved=True,
        ).select_related("user_one", "user_two", "approved_by"),
        "generated_otp": generated_otp,
        "fan_otp_statuses": [{"fan": fan, "otp": otp_by_user.get(fan.id)} for fan in fans],
        "otp_user_statuses": otp_user_statuses,
        "generated_voucher": generated_voucher,
        "voting_token_policy": voting_token_policy,
        "recent_uploads": recent_uploads.order_by("-upload_date")[:10],
        "query": query,
        "filter_status": filter_status,
        "category_filter": category_filter,
        "all_categories": Content.CATEGORY_CHOICES,  # Pass category choices to template
        "statistics": {
            "total_users": CustomUser.objects.count(),
            "total_content": Content.objects.count(),
            "approved_content": Content.objects.filter(is_approved=True).count(),
            "pending_content": Content.objects.filter(is_approved=False).count(),
        },
        "content_ranking": content_ranking,  # Add voting statistics to context
        "recent_badge_votes": recent_badge_votes,
        "performances": LivePerformance.objects.all(),
        "live_performances": live_performances,
        "vouchers_by_perf": {
            perf.id: perf.vouchers.all() for perf in LivePerformance.objects.all()
        },
    }

    return render(request, "users/admin_dashboard.html", context)


def export_data(request):
    format_type = request.GET.get("format")  # Get format from request

    if format_type == "csv":
        return generate_csv()
    elif format_type == "pdf":
        return generate_pdf()
    else:
        return HttpResponse("Invalid format", status=400)


def generate_csv():
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="data.csv"'

    writer = csv.writer(response)
    writer.writerow(["Column1", "Column2", "Column3"])  # Header
    writer.writerow(["Data1", "Data2", "Data3"])  # Example row

    return response


def generate_pdf():
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="data.pdf"'

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # Generate logo as text with styling
    pdf.setFont("Helvetica-Bold", 20)
    pdf.drawCentredString(width / 2, height - 50, "Genre Genius")

    pdf.setFillColorRGB(1, 0.8, 0)  # Orange Gradient effect simulation
    pdf.rect(
        (width / 2) - 50, height - 55, 100, 5, fill=True, stroke=False
    )  # Underline effect

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
        return redirect("dashboard")

    artist = request.user
    upload_limit, _ = ArtistUploadLimit.objects.get_or_create(artist=artist)
    context = {
        "total_uploads": Content.objects.filter(artist=artist).count(),
        "approved_content": Content.objects.filter(
            artist=artist, is_approved=True
        ).count(),
        "pending_content": Content.objects.filter(
            artist=artist, is_approved=False
        ).count(),
        "remaining_slots": max(
            0, upload_limit.upload_limit - upload_limit.uploads_used
        ),
        "upload_limit": upload_limit.upload_limit,
    }
    return render(request, "users/artist_dashboard.html", context)


@login_required
def artist_list(request):
    """
    View to display a list of all artists.
    """
    public_content = Q(content__is_approved=True, content__is_visible=True)
    artists = (
        CustomUser.objects.filter(role=Role.ARTIST)
        .annotate(
            public_upload_count=Count("content", filter=public_content, distinct=True),
            average_rating=Avg("content__votes__base_value", filter=public_content),
            comment_count=Count("content__comments", filter=public_content, distinct=True),
            follower_count=Count("followers", distinct=True),
            latest_upload_at=Max("content__upload_date", filter=public_content),
        )
        .order_by("username")
    )

    context = {
        "artists": artists,
    }
    return render(request, "users/artist_list.html", context)


@login_required
def artist_content(request, artist_id):
    """
    View to display the content of a specific artist.
    """
    # Fetch the artist or return a 404 error if not found
    artist = get_object_or_404(CustomUser, id=artist_id, role=Role.ARTIST)

    # Artists can see all of their uploads, including pending admin approval.
    # Other users can only see approved content.
    artist_content = Content.objects.filter(artist=artist).order_by("-upload_date")
    if request.user != artist and not request.user.is_admin():
        artist_content = artist_content.filter(is_approved=True, is_visible=True)

    # Pass the artist and their content to the template
    context = {
        "artist": artist,
        "artist_content": artist_content,
    }
    return render(request, "users/artist_content.html", context)


# Fan Dashboard
@login_required
def fan_dashboard(request):
    if not request.user.has_role(Role.FAN):
        return redirect("dashboard")

    fan = request.user
    context = {
        "total_votes": fan.user_votes.count(),
        "voted_content": fan.user_votes.select_related("content").order_by(
            "-timestamp"
        )[:10],
    }
    return render(request, "users/fan_dashboard.html", context)


# Unified Dashboard Redirect
@login_required
def dashboard(request):
    return role_based_redirect(request.user)


def _profile_context(profile_user, viewer, form):
    followers = profile_user.followers.all().select_related("follower")
    following = profile_user.following.all().select_related("following")

    context = {
        "profile_user": profile_user,
        "is_following": Follow.objects.filter(
            follower=viewer, following=profile_user
        ).exists(),
        "form": form,
        "followers_count": followers.count(),
        "following_count": following.count(),
        "followers": followers,
        "following": following,
        "subscription_status": "Inactive",
        "upload_limit": 0,
        "vote_limit": 0,
        "badge": Badge.objects.filter(user=profile_user).first(),
    }

    if profile_user == viewer:
        user_subscription = UserSubscription.objects.filter(user=profile_user).first()
        if user_subscription and user_subscription.is_active:
            context.update(
                {
                    "subscription_status": "Active",
                    "upload_limit": user_subscription.upload_limit,
                    "vote_limit": user_subscription.vote_limit,
                }
            )

    if profile_user.is_artist():
        user_content = Content.objects.filter(artist=profile_user)
        if profile_user != viewer and not viewer.is_admin():
            user_content = user_content.filter(is_approved=True, is_visible=True)
        context.update(
            {
                "user_content": user_content,
                "is_artist": True,
            }
        )

    if profile_user != viewer and not viewer.is_admin() and not profile_user.is_admin():
        try:
            from chatapp.models import MatchRating
            from chatapp.services import get_match_score, users_can_peer_chat

            context.update(
                {
                    "viewer_match_rating": MatchRating.objects.filter(
                        rater=viewer,
                        rated=profile_user,
                    ).first(),
                    "profile_user_match_rating": MatchRating.objects.filter(
                        rater=profile_user,
                        rated=viewer,
                    ).first(),
                    "can_peer_chat": users_can_peer_chat(viewer, profile_user),
                    "match_score": get_match_score(viewer, profile_user),
                }
            )
        except Exception:
            context.update(
                {
                    "viewer_match_rating": None,
                    "profile_user_match_rating": None,
                    "can_peer_chat": False,
                    "match_score": None,
                }
            )
    else:
        context.update(
            {
                "followed_artists": profile_user.following.filter(
                    following__role=Role.ARTIST
                ).select_related("following"),
                "can_peer_chat": False,
                "match_score": None,
                "viewer_match_rating": None,
                "profile_user_match_rating": None,
            }
        )

    return context


@login_required
def profile(request):
    if request.method == "POST":
        form = ProfileUpdateForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated successfully.")
            return redirect("profile")
    else:
        form = ProfileUpdateForm(instance=request.user)

    context = _profile_context(request.user, request.user, form)
    return render(request, "users/profile.html", context)


@login_required
def user_profile(request, user_id):
    user = get_object_or_404(CustomUser, id=user_id)
    is_following = Follow.objects.filter(follower=request.user, following=user).exists()

    # Handle Follow/Unfollow action
    if "follow" in request.POST and request.user != user:
        if is_following:
            Follow.objects.filter(follower=request.user, following=user).delete()
            messages.success(request, f"You have unfollowed {user.username}.")
        else:
            Follow.objects.create(follower=request.user, following=user)
            messages.success(request, f"You are now following {user.username}.")
        return redirect("user_profile", user_id=user.id)

    # Handle Profile Update action
    if "update_profile" in request.POST:
        if request.user != user:
            return HttpResponseForbidden("You cannot update another user's profile.")
        form = ProfileUpdateForm(request.POST, request.FILES, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated successfully.")
            return redirect("user_profile", user_id=user.id)
    else:
        form = ProfileUpdateForm(instance=user)

    context = _profile_context(user, request.user, form)

    return render(request, "users/profile.html", context)


@login_required
@require_POST
def follow_user(request, user_id):
    user_to_follow = get_object_or_404(CustomUser, id=user_id)
    if request.user != user_to_follow:
        Follow.objects.get_or_create(follower=request.user, following=user_to_follow)
        messages.success(request, f"You are now following {user_to_follow.username}.")
    return redirect("user_profile", user_id=user_id)


@login_required
@require_POST
def unfollow_user(request, user_id):
    user_to_unfollow = get_object_or_404(CustomUser, id=user_id)
    Follow.objects.filter(follower=request.user, following=user_to_unfollow).delete()
    messages.success(request, f"You have unfollowed {user_to_unfollow.username}.")
    return redirect("user_profile", user_id=user_id)


@receiver(post_save, sender=Vote)
def notify_artist_on_vote(sender, instance, **kwargs):
    """
    Send a notification to the artist when their content is voted on.
    """
    content = instance.content
    artist = content.artist
    badge_text = " with badge" if instance.is_badge_vote else ""
    message = (
        f"{instance.fan.username} voted {instance.value} on your content: {content.title}"
        f"{badge_text}"
    )

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
    notifications = Notification.objects.filter(
        user=request.user, is_read=False
    ).order_by("-created_at")
    return render(request, "users/notifications.html", {"notifications": notifications})


@login_required
def mark_notifications_as_read(request):
    """
    Mark all unread notifications as read for the logged-in user.
    """
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return JsonResponse({"status": "success"})


class ProfileUpdateView(LoginRequiredMixin, UpdateView):
    model = CustomUser
    form_class = ProfileUpdateForm
    template_name = "users/profile.html"  # Template for the profile update form
    success_url = reverse_lazy(
        "profile"
    )  # Redirect to the profile page after successful update

    def get_object(self, queryset=None):
        return self.request.user  # Ensure the logged-in user is the one being updated


@login_required
@require_POST
def toggle_content_voting(request, content_id, action):
    if not request.user.has_role(Role.ADMIN):
        return HttpResponseForbidden()

    content = get_object_or_404(Content, id=content_id)
    if action == "reset":
        vote_count = Vote.objects.filter(content=content).delete()[0]
        rating_count = reset_content_rating_chat_access(content)
        messages.success(
            request,
            (
                f"Reset {vote_count} vote(s) and {rating_count} chat unlock(s) "
                f"for {content.title}."
            ),
        )
        return redirect("admin_dashboard")

    if action not in {"approve", "disapprove"}:
        messages.error(request, "Invalid voting action.")
        return redirect("admin_dashboard")

    content.is_approved_for_voting = action == "approve"
    content.save(update_fields=["is_approved_for_voting"])
    messages.success(
        request,
        f"Voting {'approved' if content.is_approved_for_voting else 'disapproved'} for {content.title}.",
    )
    return redirect("admin_dashboard")


def voting_statistics(request):
    if not request.user.has_role(Role.ADMIN):
        return redirect("dashboard")

    content_ranking = get_content_ranking_queryset()

    context = {
        "content_ranking": content_ranking,
    }
    return render(request, "users/voting_statistics.html", context)


def search_results(request):
    query = request.GET.get("q", "").strip()

    users, content = [], []

    if query:
        # Search for users (Check if users exist)
        users = CustomUser.objects.filter(
            Q(username__icontains=query) | Q(email__icontains=query)
        )

        # Search for content
        content = Content.objects.filter(
            Q(title__icontains=query) | Q(description__icontains=query)
        ).filter(is_approved=True, is_visible=True)

    return render(
        request,
        "users/search_results.html",
        {
            "query": query,
            "users": users,
            "content": content,
        },
    )


from django.core.paginator import Paginator


@login_required
def get_announcements(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "User not authenticated"}, status=401)

    dismissed = DismissedAnnouncement.objects.filter(user=request.user).values_list(
        "announcement_id", flat=True
    )
    announcements = (
        Announcement.objects.exclude(id__in=dismissed)
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
        .order_by("-created_at")
        .values("id", "title", "message")
    )

    return JsonResponse({"announcements": list(announcements)})


@login_required
def dismiss_announcement(request, announcement_id):
    announcement = Announcement.objects.get(id=announcement_id)
    DismissedAnnouncement.objects.get_or_create(
        user=request.user, announcement=announcement
    )
    return JsonResponse({"status": "dismissed"})


@login_required
@require_POST
def delete_announcement(request, announcement_id):
    if not request.user.has_role(Role.ADMIN):
        return redirect("dashboard")

    announcement = get_object_or_404(Announcement, id=announcement_id)
    announcement.delete()
    messages.success(request, "Announcement deleted successfully.")
    return redirect("admin_dashboard")


def terms_and_conditions(request):
    terms = TermsAndConditions.objects.filter(is_active=True).first()

    # Safely check permissions for authenticated users
    can_manage = False
    if request.user.is_authenticated:
        can_manage = request.user.has_perm("users.manage_terms") or (
            hasattr(request.user, "is_admin") and request.user.is_admin()
        )

    context = {"terms": terms, "can_manage_terms": can_manage}
    return render(request, "users/terms_and_conditions.html", context)


@login_required
@permission_required("users.manage_terms", raise_exception=True)
def manage_terms(request):
    return redirect("terms_and_conditions")
