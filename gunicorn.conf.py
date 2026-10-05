import os

bind = "0.0.0.0:8000"
# requests mostly wait on the LLM, so threads matter more than processes
worker_class = "gthread"
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
threads = int(os.environ.get("WEB_THREADS", "8"))
# long enough for a streamed answer with several critique retries
timeout = 180
graceful_timeout = 30
# load Django once, then fork, so the embedding model is shared between workers
preload_app = True


# warm the embedding model in the master before workers fork
def when_ready(server):
    from agent.embeddings import warm_up

    warm_up()
