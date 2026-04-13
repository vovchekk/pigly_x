import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Max, Q
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from history.models import GenerationRequest
from users.forms import CustomAuthenticationForm, CustomUserCreationForm, UserProfileForm
from users.models import PlanAccess, PromoCode, PromoCodeRedemption, User


PROMO_COOLDOWN_DAYS = 10


def _normalize_promo_code(raw_code):
    return (raw_code or "").strip().upper()


def _get_promo_cooldown_info(user):
    last_redemption = PromoCodeRedemption.objects.filter(user=user).order_by("-created_at").first()
    if not last_redemption:
        return {"active": False, "available_at": None}

    available_at = last_redemption.created_at + timezone.timedelta(days=PROMO_COOLDOWN_DAYS)
    return {
        "active": available_at > timezone.now(),
        "available_at": available_at,
    }


def _apply_plan_access_defaults(plan_access, plan):
    plan_access.plan = plan
    if plan == plan_access.PLAN_FREE:
        plan_access.ai_reply_limit = 30
        plan_access.shorten_limit = 30
    else:
        plan_access.ai_reply_limit = 0
        plan_access.shorten_limit = 0


def _redeem_promo_code(*, user, raw_code):
    normalized_code = _normalize_promo_code(raw_code)
    if not normalized_code:
        return False, "Enter a promo code."

    with transaction.atomic():
        cooldown_info = _get_promo_cooldown_info(user)
        if cooldown_info["active"]:
            return False, "A new promo code cannot be activated yet."

        try:
            promo = PromoCode.objects.select_for_update().get(code=normalized_code)
        except PromoCode.DoesNotExist:
            return False, "Promo code not found."

        if not promo.is_active:
            return False, "This promo code is disabled."

        if PromoCodeRedemption.objects.filter(promo_code=promo, user=user).exists():
            return False, "You have already activated this promo code."

        if promo.activations_count >= promo.max_activations:
            return False, "This promo code has no activations left."

        plan_access = user.plan_access
        _apply_plan_access_defaults(plan_access, promo.plan)
        granted_until = timezone.now() + timezone.timedelta(days=promo.duration_days)
        plan_access.expires_at = granted_until
        plan_access.save(update_fields=["plan", "ai_reply_limit", "shorten_limit", "expires_at"])

        PromoCodeRedemption.objects.create(
            promo_code=promo,
            user=user,
            granted_until=granted_until,
        )
        promo.activations_count += 1
        promo.save(update_fields=["activations_count"])

    return True, f"Promo code activated. {promo.get_plan_display()} access granted."


def _build_admin_usage_rows():
    now = timezone.now()
    day_ago = now - timezone.timedelta(days=1)

    users = (
        User.objects.select_related("plan_access")
        .annotate(
            generated_day=Count("generation_requests", filter=Q(generation_requests__created_at__gte=day_ago)),
            generated_all=Count("generation_requests"),
            last_activity_at=Max("generation_requests__created_at"),
        )
        .order_by("-generated_all", "-last_activity_at", "email")
    )

    rows = []
    for user in users:
        plan_access = getattr(user, "plan_access", None)
        rows.append(
            {
                "id": user.id,
                "name": user.username or user.email.split("@")[0],
                "email": user.email,
                "plan": plan_access.plan if plan_access else PlanAccess.PLAN_FREE,
                "plan_label": plan_access.get_plan_display() if plan_access else "Free",
                "generated_day": user.generated_day or 0,
                "generated_all": user.generated_all or 0,
                "last_activity_at": user.last_activity_at,
                "plan_choices": PlanAccess.PLAN_CHOICES,
            }
        )
    return rows


def landing_view(request):
    auth_mode = request.GET.get("auth", "register")
    if auth_mode not in {"login", "register"}:
        auth_mode = "register"

    context = {
        "auth_mode": auth_mode,
        "login_form": CustomAuthenticationForm(),
        "register_form": CustomUserCreationForm(),
        "google_auth_enabled": settings.GOOGLE_AUTH_ENABLED,
    }
    return render(request, "core/landing.html", context)


@login_required
def profile_view(request):
    profile = request.user.profile
    plan_access = request.user.plan_access
    purchases = request.user.purchases.all()[:10]
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if request.method == "POST":
        admin_plan_user_id = request.POST.get("admin_plan_user_id")
        admin_plan_value = request.POST.get("admin_plan")
        if admin_plan_user_id and admin_plan_value and request.user.is_staff:
            target_user = User.objects.filter(pk=admin_plan_user_id).select_related("plan_access").first()
            valid_plans = {choice[0] for choice in PlanAccess.PLAN_CHOICES}
            if not target_user or admin_plan_value not in valid_plans:
                messages.error(request, "Could not update the user plan.")
                return redirect("core:dashboard")
            _apply_plan_access_defaults(target_user.plan_access, admin_plan_value)
            target_user.plan_access.save(update_fields=["plan", "ai_reply_limit", "shorten_limit"])
            messages.success(request, f"Plan updated for {target_user.email}.")
            return redirect("core:dashboard")

        promo_code = request.POST.get("promo_code")
        if promo_code is not None:
            success, message = _redeem_promo_code(user=request.user, raw_code=promo_code)
            if success:
                messages.success(request, message)
            else:
                messages.error(request, message)
            return redirect("core:dashboard")

        form = UserProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            if is_ajax:
                return JsonResponse({"status": "ok"})
            return redirect("core:dashboard")
        if is_ajax:
            return JsonResponse(
                {
                    "status": "error",
                    "errors": form.errors.get_json_data(),
                },
                status=400,
            )
    else:
        form = UserProfileForm(instance=profile)

    shorten_used = request.user.generation_requests.filter(kind=GenerationRequest.KIND_SHORTEN).count()
    reply_used = request.user.generation_requests.filter(kind=GenerationRequest.KIND_REPLY).count()
    promo_codes = list(PromoCode.objects.filter(is_active=True).order_by("code"))
    promo_total = sum(promo.max_activations for promo in promo_codes)
    promo_remaining = sum(max(promo.max_activations - promo.activations_count, 0) for promo in promo_codes)
    promo_cooldown = _get_promo_cooldown_info(request.user)
    show_admin_usage = request.user.is_staff
    admin_usage_rows = _build_admin_usage_rows() if show_admin_usage else []

    context = {
        "form": form,
        "current_plan": plan_access.get_plan_display(),
        "is_supporter": plan_access.plan == plan_access.PLAN_SUPPORTER,
        "has_paid_plan": plan_access.plan in {plan_access.PLAN_PRO, plan_access.PLAN_SUPPORTER},
        "purchases": purchases,
        "comment_style_options": [
            {
                "value": "sharp",
                "label": "Sharp",
                "description": "Brief, confident, thesis-focused.",
                "prompt": "Пиши как короткий комментарий в X/Twitter: 1-2 фразы, уверенно, без воды, с четкой позицией и быстрым панчлайном в конце.",
                "display_prompt": "Write like a short X/Twitter comment: 1-2 sentences, confident, clean, with a clear stance and a quick punch at the end.",
            },
            {
                "value": "supportive",
                "label": "Supportive",
                "description": "Friendly and positive.",
                "prompt": "Пиши как доброжелательный комментарий под постом: коротко, тепло, с поддержкой автора или идеи, без лишнего пафоса.",
                "display_prompt": "Write like a kind, supportive comment under a post: short, warm, encouraging toward the author or idea, without empty grandstanding.",
            },
            {
                "value": "curious",
                "label": "With a question",
                "description": "Invites dialogue and keeps the reply open.",
                "prompt": "Пиши как вовлекающий комментарий: короткая реакция плюс уточняющий или провокационный вопрос, который продолжает обсуждение.",
                "display_prompt": "Write like an engaging comment: a short reaction plus a clarifying or provocative question that keeps the discussion going.",
            },
            {
                "value": "expert",
                "label": "Expert",
                "description": "Calm and to the point.",
                "prompt": "Пиши как экспертный комментарий: спокойно, умно, по делу, с ощущением, что автор разбирается в теме и добавляет ценность.",
                "display_prompt": "Write like an expert comment: calm, smart, to the point, with a sense that the author understands the topic and adds value.",
            },
            {
                "value": "ironic",
                "label": "With irony",
                "description": "Light, sharp, no cringe.",
                "prompt": "Пиши как ироничный комментарий для X/Twitter: коротко, цепко, с легкой насмешкой, но без токсичности и перегиба.",
                "display_prompt": "Write like an ironic X/Twitter comment: short, sharp, with light mockery, but without toxicity or overdoing it.",
            },
        ],
        "comment_style_options_json": json.dumps(
            [
                {
                    "id": "sharp",
                    "label": "Sharp",
                    "description": "Brief, confident, thesis-focused.",
                    "prompt": "Пиши как короткий комментарий в X/Twitter: 1-2 фразы, уверенно, без воды, с четкой позицией и быстрым панчлайном в конце.",
                    "display_prompt": "Write like a short X/Twitter comment: 1-2 sentences, confident, clean, with a clear stance and a quick punch at the end.",
                },
                {
                    "id": "supportive",
                    "label": "Supportive",
                    "description": "Friendly and positive.",
                    "prompt": "Пиши как доброжелательный комментарий под постом: коротко, тепло, с поддержкой автора или идеи, без лишнего пафоса.",
                    "display_prompt": "Write like a kind, supportive comment under a post: short, warm, encouraging toward the author or idea, without empty grandstanding.",
                },
                {
                    "id": "curious",
                    "label": "With a question",
                    "description": "Invites dialogue and keeps the reply open.",
                    "prompt": "Пиши как вовлекающий комментарий: короткая реакция плюс уточняющий или провокационный вопрос, который продолжает обсуждение.",
                    "display_prompt": "Write like an engaging comment: a short reaction plus a clarifying or provocative question that keeps the discussion going.",
                },
                {
                    "id": "expert",
                    "label": "Expert",
                    "description": "Calm and to the point.",
                    "prompt": "Пиши как экспертный комментарий: спокойно, умно, по делу, с ощущением, что автор разбирается в теме и добавляет ценность.",
                    "display_prompt": "Write like an expert comment: calm, smart, to the point, with a sense that the author understands the topic and adds value.",
                },
                {
                    "id": "ironic",
                    "label": "With irony",
                    "description": "Light, sharp, no cringe.",
                    "prompt": "Пиши как ироничный комментарий для X/Twitter: коротко, цепко, с легкой насмешкой, но без токсичности и перегиба.",
                    "display_prompt": "Write like an ironic X/Twitter comment: short, sharp, with light mockery, but without toxicity or overdoing it.",
                },
            ]
        ),
        "selected_comment_styles_json": json.dumps(profile.selected_comment_styles),
        "custom_comment_styles_json": json.dumps(profile.custom_comment_styles),
        "preferred_variant_count": profile.preferred_variant_count,
        "promo_total": promo_total,
        "promo_remaining": promo_remaining,
        "promo_percent": int((promo_remaining / promo_total) * 100) if promo_total else 0,
        "promo_cooldown_active": promo_cooldown["active"],
        "reply_used": reply_used,
        "shorten_used": shorten_used,
        "reply_remaining": plan_access.reply_remaining,
        "shorten_remaining": plan_access.shorten_remaining,
        "expires_at": plan_access.expires_at,
        "show_admin_usage": show_admin_usage,
        "admin_usage_rows": admin_usage_rows,
    }
    return render(request, "core/profile.html", context)
