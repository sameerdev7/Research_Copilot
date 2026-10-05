import os

from celery import Celery
from celery.signals import worker_process_init

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("research_copilot")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


# load the embedding model when each worker process starts
@worker_process_init.connect
def warm_embeddings(**kwargs):
    from agent.embeddings import warm_up

    warm_up()
