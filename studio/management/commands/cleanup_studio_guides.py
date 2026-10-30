import re
import time
from django.core.management.base import BaseCommand, CommandError
from studio.guide_cache import cache_directory


class Command(BaseCommand):
    help = "Remove old generated collaboration audio guides; never source media or previews."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=7)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        if options["days"] < 1:
            raise CommandError("Choose at least one day.")
        root = cache_directory()
        cutoff = time.time() - options["days"] * 86400
        count = 0
        if root.is_dir():
            for path in root.iterdir():
                if not re.fullmatch(r"[0-9a-f]{64}\.wav|\.guide-[^/\\]+\.tmp", path.name):
                    continue
                try:
                    if not path.is_file() or path.stat().st_mtime >= cutoff:
                        continue
                    if not options["dry_run"]:
                        path.unlink()
                    count += 1
                except OSError:
                    continue
        self.stdout.write(f"{count} old generated guides " + ("eligible for removal." if options["dry_run"] else "removed."))
