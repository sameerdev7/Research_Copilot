from django.contrib import admin

from .models import UsageRecord


@admin.register(UsageRecord)
class UsageRecordAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "date", "requests_made", "tokens_used")
    list_filter = ("date",)
