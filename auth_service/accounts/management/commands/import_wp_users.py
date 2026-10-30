from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts.wp_import import ImportFailed, ValidationFailed, run_user_import
from accounts.wp_source import MariaDBUserSource, SourceError


def source_from_settings():
    return MariaDBUserSource(**settings.WP_SOURCE)


class Command(BaseCommand):
    help = (
        "Import WordPress users and roles (administrator/editor -> editor, "
        "everything else -> reader). Safe to re-run: matched on WordPress user ID."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would change, then roll back.")
        parser.add_argument("--prune", action="store_true",
                            help="Deactivate imported accounts that no longer exist in WordPress.")

    def handle(self, *args, dry_run, prune, **options):
        source = source_from_settings()
        password = settings.AUTH_IMPORT_PASSWORD
        self.stdout.write(f"Reading {source.describe()} ...")
        try:
            report = run_user_import(source, password=password, prune=prune, dry_run=dry_run)
        except SourceError as exc:
            raise CommandError(str(exc)) from exc
        except (ValidationFailed, ImportFailed) as exc:
            for error in exc.errors:
                self.stderr.write(f"  ERROR {error}")
            raise CommandError(f"{exc} Nothing was written.") from exc

        out = self.stdout
        out.write(f"users: created {report.created}, updated {report.updated}, "
                  f"unchanged {report.unchanged}, missing {len(report.missing)}, "
                  f"deactivated {report.deactivated}")
        for username, role in sorted(report.roles.items()):
            out.write(f"  new account {username:<12} role={role}")
        if report.created:
            out.write("  new accounts' password: "
                      + ("AUTH_IMPORT_PASSWORD" if password else "unusable (AUTH_IMPORT_PASSWORD is empty)"))
        if report.missing and not prune:
            out.write("  missing in WordPress (kept; use --prune to deactivate): wp_user_id "
                      + ", ".join(map(str, report.missing)))
        for warning in report.warnings:
            out.write(self.style.WARNING(f"WARNING {warning}"))
        out.write(self.style.WARNING("Dry run: all changes rolled back.") if report.dry_run
                  else self.style.SUCCESS("Import committed."))
