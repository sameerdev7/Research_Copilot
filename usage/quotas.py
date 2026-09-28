from datetime import date

from django.conf import settings
from django.db import transaction
from django.db.models import F

from .models import UsageRecord


class QuotaExceeded(Exception):
    pass


def check_and_increment(user, tokens_used: int = 0) -> UsageRecord:
    """Raise QuotaExceeded if today's question quota is already used up, else record the request."""
    today = date.today()
    with transaction.atomic():
        record, _ = UsageRecord.objects.select_for_update().get_or_create(user=user, date=today)
        if record.requests_made >= settings.DAILY_QUESTION_QUOTA:
            raise QuotaExceeded(f"Daily quota of {settings.DAILY_QUESTION_QUOTA} questions reached")
        record.requests_made = F("requests_made") + 1
        record.tokens_used = F("tokens_used") + tokens_used
        record.save(update_fields=["requests_made", "tokens_used"])
        record.refresh_from_db()
    return record
