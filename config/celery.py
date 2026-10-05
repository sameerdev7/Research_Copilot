import os

from celery import Celery
from celery.signals import worker_init

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("research_copilot")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


# load the embedding model once in the main process, before the pool forks
@worker_init.connect
def warm_embeddings(**kwargs):
    from agent.embeddings import warm_up

    warm_up()
