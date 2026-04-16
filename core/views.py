import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Max, Q
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from history.models import GenerationRequest
from users.forms import CustomAuthenticationForm, CustomUserCreationForm, UserProfileForm
from users.models import PlanAccess, PromoCode, PromoCodeRedemption, User


PROMO_COOLDOWN_DAYS = 10
ADMIN_GENERATION_BLOCK_CHOICES = (
    ("1", "1h"),
    ("6", "6h"),
    ("24", "24h"),
    ("72", "3d"),
    ("168", "7d"),
)


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


def _dashboard_redirect_with_page(page_number):
    return f"{reverse('core:dashboard')}?admin_page={page_number}"


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


def _build_admin_usage_rows(page_number=1, per_page=8):
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
                "generation_blocked_until": plan_access.generation_blocked_until if plan_access else None,
                "is_generation_blocked": plan_access.is_generation_blocked if plan_access else False,
                "generation_block_choices": ADMIN_GENERATION_BLOCK_CHOICES,
            }
        )
    paginator = Paginator(rows, per_page)
    return paginator.get_page(page_number)


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
    show_welcome_modal = False

    if request.method == "POST":
        admin_plan_user_id = request.POST.get("admin_plan_user_id")
        admin_plan_value = request.POST.get("admin_plan")
        admin_block_user_id = request.POST.get("admin_block_user_id")
        admin_block_hours = request.POST.get("admin_block_hours")
        admin_block_action = request.POST.get("admin_block_action")
        admin_page = request.POST.get("admin_page") or request.GET.get("admin_page") or 1
        if admin_plan_user_id and admin_plan_value and request.user.is_staff:
            target_user = User.objects.filter(pk=admin_plan_user_id).select_related("plan_access").first()
            valid_plans = {choice[0] for choice in PlanAccess.PLAN_CHOICES}
            if not target_user or admin_plan_value not in valid_plans:
                messages.error(request, "Could not update the user plan.")
                return redirect(_dashboard_redirect_with_page(admin_page))
            _apply_plan_access_defaults(target_user.plan_access, admin_plan_value)
            target_user.plan_access.save(update_fields=["plan", "ai_reply_limit", "shorten_limit"])
            messages.success(request, f"Plan updated for {target_user.email}.")
            return redirect(_dashboard_redirect_with_page(admin_page))

        if admin_block_user_id and request.user.is_staff:
            target_user = User.objects.filter(pk=admin_block_user_id).select_related("plan_access").first()
            valid_hours = {value for value, _label in ADMIN_GENERATION_BLOCK_CHOICES}
            if not target_user:
                messages.error(request, "Could not update the generation restriction.")
                return redirect(_dashboard_redirect_with_page(admin_page))

            if admin_block_action == "clear":
                target_user.plan_access.generation_blocked_until = None
                target_user.plan_access.save(update_fields=["generation_blocked_until"])
                messages.success(request, f"Generation restriction cleared for {target_user.email}.")
                return redirect(_dashboard_redirect_with_page(admin_page))

            if admin_block_hours not in valid_hours:
                messages.error(request, "Choose a valid restriction duration.")
                return redirect(_dashboard_redirect_with_page(admin_page))

            blocked_until = timezone.now() + timezone.timedelta(hours=int(admin_block_hours))
            target_user.plan_access.generation_blocked_until = blocked_until
            target_user.plan_access.save(update_fields=["generation_blocked_until"])
            messages.success(
                request,
                f"Generation restricted for {target_user.email} until {blocked_until.strftime('%Y-%m-%d %H:%M')}.",
            )
            return redirect(_dashboard_redirect_with_page(admin_page))

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
        show_welcome_modal = bool(request.session.pop("show_dashboard_welcome", False))

    shorten_used = request.user.generation_requests.filter(kind=GenerationRequest.KIND_SHORTEN).count()
    reply_used = request.user.generation_requests.filter(kind=GenerationRequest.KIND_REPLY).count()
    promo_codes = list(PromoCode.objects.filter(is_active=True).order_by("code"))
    promo_total = sum(promo.max_activations for promo in promo_codes)
    promo_remaining = sum(max(promo.max_activations - promo.activations_count, 0) for promo in promo_codes)
    promo_cooldown = _get_promo_cooldown_info(request.user)
    show_admin_usage = request.user.is_staff
    admin_page = request.GET.get("admin_page", 1)
    admin_usage_page = _build_admin_usage_rows(admin_page) if show_admin_usage else None

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
        "show_welcome_modal": show_welcome_modal,
        "show_admin_usage": show_admin_usage,
        "admin_usage_page": admin_usage_page,
        "admin_usage_rows": admin_usage_page.object_list if admin_usage_page else [],
    }
    return render(request, "core/profile.html", context)
