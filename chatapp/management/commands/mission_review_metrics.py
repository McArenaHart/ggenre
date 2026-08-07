from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Count
from django.db.utils import OperationalError
from django.utils import timezone

from chatapp.models import AdminDecisionLog, ReviewAutomationTicket
from chatapp.services import get_mission_policy_settings


class Command(BaseCommand):
    help = "Print mission review routing and moderation metrics for ops readiness."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=7,
            help="Trailing number of days for the metrics window.",
        )

    def handle(self, *args, **options):
        days = max(1, int(options["days"]))
        since = timezone.now() - timedelta(days=days)

        try:
            route_logs = AdminDecisionLog.objects.filter(
                action="mission_review_route",
                created_at__gte=since,
            )
            decision_logs = AdminDecisionLog.objects.filter(
                action__in=["approve_proof", "reject_proof"],
                created_at__gte=since,
            )

            route_counts = list(route_logs.values("actor_type").annotate(total=Count("id")))
            decision_counts = list(decision_logs.values("action").annotate(total=Count("id")))
            ticket_counts = list(ReviewAutomationTicket.objects.filter(
                created_at__gte=since,
            ).values("status").annotate(total=Count("id")))
        except OperationalError:
            self.stdout.write(
                self.style.WARNING(
                    "Database tables for mission metrics are not available yet. "
                    "Run migrations first: python manage.py migrate"
                )
            )
            return

        self.stdout.write(f"Mission review metrics window: last {days} day(s)")
        self.stdout.write("Policy snapshot:")
        for key, value in sorted(get_mission_policy_settings().items()):
            self.stdout.write(f"  - {key}: {value}")

        self.stdout.write("\nMission route counts:")
        if route_counts:
            for row in route_counts:
                self.stdout.write(f"  - {row['actor_type']}: {row['total']}")
        else:
            self.stdout.write("  - none")

        self.stdout.write("\nMission decision counts:")
        if decision_counts:
            for row in decision_counts:
                self.stdout.write(f"  - {row['action']}: {row['total']}")
        else:
            self.stdout.write("  - none")

        self.stdout.write("\nAutomation ticket counts:")
        if ticket_counts:
            for row in ticket_counts:
                self.stdout.write(f"  - {row['status']}: {row['total']}")
        else:
            self.stdout.write("  - none")
