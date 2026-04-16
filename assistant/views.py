from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt

from history.models import GenerationRequest
from history.serializers import serialize_generation_request

from .services import GeminiGenerationError, build_reply_generation, build_shorten_generation, create_generation_record
from .utils import (
    coerce_int,
    json_error,
    normalize_text,
    parse_request_data,
    pick_first,
    require_api_auth,
)


def _build_response(item):
    return JsonResponse({"status": "ok", "request": serialize_generation_request(item)}, status=201)


def _enforce_plan_limit(user, kind):
    blocked_until = user.plan_access.generation_blocked_until
    if blocked_until and blocked_until > timezone.now():
        return json_error(
            "Generation is temporarily restricted for this account.",
            status=403,
            code="generation_temporarily_blocked",
            extra={"kind": kind, "blocked_until": blocked_until.isoformat()},
        )
    remaining = user.plan_access.remaining_for_kind(kind)
    if remaining == 0:
        return json_error(
            "Plan limit reached.",
            status=403,
            code="plan_limit_reached",
            extra={"kind": kind, "remaining": 0},
        )
    return None


@csrf_exempt
@require_api_auth
@require_POST
def shorten_view(request):
    data, error = parse_request_data(request)
    if error:
        return error

    source_text = pick_first(data, "text", "source_text", "post_text", "draft_text", "content").strip()
    if not source_text:
        return json_error("Source text is required.", code="missing_source_text")

    profile = getattr(request.user, "profile", None)
    tone = pick_first(data, "tone", default=getattr(profile, "preferred_tone", "friendly"))
    language = pick_first(
        data,
        "language",
        "locale",
        default=getattr(profile, "preferred_translate_language", ""),
    )
    variant_count = coerce_int(
        pick_first(data, "variant_count", "count"),
        default=1,
        minimum=1,
        maximum=3,
    )
    target_length = coerce_int(pick_first(data, "target_length", "max_length"), default=220, minimum=80, maximum=420)

    limit_error = _enforce_plan_limit(request.user, GenerationRequest.KIND_SHORTEN)
    if limit_error:
        return limit_error

    try:
        request_data, results = build_shorten_generation(
            source_text=source_text,
            tone=tone,
            language=language,
            variant_count=variant_count,
            target_length=target_length,
            profile=profile,
        )
    except GeminiGenerationError as exc:
        return json_error(
            str(exc),
            status=503,
            code=exc.code,
            extra=exc.extra,
        )
    item = create_generation_record(
        user=request.user,
        kind=GenerationRequest.KIND_SHORTEN,
        source_text=source_text,
        tone=request_data["tone"],
        request_data=request_data,
        results=results,
    )
    return _build_response(item)


@csrf_exempt
@require_api_auth
@require_POST
def reply_view(request):
    data, error = parse_request_data(request)
    if error:
        return error

    source_text = pick_first(data, "text", "source_text", "post_text", "content").strip()
    context_text = pick_first(data, "context", "context_text", "thread_context", default="").strip()
    if not source_text:
        return json_error("Source text is required.", code="missing_source_text")

    profile = getattr(request.user, "profile", None)
    tone = pick_first(data, "tone", default=getattr(profile, "preferred_tone", "friendly"))
    language = pick_first(
        data,
        "language",
        "locale",
        default=getattr(profile, "preferred_translate_language", ""),
    )
    variant_count = coerce_int(
        pick_first(data, "variant_count", "count"),
        default=getattr(profile, "preferred_variant_count", 3),
        minimum=1,
        maximum=3,
    )

    limit_error = _enforce_plan_limit(request.user, GenerationRequest.KIND_REPLY)
    if limit_error:
        return limit_error

    try:
        request_data, results = build_reply_generation(
            source_text=source_text,
            context_text=context_text,
            tone=tone,
            language=language,
            variant_count=variant_count,
            profile=profile,
        )
    except GeminiGenerationError as exc:
        return json_error(
            str(exc),
            status=503,
            code=exc.code,
            extra=exc.extra,
        )
    item = create_generation_record(
        user=request.user,
        kind=GenerationRequest.KIND_REPLY,
        source_text=source_text,
        tone=request_data["tone"],
        request_data=request_data,
        results=results,
    )
    return _build_response(item)
