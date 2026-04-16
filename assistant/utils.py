import json
import re
from functools import wraps

from django.http import JsonResponse
from django.utils import timezone

from users.models import ExtensionAccessToken


CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
MULTISPACE_RE = re.compile(r"[ \t]+")


def json_error(message, *, status=400, code="bad_request", extra=None):
    payload = {"status": "error", "error": {"code": code, "message": message}}
    if extra:
        payload["error"].update(extra)
    return JsonResponse(payload, status=status)


def _extract_extension_token(request):
    auth_header = (request.headers.get("Authorization") or "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return (request.headers.get("X-Pigly-Extension-Token") or "").strip()


def require_api_auth(view_func):
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if request.user.is_authenticated:
            request.auth_method = "session"
            return view_func(request, *args, **kwargs)

        token_value = _extract_extension_token(request)
        if not token_value:
            return json_error("Authentication required.", status=401, code="not_authenticated")

        try:
            extension_token = ExtensionAccessToken.objects.select_related("user", "user__profile", "user__plan_access").get(
                token=token_value
            )
        except ExtensionAccessToken.DoesNotExist:
            return json_error("Extension token is invalid.", status=401, code="invalid_extension_token")

        extension_token.last_used_at = timezone.now()
        extension_token.save(update_fields=["last_used_at"])
        request.user = extension_token.user
        request.auth_method = "extension_token"
        request.extension_token = extension_token
        return view_func(request, *args, **kwargs)

    return wrapped


def parse_request_data(request):
    if request.method == "GET":
        return request.GET.dict(), None

    content_type = (request.content_type or "").split(";")[0].strip().lower()
    if content_type == "application/json":
        try:
            body = json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return None, json_error("Request body must be valid JSON.", code="invalid_json")
        if not isinstance(body, dict):
            return None, json_error("JSON payload must be an object.", code="invalid_json")
        return body, None

    if request.POST:
        return request.POST.dict(), None

    return {}, None


def pick_first(data, *keys, default=""):
    for key in keys:
        value = data.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
        else:
            value = str(value).strip()
        if value != "":
            return value
    return default


def coerce_int(value, *, default, minimum=None, maximum=None):
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default

    if minimum is not None and result < minimum:
        result = minimum
    if maximum is not None and result > maximum:
        result = maximum
    return result


def normalize_language(value, source_text=""):
    candidate = str(value or "").strip().lower()
    if candidate in {"ru", "russian", "русский"}:
        return "ru"
    if candidate in {"en", "english", "английский"}:
        return "en"
    if candidate in {"zh", "chinese", "中文", "китайский"}:
        return "zh"
    return "ru" if CYRILLIC_RE.search(source_text or "") else "en"


def normalize_tone(value):
    tone = str(value or "").strip().lower()
    if tone in {"friendly", "warm", "kind"}:
        return "friendly"
    if tone in {"confident", "bold"}:
        return "confident"
    if tone in {"concise", "short"}:
        return "concise"
    if tone in {"neutral", "calm"}:
        return "neutral"
    return "friendly"


def normalize_text(value):
    return MULTISPACE_RE.sub(" ", str(value or "").strip())


def trim_words(text, word_count):
    words = normalize_text(text).split()
    if not words:
        return ""
    if len(words) <= word_count:
        return " ".join(words)
    return " ".join(words[:word_count]).rstrip(",;:-") + "..."


def first_sentence(text):
    normalized = normalize_text(text)
    if not normalized:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", normalized)
    return parts[0]
