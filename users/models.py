import random
import secrets
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


USERNAME_FIRST_WORDS = (
    "amber", "brisk", "calm", "clever", "cosmic", "daring", "echo", "ember",
    "fancy", "frost", "gentle", "glimmer", "golden", "jolly", "lucky", "mellow",
    "misty", "neon", "nimble", "nova", "pixel", "quiet", "rapid", "sly",
    "solar", "spark", "steady", "stormy", "sunny", "swift", "vivid", "wild",
)

USERNAME_SECOND_WORDS = (
    "badger", "bear", "beetle", "bunny", "comet", "falcon", "ferret", "firefly",
    "fox", "gecko", "hawk", "koala", "lemur", "lynx", "moose", "otter",
    "owl", "panda", "phoenix", "pilot", "rabbit", "raven", "rocket", "seal",
    "shark", "sprite", "star", "tiger", "turtle", "whale", "wolf", "yak",
)


class User(AbstractUser):
    email = models.EmailField(unique=True)
    username = models.CharField(max_length=150, unique=True, blank=True, null=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    def __str__(self):
        return self.email


def generate_random_username():
    for _ in range(128):
        candidate = (
            f"{random.choice(USERNAME_FIRST_WORDS)}"
            f"{random.choice(USERNAME_SECOND_WORDS)}"
            f"{random.randint(10, 99)}"
        )
        if not User.objects.filter(username__iexact=candidate).exists():
            return candidate
    return f"user{random.randint(100000, 999999)}"


class UserProfile(models.Model):
    SHORTEN_TRIGGER_MIN = 1
    SHORTEN_TRIGGER_MAX = 10000
    SHORTEN_TRIGGER_DEFAULT = 200

    VARIANT_ONE = 1
    VARIANT_TWO = 2
    VARIANT_THREE = 3
    VARIANT_COUNT_CHOICES = (
        (VARIANT_ONE, "1"),
        (VARIANT_TWO, "2"),
        (VARIANT_THREE, "3"),
    )

    TRANSLATE_NONE = ""
    TRANSLATE_ENGLISH = "en"
    TRANSLATE_RUSSIAN = "ru"
    TRANSLATE_CHINESE = "zh"
    TRANSLATE_CHOICES = (
        (TRANSLATE_NONE, "Not selected"),
        (TRANSLATE_ENGLISH, "English"),
        (TRANSLATE_RUSSIAN, "Russian"),
        (TRANSLATE_CHINESE, "Chinese"),
    )

    STYLE_SHARP = "sharp"
    STYLE_SUPPORTIVE = "supportive"
    STYLE_CURIOUS = "curious"
    STYLE_EXPERT = "expert"
    STYLE_IRONIC = "ironic"
    COMMENT_STYLE_CHOICES = (
        (STYLE_SHARP, "Sharp"),
        (STYLE_SUPPORTIVE, "Supportive"),
        (STYLE_CURIOUS, "With a question"),
        (STYLE_EXPERT, "Expert"),
        (STYLE_IRONIC, "With irony"),
    )

    LENGTH_SHORT = "short"
    LENGTH_MEDIUM = "medium"
    LENGTH_LONG = "long"
    LENGTH_MIX = "mix"
    LENGTH_CHOICES = (
        (LENGTH_SHORT, "Short"),
        (LENGTH_MEDIUM, "Medium"),
        (LENGTH_LONG, "Long"),
        (LENGTH_MIX, "Mix"),
    )

    EMOJI_NONE = "none"
    EMOJI_MODERATE = "moderate"
    EMOJI_MANY = "many"
    EMOJI_MIX = "mix"
    EMOJI_CHOICES = (
        (EMOJI_NONE, "None"),
        (EMOJI_MODERATE, "Moderate"),
        (EMOJI_MANY, "Many"),
        (EMOJI_MIX, "Mix"),
    )

    DASH_HYPHEN = "hyphen"
    DASH_NDASH = "ndash"
    DASH_MDASH = "mdash"
    DASH_CHOICES = (
        (DASH_HYPHEN, "Hyphen -"),
        (DASH_NDASH, "En dash -"),
        (DASH_MDASH, "Em dash -"),
    )

    PUNCT_NONE = "none"
    PUNCT_KEEP = "keep"
    PUNCT_MIX = "mix"
    PUNCT_CHOICES = (
        (PUNCT_NONE, "No period"),
        (PUNCT_KEEP, "Keep"),
        (PUNCT_MIX, "Mix"),
    )

    CAPS_UPPER = "upper"
    CAPS_PRESERVE = "preserve"
    CAPS_MIX = "mix"
    CAPS_CHOICES = (
        (CAPS_UPPER, "Uppercase"),
        (CAPS_PRESERVE, "Preserve"),
        (CAPS_MIX, "Mix"),
    )

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    preferred_language = models.CharField(max_length=8, default="ru")
    preferred_tone = models.CharField(max_length=32, default="friendly")
    preferred_comment_styles = models.JSONField(default=list, blank=True)
    preferred_custom_comment_styles = models.JSONField(default=list, blank=True)
    preferred_variant_count = models.PositiveSmallIntegerField(choices=VARIANT_COUNT_CHOICES, default=VARIANT_THREE)
    preferred_translate_language = models.CharField(max_length=8, choices=TRANSLATE_CHOICES, default="", blank=True)
    preferred_comment_length = models.CharField(max_length=16, choices=LENGTH_CHOICES, default=LENGTH_MIX)
    preferred_emoji_mode = models.CharField(max_length=16, choices=EMOJI_CHOICES, default=EMOJI_MODERATE)
    preferred_dash_style = models.CharField(max_length=16, choices=DASH_CHOICES, default=DASH_NDASH)
    preferred_terminal_punctuation = models.CharField(max_length=16, choices=PUNCT_CHOICES, default=PUNCT_NONE)
    preferred_capitalization = models.CharField(max_length=16, choices=CAPS_CHOICES, default=CAPS_UPPER)
    preferred_shorten_trigger_length = models.PositiveIntegerField(default=SHORTEN_TRIGGER_DEFAULT)
    preferred_inline_translate_enabled = models.BooleanField(default=False)

    def __str__(self):
        return f"Profile for {self.user.email}"

    @property
    def selected_comment_styles(self):
        valid_builtin_ids = set(dict(self.COMMENT_STYLE_CHOICES))
        valid_custom_ids = {item["id"] for item in self.custom_comment_styles}
        styles = [
            value
            for value in (self.preferred_comment_styles or [])
            if value in valid_builtin_ids or value in valid_custom_ids
        ]
        return styles or [self.STYLE_SUPPORTIVE]

    @property
    def custom_comment_styles(self):
        items = []
        for style in self.preferred_custom_comment_styles or []:
            if not isinstance(style, dict):
                continue
            style_id = str(style.get("id") or "").strip()
            label = str(style.get("label") or "").strip()
            prompt = str(style.get("prompt") or "").strip()
            description = str(style.get("description") or "").strip()
            if style_id.startswith("custom-") and label and prompt:
                items.append(
                    {
                        "id": style_id,
                        "label": label[:32],
                        "prompt": prompt[:800],
                        "description": description[:160],
                    }
                )
        return items

    @classmethod
    def map_style_to_tone(cls, style):
        mapping = {
            cls.STYLE_SHARP: "concise",
            cls.STYLE_SUPPORTIVE: "friendly",
            cls.STYLE_CURIOUS: "friendly",
            cls.STYLE_EXPERT: "neutral",
            cls.STYLE_IRONIC: "confident",
        }
        return mapping.get(style, "friendly")

    @classmethod
    def normalize_shorten_trigger_length(cls, value):
        try:
            normalized = int(value)
        except (TypeError, ValueError):
            return cls.SHORTEN_TRIGGER_DEFAULT
        return max(cls.SHORTEN_TRIGGER_MIN, min(cls.SHORTEN_TRIGGER_MAX, normalized))


class PlanAccess(models.Model):
    PLAN_FREE = "free"
    PLAN_PRO = "pro"
    PLAN_SUPPORTER = "supporter"
    PLAN_CHOICES = (
        (PLAN_FREE, "Free"),
        (PLAN_PRO, "Pro"),
        (PLAN_SUPPORTER, "Supporter"),
    )

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="plan_access")
    plan = models.CharField(max_length=16, choices=PLAN_CHOICES, default=PLAN_FREE)
    ai_reply_limit = models.PositiveIntegerField(default=30)
    shorten_limit = models.PositiveIntegerField(default=30)
    generation_blocked_until = models.DateTimeField(blank=True, null=True)
    expires_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.email} - {self.plan}"

    def remaining_for_kind(self, kind):
        if kind == "reply":
            limit = self.ai_reply_limit
        elif kind == "shorten":
            limit = self.shorten_limit
        else:
            return None
        if limit <= 0:
            return None
        used = self.user.generation_requests.filter(kind=kind).count()
        return max(limit - used, 0)

    @property
    def is_generation_blocked(self):
        return bool(self.generation_blocked_until and self.generation_blocked_until > timezone.now())

    @property
    def reply_remaining(self):
        return self.remaining_for_kind("reply")

    @property
    def shorten_remaining(self):
        return self.remaining_for_kind("shorten")


class Purchase(models.Model):
    PROVIDER_MANUAL = "manual"
    PROVIDER_NOWPAYMENTS = "nowpayments"
    PROVIDER_WALLET = "wallet"
    PROVIDER_CHOICES = (
        (PROVIDER_MANUAL, "Manual"),
        (PROVIDER_NOWPAYMENTS, "NOWPayments"),
        (PROVIDER_WALLET, "Wallet"),
    )

    STATUS_PENDING = "pending"
    STATUS_CREATED = "created"
    STATUS_WAITING = "waiting"
    STATUS_PAID = "paid"
    STATUS_CONFIRMED = "confirmed"
    STATUS_FINISHED = "finished"
    STATUS_CANCELLED = "cancelled"
    STATUS_FAILED = "failed"
    STATUS_EXPIRED = "expired"
    STATUS_REFUNDED = "refunded"
    STATUS_CREATE_FAILED = "create_failed"
    STATUS_WALLET_WAITING = "wallet_waiting"
    STATUS_WALLET_CONFIRMED = "wallet_confirmed"
    STATUS_WALLET_FAILED = "wallet_failed"
    STATUS_WALLET_REJECTED = "wallet_rejected"
    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_CREATED, "Created"),
        (STATUS_WAITING, "Waiting"),
        (STATUS_PAID, "Paid"),
        (STATUS_CONFIRMED, "Confirmed"),
        (STATUS_FINISHED, "Finished"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_FAILED, "Failed"),
        (STATUS_EXPIRED, "Expired"),
        (STATUS_REFUNDED, "Refunded"),
        (STATUS_CREATE_FAILED, "Create failed"),
        (STATUS_WALLET_WAITING, "Wallet waiting"),
        (STATUS_WALLET_CONFIRMED, "Wallet confirmed"),
        (STATUS_WALLET_FAILED, "Wallet failed"),
        (STATUS_WALLET_REJECTED, "Wallet rejected"),
    )

    PAID_STATUSES = {STATUS_PAID, STATUS_CONFIRMED, STATUS_FINISHED, STATUS_WALLET_CONFIRMED}
    CANCELLED_STATUSES = {
        STATUS_CANCELLED,
        STATUS_FAILED,
        STATUS_EXPIRED,
        STATUS_REFUNDED,
        STATUS_CREATE_FAILED,
        STATUS_WALLET_FAILED,
        STATUS_WALLET_REJECTED,
    }

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="purchases")
    plan = models.CharField(max_length=16, choices=PlanAccess.PLAN_CHOICES, default=PlanAccess.PLAN_PRO)
    amount_usd = models.DecimalField(max_digits=10, decimal_places=2)
    provider = models.CharField(max_length=24, choices=PROVIDER_CHOICES, default=PROVIDER_MANUAL)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_PENDING)
    order_id = models.CharField(max_length=100, blank=True, db_index=True)
    provider_payment_id = models.CharField(max_length=100, blank=True)
    provider_invoice_id = models.CharField(max_length=100, blank=True)
    invoice_url = models.URLField(blank=True)
    amount_crypto = models.DecimalField(max_digits=20, decimal_places=10, null=True, blank=True)
    currency = models.CharField(max_length=16, blank=True)
    network = models.CharField(max_length=32, blank=True)
    tx_hash = models.CharField(max_length=255, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.user.email} - {self.plan} - {self.status}"

    @property
    def is_paid(self):
        return self.status in self.PAID_STATUSES

    @property
    def ui_status(self):
        if self.status in self.PAID_STATUSES:
            return "paid"
        if self.status in self.CANCELLED_STATUSES:
            return "cancelled"
        return "pending"

    @property
    def ui_status_label(self):
        labels = {
            "paid": "Paid",
            "cancelled": "Cancelled",
            "pending": "Pending",
        }
        return labels[self.ui_status]

    @property
    def amount_crypto_display(self):
        if self.amount_crypto is None:
            return ""
        normalized = Decimal(self.amount_crypto).normalize()
        return format(normalized, "f")


class PromoCode(models.Model):
    code = models.CharField(max_length=64, unique=True)
    plan = models.CharField(max_length=16, choices=PlanAccess.PLAN_CHOICES, default=PlanAccess.PLAN_PRO)
    duration_days = models.PositiveIntegerField(default=30)
    max_activations = models.PositiveIntegerField(default=1)
    activations_count = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return self.code


class PromoCodeRedemption(models.Model):
    promo_code = models.ForeignKey(PromoCode, on_delete=models.CASCADE, related_name="redemptions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="promo_redemptions")
    granted_until = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("promo_code", "user")

    def __str__(self):
        return f"{self.promo_code.code} -> {self.user.email}"


def generate_extension_token():
    return f"{settings.EXTENSION_TOKEN_PREFIX}{secrets.token_urlsafe(24)}"


class ExtensionAccessToken(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="extension_access")
    token = models.CharField(max_length=128, unique=True, default=generate_extension_token)
    created_at = models.DateTimeField(auto_now_add=True)
    rotated_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f"Extension token for {self.user.email}"

    @property
    def masked_token(self):
        if len(self.token) <= 10:
            return self.token
        return f"{self.token[:8]}...{self.token[-4:]}"

    def rotate(self):
        self.token = generate_extension_token()
        self.rotated_at = timezone.now()
        self.save(update_fields=["token", "rotated_at"])
        return self.token
