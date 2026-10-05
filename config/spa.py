from django.conf import settings
from django.http import HttpResponse

NOT_BUILT = """<!doctype html><title>Research Copilot</title>
<body style="font-family:system-ui;max-width:36rem;margin:4rem auto;line-height:1.5">
<h1>Frontend not built</h1>
<p>For development run <code>npm run dev</code> in <code>frontend/</code> and open
<a href="http://localhost:5173">localhost:5173</a>.</p>
<p>For production run <code>npm run build</code> in <code>frontend/</code>, then restart Django.</p>"""


def spa(request):
    index = settings.FRONTEND_DIST / "index.html"
    if not index.exists():
        return HttpResponse(NOT_BUILT, status=503)
    response = HttpResponse(index.read_text(), content_type="text/html")
    response["Cache-Control"] = "no-cache"  # always pick up a new build's asset names
    return response
