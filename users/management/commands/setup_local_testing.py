from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from content.models import ArtistUploadLimit, Content, Genre
from users.models import OTP, Role


class Command(BaseCommand):
    help = "Bootstrap local users/content/OTP data for manual testing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete and recreate local testing users/content.",
        )
        parser.add_argument(
            "--admin-password",
            default="Admin123!",
            help="Password for local_admin user.",
        )
        parser.add_argument(
            "--artist-password",
            default="Artist123!",
            help="Password for local_artist user.",
        )
        parser.add_argument(
            "--fan-password",
            default="Fan123!",
            help="Password for local_fan user.",
        )
        parser.add_argument(
            "--fan-votes",
            default=1,
            type=int,
            help="Initial OTP vote count for local_fan (default: 1).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        usernames = ["local_admin", "local_artist", "local_fan"]

        if options["reset"]:
            Content.objects.filter(artist__username__in=usernames).delete()
            OTP.objects.filter(user__username__in=usernames).delete()
            User.objects.filter(username__in=usernames).delete()
            self.stdout.write(self.style.WARNING("Reset existing local testing users/content."))

        admin = self._create_or_update_user(
            User=User,
            username="local_admin",
            email="local_admin@example.com",
            password=options["admin_password"],
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        artist = self._create_or_update_user(
            User=User,
            username="local_artist",
            email="local_artist@example.com",
            password=options["artist_password"],
            role=Role.ARTIST,
        )
        fan = self._create_or_update_user(
            User=User,
            username="local_fan",
            email="local_fan@example.com",
            password=options["fan_password"],
            role=Role.FAN,
        )

        genre, _ = Genre.objects.get_or_create(name="Local Demo Genre")
        ArtistUploadLimit.objects.get_or_create(
            artist=artist,
            defaults={
                "uploads_used": 0,
                "upload_limit": 50,
                "reset_on_payment": False,
                "suspended_by_admin": False,
            },
        )

        content_one, _ = Content.objects.get_or_create(
            artist=artist,
            title="Local YouTube Demo",
            defaults={
                "description": "YouTube embed demo content for local testing.",
                "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "genre": genre,
                "is_approved": True,
                "is_approved_for_voting": True,
                "is_visible": True,
            },
        )
        content_one.genre = genre
        content_one.youtube_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        content_one.is_approved = True
        content_one.is_approved_for_voting = True
        content_one.is_visible = True
        content_one.save()
        content_one.tags.set(["local", "youtube", "demo"])

        content_two, _ = Content.objects.get_or_create(
            artist=artist,
            title="Local YouTube Shorts Demo",
            defaults={
                "description": "YouTube shorts embed demo for local testing.",
                "youtube_url": "https://www.youtube.com/shorts/aqz-KE-bpKQ",
                "genre": genre,
                "is_approved": True,
                "is_approved_for_voting": True,
                "is_visible": True,
            },
        )
        content_two.genre = genre
        content_two.youtube_url = "https://www.youtube.com/shorts/aqz-KE-bpKQ"
        content_two.is_approved = True
        content_two.is_approved_for_voting = True
        content_two.is_visible = True
        content_two.save()
        content_two.tags.set(["local", "youtube", "shorts"])

        fan_votes = max(1, int(options["fan_votes"]))
        otp, _ = OTP.objects.get_or_create(
            user=fan,
            defaults={
                "otp_code": "123456",
                "remaining_votes": fan_votes,
                "is_active": True,
                "last_vote_reset_at": timezone.now(),
            },
        )
        otp.otp_code = "123456"
        otp.remaining_votes = fan_votes
        otp.is_active = True
        otp.last_vote_reset_at = timezone.now()
        otp.save()

        self.stdout.write(self.style.SUCCESS("Local testing data is ready."))
        self.stdout.write("")
        self.stdout.write("Users:")
        self.stdout.write(f"  admin  -> username: local_admin | password: {options['admin_password']}")
        self.stdout.write(f"  artist -> username: local_artist | password: {options['artist_password']}")
        self.stdout.write(f"  fan    -> username: local_fan | password: {options['fan_password']}")
        self.stdout.write("")
        self.stdout.write("OTP for local_fan:")
        self.stdout.write(f"  code: {otp.otp_code} | remaining_votes: {otp.remaining_votes} | active: {otp.is_active}")
        self.stdout.write("")
        self.stdout.write("Quick checks:")
        self.stdout.write("  1) Login as local_artist and upload a YouTube link.")
        self.stdout.write("  2) Login as local_fan and vote once using OTP 123456.")
        self.stdout.write("  3) Login as local_admin and use OTP Access Controls to extend/reset/cancel local_fan.")

    def _create_or_update_user(
        self,
        *,
        User,
        username,
        email,
        password,
        role,
        is_staff=False,
        is_superuser=False,
    ):
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "email": email,
                "role": role,
                "is_active": True,
                "is_staff": is_staff,
                "is_superuser": is_superuser,
            },
        )

        user.email = email
        user.role = role
        user.is_active = True
        user.is_staff = is_staff
        user.is_superuser = is_superuser
        user.set_password(password)
        user.save()

        status = "Created" if created else "Updated"
        self.stdout.write(f"{status} user: {username}")
        return user
