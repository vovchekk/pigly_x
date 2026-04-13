from types import SimpleNamespace
from unittest.mock import Mock

from django.test import TestCase
from django.urls import reverse

from users.adapters import PiglySocialAccountAdapter
from users.models import ExtensionAccessToken, PromoCode, PromoCodeRedemption, Purchase, User


class DashboardTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="dashboard@example.com",
            username="dashboard-user",
            password="pass12345",
        )
        self.client.force_login(self.user)

    def test_dashboard_renders_clean_utf8_content(self):
        response = self.client.get(reverse("core:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dashboard")
        self.assertContains(response, "Comment writing settings")
        self.assertContains(response, "Payment history")
        self.assertContains(response, "Current privilege")

    def test_dashboard_updates_profile_defaults(self):
        response = self.client.post(
            reverse("core:dashboard"),
            data={
                "preferred_language": "en",
                "preferred_tone": "neutral",
                "preferred_comment_styles_json": "[\"expert\", \"ironic\"]",
                "preferred_custom_comment_styles_json": "[]",
                "preferred_translate_language": "en",
                "preferred_comment_length": "medium",
                "preferred_emoji_mode": "none",
                "preferred_dash_style": "hyphen",
                "preferred_terminal_punctuation": "keep",
                "preferred_capitalization": "preserve",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.preferred_language, "en")
        self.assertEqual(self.user.profile.preferred_tone, "neutral")
        self.assertEqual(self.user.profile.preferred_comment_styles, ["expert", "ironic"])
        self.assertEqual(self.user.profile.preferred_translate_language, "en")
        self.assertEqual(self.user.profile.preferred_comment_length, "medium")
        self.assertEqual(self.user.profile.preferred_emoji_mode, "none")
        self.assertEqual(self.user.profile.preferred_dash_style, "hyphen")
        self.assertEqual(self.user.profile.preferred_terminal_punctuation, "keep")
        self.assertEqual(self.user.profile.preferred_capitalization, "preserve")

    def test_dashboard_shows_payment_history(self):
        Purchase.objects.create(user=self.user, plan="pro", amount_usd="12.00", status="paid")

        response = self.client.get(reverse("core:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Payment history")
        self.assertContains(response, "$12.00")

    def test_dashboard_redeems_promo_code(self):
        PromoCode.objects.create(code="BROSKILUDOSKI", plan="pro", duration_days=30, max_activations=5)

        response = self.client.post(reverse("core:dashboard"), data={"promo_code": "BROSKILUDOSKI"}, follow=True)

        self.assertEqual(response.status_code, 200)
        self.user.plan_access.refresh_from_db()
        self.assertEqual(self.user.plan_access.plan, "pro")
        self.assertEqual(self.user.plan_access.ai_reply_limit, 0)
        self.assertEqual(self.user.plan_access.shorten_limit, 0)
        self.assertEqual(PromoCodeRedemption.objects.filter(user=self.user).count(), 1)

    def test_dashboard_requires_at_least_one_style(self):
        response = self.client.post(
            reverse("core:dashboard"),
            data={
                "preferred_language": "en",
                "preferred_tone": "neutral",
                "preferred_comment_styles_json": "[]",
                "preferred_custom_comment_styles_json": "[]",
                "preferred_translate_language": "",
                "preferred_comment_length": "mix",
                "preferred_emoji_mode": "moderate",
                "preferred_dash_style": "ndash",
                "preferred_terminal_punctuation": "none",
                "preferred_capitalization": "upper",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Select at least one style.")


class PublicAuthUiTests(TestCase):
    def test_login_page_is_google_only(self):
        response = self.client.get(reverse("users:login"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Continue with Google")
        self.assertNotContains(response, 'type="password"', html=False)
        self.assertNotContains(response, "No account yet?")

    def test_register_page_is_google_only(self):
        response = self.client.get(reverse("users:register"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Continue with Google")
        self.assertNotContains(response, "password_confirm", html=False)
        self.assertNotContains(response, 'type="password"', html=False)


class ExtensionSessionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="session@example.com",
            username="session-user",
            password="pass12345",
        )
        self.client.force_login(self.user)

    def test_session_endpoint_returns_extension_token(self):
        response = self.client.get(reverse("users_api:session"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["auth"]["method"], "session")
        self.assertIn("extension_token", payload)
        self.assertEqual(payload["user"]["email"], self.user.email)

    def test_rotate_endpoint_reissues_extension_token(self):
        initial = ExtensionAccessToken.objects.create(user=self.user)
        previous_token = initial.token

        response = self.client.post(reverse("users_api:extension_token_rotate"))

        self.assertEqual(response.status_code, 200)
        initial.refresh_from_db()
        self.assertNotEqual(previous_token, initial.token)
        self.assertEqual(initial.token, response.json()["extension_token"])


class GoogleAdapterTests(TestCase):
    def test_existing_user_is_connected_by_email(self):
        user = User.objects.create_user(
            email="google@example.com",
            username="google-user",
            password="pass12345",
        )
        sociallogin = SimpleNamespace(
            is_existing=False,
            user=SimpleNamespace(email=user.email),
            connect=Mock(),
        )

        PiglySocialAccountAdapter().pre_social_login(request=None, sociallogin=sociallogin)

        sociallogin.connect.assert_called_once_with(None, user)
