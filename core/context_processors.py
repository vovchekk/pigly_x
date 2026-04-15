from django.conf import settings


def site_context(request):
    return {
        "site_name": settings.SITE_NAME,
        "extension_install_url": settings.EXTENSION_INSTALL_URL,
        "extension_install_ready": settings.EXTENSION_INSTALL_URL.strip() not in {"", "#"},
        "site_url": settings.SITE_URL,
    }
