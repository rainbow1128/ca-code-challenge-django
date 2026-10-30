import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ca_shared.tokens import generate_private_key, private_key_to_pem, public_key_to_pem


class Command(BaseCommand):
    help = (
        "Create the Ed25519 key pair for signing access tokens: the private key "
        "for this service (mode 600) and the public key for the services that "
        "verify tokens. Does nothing if both files exist (use --force to replace)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--private-key", default=settings.JWT_PRIVATE_KEY_FILE)
        parser.add_argument("--public-key", default=settings.JWT_PUBLIC_KEY_FILE)
        parser.add_argument("--force", action="store_true",
                            help="Replace existing keys (every issued token stops working).")

    def handle(self, *args, private_key, public_key, force, **options):
        private_path, public_path = Path(private_key), Path(public_key)
        exists = private_path.exists(), public_path.exists()
        if all(exists) and not force:
            self.stdout.write(f"Keys already exist ({private_path}, {public_path}); nothing to do.")
            return
        if any(exists) and not force:
            raise CommandError("Only one of the two key files exists; use --force to create a new pair.")

        key = generate_private_key()
        _write(private_path, private_key_to_pem(key), mode=0o600)
        _write(public_path, public_key_to_pem(key), mode=0o644)
        self.stdout.write(self.style.SUCCESS(f"Wrote {private_path} (private) and {public_path} (public)."))


def _write(path: Path, data: bytes, *, mode: int):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.chmod(tmp, mode)  # O_CREAT's mode is reduced by the umask
    os.replace(tmp, path)  # never leave a half-written key behind
