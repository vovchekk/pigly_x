from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
    path("users/", include("users.urls")),
    path("accounts/", include("allauth.urls")),
    path("api/auth/", include("users.api_urls")),
    path("api/ai/", include("assistant.urls")),
    path("api/history/", include("history.urls")),
    path("history/", include("history.web_urls")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
