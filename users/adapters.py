from django.contrib.auth import get_user_model
from django.urls import reverse

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter

from .models import generate_random_username


User = get_user_model()


class PiglyAccountAdapter(DefaultAccountAdapter):
    def get_login_redirect_url(self, request):
        return reverse("core:dashboard")


class PiglySocialAccountAdapter(DefaultSocialAccountAdapter):
    def pre_social_login(self, request, sociallogin):
        if sociallogin.is_existing:
            return

        email = (sociallogin.user.email or "").strip().lower()
        if not email:
            return

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return
        sociallogin.connect(request, user)

    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)
        user.email = (user.email or data.get("email") or "").strip().lower()
        if not user.username:
            user.username = generate_random_username()
        return user

    def save_user(self, request, sociallogin, form=None):
        user = super().save_user(request, sociallogin, form=form)
        if not user.username:
            user.username = generate_random_username()
            user.save(update_fields=["username"])
        return user
