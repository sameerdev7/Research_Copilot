from django.conf import settings
from django.db import models


class UsageRecord(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="usage_records")
    date = models.DateField()
    tokens_used = models.IntegerField(default=0)
    requests_made = models.IntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "date"], name="unique_usage_record_per_day"),
        ]

    def __str__(self):
        return f"{self.user_id}:{self.date}"
