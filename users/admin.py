from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.db.models import Count, Max, Q
from django.urls import reverse
from django.utils.html import format_html

from .models import (
    ExtensionAccessToken,
    PlanAccess,
    PromoCode,
    PromoCodeRedemption,
    Purchase,
    User,
    UserProfile,
)


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    extra = 0
    fieldsets = (
        (
            "Writing Preferences",
            {
                "fields": (
                    "preferred_language",
                    "preferred_tone",
                    "preferred_translate_language",
                    "preferred_comment_length",
                    "preferred_emoji_mode",
                    "preferred_dash_style",
                    "preferred_terminal_punctuation",
                    "preferred_capitalization",
                    "preferred_comment_styles",
                    "preferred_custom_comment_styles",
                )
            },
        ),
    )


class PlanAccessInline(admin.StackedInline):
    model = PlanAccess
    can_delete = False
    extra = 0
    fieldsets = (
        (
            "Access",
            {
                "fields": (
                    "plan",
                    "ai_reply_limit",
                    "shorten_limit",
                    "created_at",
                )
            },
        ),
    )
    readonly_fields = ("created_at",)


class PurchaseInline(admin.TabularInline):
    model = Purchase
    extra = 0
    fields = ("provider", "plan", "amount_usd", "status", "order_id", "created_at")
    readonly_fields = ("created_at", "order_id")
    ordering = ("-created_at",)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        "email",
        "username",
        "plan_badge",
        "reply_requests_count",
        "shorten_requests_count",
        "total_requests_count",
        "last_generation_at",
        "is_staff",
        "is_active",
    )
    list_filter = ("is_staff", "is_active", "is_superuser", "plan_access__plan")
    ordering = ("email",)
    search_fields = ("email", "username")
    readonly_fields = (
        "last_login",
        "date_joined",
        "admin_stats",
    )
    fieldsets = (
        (None, {"fields": ("email", "username", "password")}),
        (
            "Admin Stats",
            {
                "fields": ("admin_stats",),
            },
        ),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "username", "password1", "password2"),
            },
        ),
    )
    inlines = (PlanAccessInline, UserProfileInline, PurchaseInline)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related("plan_access").annotate(
            reply_requests_total=Count(
                "generation_requests",
                filter=Q(generation_requests__kind="reply"),
            ),
            shorten_requests_total=Count(
                "generation_requests",
                filter=Q(generation_requests__kind="shorten"),
            ),
            generation_requests_total=Count("generation_requests"),
            last_generation_value=Max("generation_requests__created_at"),
        )

    @admin.display(description="Plan", ordering="plan_access__plan")
    def plan_badge(self, obj):
        plan_access = getattr(obj, "plan_access", None)
        if not plan_access:
            return "-"
        colors = {
            PlanAccess.PLAN_FREE: ("#64748b", "#f8fafc", "#cbd5e1"),
            PlanAccess.PLAN_PRO: ("#1d4ed8", "#eff6ff", "#bfdbfe"),
            PlanAccess.PLAN_SUPPORTER: ("#92400e", "#fffbeb", "#fcd34d"),
        }
        fg, bg, border = colors.get(plan_access.plan, ("#111827", "#f8fafc", "#e5e7eb"))
        return format_html(
            '<span style="display:inline-flex;align-items:center;border:1px solid {};background:{};color:{};padding:4px 10px;border-radius:999px;font-weight:600;">{}</span>',
            border,
            bg,
            fg,
            plan_access.get_plan_display(),
        )

    @admin.display(description="Replies", ordering="reply_requests_total")
    def reply_requests_count(self, obj):
        return getattr(obj, "reply_requests_total", 0)

    @admin.display(description="Shortens", ordering="shorten_requests_total")
    def shorten_requests_count(self, obj):
        return getattr(obj, "shorten_requests_total", 0)

    @admin.display(description="Total", ordering="generation_requests_total")
    def total_requests_count(self, obj):
        return getattr(obj, "generation_requests_total", 0)

    @admin.display(description="Last generation", ordering="last_generation_value")
    def last_generation_at(self, obj):
        return getattr(obj, "last_generation_value", None) or "-"

    @admin.display(description="Statistics")
    def admin_stats(self, obj):
        reply_count = obj.generation_requests.filter(kind="reply").count()
        shorten_count = obj.generation_requests.filter(kind="shorten").count()
        purchases_count = obj.purchases.count()
        redemptions_count = obj.promo_redemptions.count()
        last_generation = obj.generation_requests.order_by("-created_at").first()
        history_url = reverse("admin:history_generationrequest_changelist") + f"?user__id__exact={obj.id}"
        purchases_url = reverse("admin:users_purchase_changelist") + f"?user__id__exact={obj.id}"
        redemptions_url = reverse("admin:users_promocoderedemption_changelist") + f"?user__id__exact={obj.id}"
        return format_html(
            """
            <div style="display:grid;grid-template-columns:repeat(2,minmax(220px,1fr));gap:12px;">
                <div style="border:1px solid #e5e7eb;border-radius:16px;padding:14px;">
                    <div style="font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:.08em;">Generation stats</div>
                    <div style="margin-top:8px;font-size:14px;"><strong>Replies:</strong> {}</div>
                    <div style="font-size:14px;"><strong>Shortens:</strong> {}</div>
                    <div style="font-size:14px;"><strong>Total:</strong> {}</div>
                    <div style="font-size:14px;"><strong>Last request:</strong> {}</div>
                    <div style="margin-top:10px;"><a href="{}">Open generation history</a></div>
                </div>
                <div style="border:1px solid #e5e7eb;border-radius:16px;padding:14px;">
                    <div style="font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:.08em;">Commerce stats</div>
                    <div style="margin-top:8px;font-size:14px;"><strong>Purchases:</strong> {}</div>
                    <div style="font-size:14px;"><strong>Promo activations:</strong> {}</div>
                    <div style="margin-top:10px;"><a href="{}">Open purchases</a></div>
                    <div style="margin-top:6px;"><a href="{}">Open promo activations</a></div>
                </div>
            </div>
            """,
            reply_count,
            shorten_count,
            reply_count + shorten_count,
            last_generation.created_at.strftime("%Y-%m-%d %H:%M") if last_generation else "No activity yet",
            history_url,
            purchases_count,
            redemptions_count,
            purchases_url,
            redemptions_url,
        )


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "preferred_language", "preferred_tone", "preferred_translate_language")
    search_fields = ("user__email", "user__username")


@admin.register(PlanAccess)
class PlanAccessAdmin(admin.ModelAdmin):
    list_display = ("user", "plan", "ai_reply_limit", "shorten_limit", "reply_remaining", "shorten_remaining", "created_at")
    list_filter = ("plan", "created_at")
    search_fields = ("user__email", "user__username")
    list_editable = ("plan", "ai_reply_limit", "shorten_limit")


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ("user", "provider", "plan", "amount_usd", "status", "provider_invoice_id", "created_at")
    list_filter = ("provider", "plan", "status", "created_at")
    search_fields = ("user__email", "user__username", "order_id", "provider_payment_id", "provider_invoice_id", "tx_hash")


@admin.register(ExtensionAccessToken)
class ExtensionAccessTokenAdmin(admin.ModelAdmin):
    list_display = ("user", "masked_token", "rotated_at", "last_used_at")
    readonly_fields = ("token", "created_at", "rotated_at", "last_used_at")
    search_fields = ("user__email", "user__username", "token")


@admin.register(PromoCode)
class PromoCodeAdmin(admin.ModelAdmin):
    list_display = ("code", "plan", "duration_days", "max_activations", "activations_count", "is_active")
    list_filter = ("plan", "is_active")
    search_fields = ("code",)
    list_editable = ("plan", "duration_days", "max_activations", "is_active")


@admin.register(PromoCodeRedemption)
class PromoCodeRedemptionAdmin(admin.ModelAdmin):
    list_display = ("promo_code", "user", "granted_until", "created_at")
    list_filter = ("promo_code", "created_at")
    search_fields = ("promo_code__code", "user__email", "user__username")


admin.site.site_header = "Pigly Admin"
admin.site.site_title = "Pigly Admin"
admin.site.index_title = "Dashboard"
