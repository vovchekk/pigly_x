from django.urls import path

from .views import history_detail_view, history_list_view


app_name = "history"

urlpatterns = [
    path("", history_list_view, name="list"),
    path("<int:pk>/", history_detail_view, name="detail"),
]
