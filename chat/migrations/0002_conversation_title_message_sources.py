import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0001_initial"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="conversation",
            options={"ordering": ["-updated_at"]},
        ),
        migrations.AddField(
            model_name="conversation",
            name="title",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="conversation",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="message",
            name="sources",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="message",
            name="diagnostics",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
