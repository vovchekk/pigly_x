from django.urls import path

from . import views


app_name = "users_api"

urlpatterns = [
    path("session/", views.extension_session_view, name="session"),
    path("profile/update/", views.profile_update_view, name="profile_update"),
    path("extension-token/rotate/", views.extension_token_rotate_view, name="extension_token_rotate"),
]
