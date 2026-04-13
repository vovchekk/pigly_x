from django.urls import path

from .views import history_detail_page_view, history_page_view


app_name = "history_pages"

urlpatterns = [
    path("", history_page_view, name="list"),
    path("<int:pk>/", history_detail_page_view, name="detail"),
]
