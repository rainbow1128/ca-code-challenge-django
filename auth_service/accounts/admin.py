from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "display_name", "email", "role", "is_active", "wp_user_id")
    list_filter = ("role", "is_active")
    readonly_fields = ("wp_user_id",)
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Access", {"fields": ("role", "display_name", "wp_user_id")}),
    )
