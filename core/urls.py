from django.urls import path

from . import views


app_name = "core"

urlpatterns = [
    path("", views.landing_view, name="landing"),
    path("dashboard/", views.profile_view, name="dashboard"),
    path("profile/", views.profile_view, name="profile"),
]
