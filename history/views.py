from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from assistant.utils import require_api_auth

from .models import GenerationRequest, GenerationResult
from .serializers import serialize_generation_request


@require_api_auth
@require_GET
def history_list_view(request):
    kind = request.GET.get("kind", "").strip()
    limit = request.GET.get("limit", "20").strip()
    try:
        limit = max(1, min(int(limit), 100))
    except ValueError:
        limit = 20

    queryset = (
        GenerationRequest.objects.filter(user=request.user)
        .prefetch_related(Prefetch("results", queryset=GenerationResult.objects.all()))
        .order_by("-created_at")
    )
    if kind in {GenerationRequest.KIND_SHORTEN, GenerationRequest.KIND_REPLY}:
        queryset = queryset.filter(kind=kind)

    items = [serialize_generation_request(item) for item in queryset[:limit]]
    return JsonResponse({"status": "ok", "items": items, "count": len(items)})


@require_api_auth
@require_GET
def history_detail_view(request, pk):
    item = get_object_or_404(
        GenerationRequest.objects.prefetch_related(Prefetch("results", queryset=GenerationResult.objects.all())),
        pk=pk,
        user=request.user,
    )
    return JsonResponse({"status": "ok", "item": serialize_generation_request(item)})


@login_required
def history_page_view(request):
    items = (
        GenerationRequest.objects.filter(user=request.user)
        .prefetch_related(Prefetch("results", queryset=GenerationResult.objects.all()))
        .order_by("-created_at")
    )
    return render(request, "history/list.html", {"items": items})


@login_required
def history_detail_page_view(request, pk):
    item = get_object_or_404(
        GenerationRequest.objects.prefetch_related(Prefetch("results", queryset=GenerationResult.objects.all())),
        pk=pk,
        user=request.user,
    )
    return render(request, "history/detail.html", {"item": item})
