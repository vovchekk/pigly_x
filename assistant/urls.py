from django.urls import path

from . import views


app_name = "assistant"

urlpatterns = [
    path("shorten/", views.shorten_view, name="shorten"),
    path("reply/", views.reply_view, name="reply"),
    path("translate/", views.translate_view, name="translate"),
]
