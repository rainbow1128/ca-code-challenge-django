from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from catalog.wp_import.runner import ImportFailed, run_import
from catalog.wp_import.source import MariaDBSource, SourceError
from catalog.wp_import.validate import ValidationFailed


def source_from_settings():
    return MariaDBSource(**settings.WP_SOURCE)


class Command(BaseCommand):
    help = (
        "Import industries, brands, reviewers and reviews from the WordPress "
        "MariaDB. Safe to re-run: rows are matched on their WordPress ID."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Run the whole import, report what would change, then roll back.",
        )
        parser.add_argument(
            "--prune", action="store_true",
            help="Delete imported rows that no longer exist (or are unpublished) in WordPress. "
                 "Rows created in Django are never deleted.",
        )

    def handle(self, *args, dry_run, prune, **options):
        source = source_from_settings()
        self.stdout.write(f"Reading {source.describe()} ...")
        try:
            report = run_import(source, prune=prune, dry_run=dry_run)
        except SourceError as exc:
            raise CommandError(str(exc)) from exc
        except (ValidationFailed, ImportFailed) as exc:
            for error in exc.errors:
                self.stderr.write(f"  ERROR {error}")
            raise CommandError(f"{exc} Nothing was written.") from exc

        self._print_report(report)

    def _print_report(self, report):
        out = self.stdout
        out.write("")
        out.write(f"{'':<12}{'created':>9}{'updated':>9}{'unchanged':>11}{'missing':>9}{'pruned':>8}")
        for name, r in report.results.items():
            out.write(
                f"{name:<12}{r.created:>9}{r.updated:>9}{r.unchanged:>11}"
                f"{len(r.missing):>9}{r.pruned:>8}"
            )
        for name, r in report.results.items():
            if r.changed_fields:
                out.write(f"  {name} updated fields: {', '.join(sorted(r.changed_fields))}")
            if r.missing:
                out.write(f"  {name} missing in WordPress (kept; use --prune to delete): wp_id "
                          + ", ".join(map(str, r.missing)))

        out.write("")
        out.write("Average rating: WordPress value vs. calculated from reviews")
        for c in report.ratings:
            flag = "  <- differs" if c.differs else ""
            out.write(f"  {c.brand:<28} WP {_fmt(c.wp_average):>5}   reviews {_fmt(c.average):>5}"
                      f"  ({c.review_count}){flag}")

        for warning in report.warnings:
            out.write(self.style.WARNING(f"WARNING {warning}"))

        out.write("")
        if report.dry_run:
            out.write(self.style.WARNING("Dry run: all changes rolled back."))
        else:
            out.write(self.style.SUCCESS("Import committed."))


def _fmt(value):
    return "-" if value is None else str(value)
