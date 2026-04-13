from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from django.middleware.csrf import get_token

from allauth.socialaccount.models import SocialAccount

from assistant.utils import require_api_auth

from .forms import CustomAuthenticationForm, CustomUserCreationForm
from .models import ExtensionAccessToken
from assistant.utils import parse_request_data
from django.views.decorators.csrf import csrf_exempt


def render_google_auth_page(request, page_title):
    return render(
        request,
        "users/auth_page.html",
        {
            "page_title": page_title,
            "google_auth_enabled": settings.GOOGLE_AUTH_ENABLED,
        },
    )


def render_landing_with_forms(request, auth_mode, login_form=None, register_form=None):
    context = {
        "auth_mode": auth_mode,
        "google_auth_enabled": settings.GOOGLE_AUTH_ENABLED,
    }
    return render(request, "core/landing.html", context)


@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect("core:profile")

    if request.method == "POST":
        form = CustomAuthenticationForm(request.POST or None)
        if form.is_valid():
            login(request, form.get_user())
            return redirect(request.POST.get("next") or reverse("core:dashboard"))
        if request.POST.get("origin") == "landing":
            return render_landing_with_forms(request, "login", login_form=form)

    return render_google_auth_page(request, "Continue with Google")


@require_http_methods(["GET", "POST"])
def register_view(request):
    if request.user.is_authenticated:
        return redirect("core:profile")

    if request.method == "POST":
        form = CustomUserCreationForm(request.POST or None)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, "Account created. Welcome to Pigly.")
            return redirect("core:dashboard")
        if request.POST.get("origin") == "landing":
            return render_landing_with_forms(request, "register", register_form=form)

    return render_google_auth_page(request, "Continue with Google")


def logout_view(request):
    logout(request)
    messages.success(request, "You signed out of your account.")
    return redirect("core:landing")


def _build_auth_payload(request, token=None):
    token = token or getattr(request.user, "extension_access", None)
    plan_access = request.user.plan_access
    google_connected = SocialAccount.objects.filter(user=request.user, provider="google").exists()
    payload = {
        "status": "ok",
        "auth": {
            "method": getattr(request, "auth_method", "session"),
            "google_connected": google_connected,
        },
        "user": {
            "email": request.user.email,
            "plan_label": plan_access.get_plan_display(),
        },
        "defaults": {
            "language": request.user.profile.preferred_language,
            "tone": request.user.profile.preferred_tone,
            "comment_styles": request.user.profile.selected_comment_styles,
            "translate_to_language": request.user.profile.preferred_translate_language,
            "comment_length": request.user.profile.preferred_comment_length,
            "emoji_mode": request.user.profile.preferred_emoji_mode,
            "dash_style": request.user.profile.preferred_dash_style,
            "terminal_punctuation": request.user.profile.preferred_terminal_punctuation,
            "capitalization": request.user.profile.preferred_capitalization,
        },
        "plan": {
            "name": plan_access.plan,
            "reply_remaining": plan_access.reply_remaining,
            "shorten_remaining": plan_access.shorten_remaining,
            "expires_at": plan_access.expires_at.isoformat() if plan_access.expires_at else None,
        },
        "endpoints": {
            "reply": reverse("assistant:reply"),
            "shorten": reverse("assistant:shorten"),
            "history": reverse("history:list"),
        },
        "dashboard_url": reverse("core:dashboard"),
        "extension_install_url": settings.EXTENSION_INSTALL_URL,
    }
    if token and getattr(request, "auth_method", "session") == "session":
        payload["extension_token"] = token.token
        payload["masked_extension_token"] = token.masked_token
    elif token:
        payload["masked_extension_token"] = token.masked_token
    return payload


@require_api_auth
@require_http_methods(["GET"])
def extension_session_view(request):
    payload = _build_auth_payload(request)
    payload["csrf_token"] = get_token(request)
    return JsonResponse(payload)


@require_api_auth
@require_http_methods(["POST"])
def extension_token_rotate_view(request):
    token, _ = ExtensionAccessToken.objects.get_or_create(user=request.user)
    token.rotate()
    return JsonResponse(_build_auth_payload(request, token=token))


@csrf_exempt
@require_api_auth
@require_http_methods(["POST"])
def profile_update_view(request):
    data, error = parse_request_data(request)
    if error:
        return error

    profile = request.user.profile
    
    if "comment_styles" in data and isinstance(data["comment_styles"], list):
        profile.preferred_comment_styles = [s for s in data["comment_styles"] if s in dict(profile.COMMENT_STYLE_CHOICES)]
        
    if "comment_length" in data and data["comment_length"] in dict(profile.LENGTH_CHOICES):
        profile.preferred_comment_length = data["comment_length"]
        
    if "emoji_mode" in data and data["emoji_mode"] in dict(profile.EMOJI_CHOICES):
        profile.preferred_emoji_mode = data["emoji_mode"]
        
    if "dash_style" in data and data["dash_style"] in dict(profile.DASH_CHOICES):
        profile.preferred_dash_style = data["dash_style"]
        
    if "terminal_punctuation" in data and data["terminal_punctuation"] in dict(profile.PUNCT_CHOICES):
        profile.preferred_terminal_punctuation = data["terminal_punctuation"]
        
    if "capitalization" in data and data["capitalization"] in dict(profile.CAPS_CHOICES):
        profile.preferred_capitalization = data["capitalization"]

    profile.save(update_fields=[
        "preferred_comment_styles", 
        "preferred_comment_length", 
        "preferred_emoji_mode",
        "preferred_dash_style",
        "preferred_terminal_punctuation",
        "preferred_capitalization"
    ])
    
    payload = _build_auth_payload(request)
    payload["csrf_token"] = get_token(request)
    return JsonResponse(payload)
