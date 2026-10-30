from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """An account. The auth service is the source of truth for its role.

    ``wp_user_id`` is the WordPress user ID for imported accounts. The main
    service's Reviewer rows carry the same ID, which links a reviewer profile
    to its account without either service reading the other's database.
    """

    class Role(models.TextChoices):
        READER = "reader", "Reader"
        EDITOR = "editor", "Editor"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.READER)
    display_name = models.CharField(max_length=200, blank=True)
    wp_user_id = models.PositiveBigIntegerField(
        unique=True,
        null=True,
        blank=True,
        editable=False,
        help_text="ID of the source user in WordPress. NULL for accounts created here.",
    )

    def __str__(self):
        return self.username
