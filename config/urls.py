from django.contrib import admin
from django.urls import include, path, re_path

from api.health import healthz

from .spa import spa

urlpatterns = [
    path("healthz", healthz),
    path("admin/", admin.site.urls),
    path("api/", include("api.urls")),
    # everything else is the React app
    re_path(r"^(?!static/|api/|admin/|healthz).*$", spa),
]
