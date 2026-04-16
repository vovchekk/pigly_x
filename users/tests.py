import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from users.adapters import PiglyAccountAdapter, PiglySocialAccountAdapter
from users.billing import nowpayments_signature
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
        self.assertContains(response, "Upgrade plan")

    def test_dashboard_updates_profile_defaults(self):
        response = self.client.post(
            reverse("core:dashboard"),
            data={
                "preferred_language": "en",
                "preferred_tone": "neutral",
                "preferred_comment_styles_json": "[\"expert\", \"ironic\"]",
                "preferred_custom_comment_styles_json": "[]",
                "preferred_variant_count": "3",
                "preferred_translate_language": "en",
                "preferred_comment_length": "medium",
                "preferred_emoji_mode": "none",
                "preferred_dash_style": "hyphen",
                "preferred_terminal_punctuation": "keep",
                "preferred_capitalization": "preserve",
                "preferred_shorten_trigger_length": 420,
                "preferred_inline_translate_enabled": "on",
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
        self.assertEqual(self.user.profile.preferred_shorten_trigger_length, 200)
        self.assertTrue(self.user.profile.preferred_inline_translate_enabled)

    def test_dashboard_shows_payment_history(self):
        Purchase.objects.create(user=self.user, plan="pro", amount_usd="12.00", status="paid")

        response = self.client.get(reverse("core:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Payment history")
        self.assertContains(response, "$12.00")

    def test_dashboard_shows_welcome_modal_once_when_session_flag_is_set(self):
        session = self.client.session
        session["show_dashboard_welcome"] = True
        session.save()

        first_response = self.client.get(reverse("core:dashboard"))
        second_response = self.client.get(reverse("core:dashboard"))

        self.assertEqual(first_response.status_code, 200)
        self.assertContains(first_response, "You're in")
        self.assertContains(first_response, "Let's go")
        self.assertEqual(second_response.status_code, 200)
        self.assertNotContains(second_response, "showWelcomeModal: true")

    def test_dashboard_redeems_promo_code(self):
        PromoCode.objects.create(code="BROSKILUDOSKI-TEST", plan="pro", duration_days=30, max_activations=5)

        response = self.client.post(reverse("core:dashboard"), data={"promo_code": "BROSKILUDOSKI-TEST"}, follow=True)

        self.assertEqual(response.status_code, 200)
        self.user.plan_access.refresh_from_db()
        self.assertEqual(self.user.plan_access.plan, "pro")
        self.assertEqual(self.user.plan_access.ai_reply_limit, 0)
        self.assertEqual(self.user.plan_access.shorten_limit, 0)
        self.assertEqual(PromoCodeRedemption.objects.filter(user=self.user).count(), 1)

    def test_dashboard_requires_at_least_one_style(self):
        original_styles = list(self.user.profile.preferred_comment_styles)
        response = self.client.post(
            reverse("core:dashboard"),
            data={
                "preferred_language": "en",
                "preferred_tone": "neutral",
                "preferred_comment_styles_json": "[]",
                "preferred_custom_comment_styles_json": "[]",
                "preferred_variant_count": "3",
                "preferred_translate_language": "",
                "preferred_comment_length": "mix",
                "preferred_emoji_mode": "moderate",
                "preferred_dash_style": "ndash",
                "preferred_terminal_punctuation": "none",
                "preferred_capitalization": "upper",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.preferred_comment_styles, original_styles)

    def test_staff_can_set_temporary_generation_restriction_from_dashboard(self):
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        target = User.objects.create_user(
            email="blocked@example.com",
            username="blocked-user",
            password="pass12345",
        )

        response = self.client.post(
            reverse("core:dashboard"),
            data={
                "admin_block_user_id": str(target.id),
                "admin_block_hours": "24",
                "admin_page": "1",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        target.plan_access.refresh_from_db()
        self.assertIsNotNone(target.plan_access.generation_blocked_until)
        self.assertGreater(target.plan_access.generation_blocked_until, timezone.now())

    def test_staff_can_clear_temporary_generation_restriction_from_dashboard(self):
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        target = User.objects.create_user(
            email="unblocked@example.com",
            username="unblocked-user",
            password="pass12345",
        )
        target.plan_access.generation_blocked_until = timezone.now() + timezone.timedelta(hours=6)
        target.plan_access.save(update_fields=["generation_blocked_until"])

        response = self.client.post(
            reverse("core:dashboard"),
            data={
                "admin_block_user_id": str(target.id),
                "admin_block_action": "clear",
                "admin_page": "1",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        target.plan_access.refresh_from_db()
        self.assertIsNone(target.plan_access.generation_blocked_until)


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

    def test_register_page_preserves_checkout_next_for_google_login(self):
        response = self.client.get(f"{reverse('users:register')}?intent=checkout&plan=pro&next=/%3Fcheckout%3Dpro%23pricing")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "next=%2F%3Fcheckout%3Dpro%23pricing")
        self.assertContains(response, "authCheckoutLead")


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
        self.assertEqual(payload["defaults"]["shorten_trigger_length"], 200)
        self.assertFalse(payload["defaults"]["translate_enabled"])

    def test_session_endpoint_includes_custom_comment_styles(self):
        self.user.profile.preferred_comment_styles = ["supportive", "custom-test"]
        self.user.profile.preferred_custom_comment_styles = [
            {
                "id": "custom-test",
                "label": "Test",
                "prompt": "Write like test.",
                "description": "ttt",
            }
        ]
        self.user.profile.save(update_fields=["preferred_comment_styles", "preferred_custom_comment_styles"])

        response = self.client.get(reverse("users_api:session"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["defaults"]["comment_styles"], ["supportive", "custom-test"])
        self.assertEqual(payload["defaults"]["custom_comment_styles"][0]["id"], "custom-test")

    def test_profile_update_accepts_shorten_trigger_length(self):
        response = self.client.post(
            reverse("users_api:profile_update"),
            data=json.dumps({"shorten_trigger_length": 420}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.preferred_shorten_trigger_length, 420)
        self.assertEqual(response.json()["defaults"]["shorten_trigger_length"], 420)

    def test_profile_update_preserves_custom_comment_style_ids(self):
        self.user.profile.preferred_custom_comment_styles = [
            {
                "id": "custom-test",
                "label": "Test",
                "prompt": "Write like test.",
                "description": "ttt",
            }
        ]
        self.user.profile.save(update_fields=["preferred_custom_comment_styles"])

        response = self.client.post(
            reverse("users_api:profile_update"),
            data=json.dumps({"comment_styles": ["supportive", "custom-test"]}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.preferred_comment_styles, ["supportive", "custom-test"])
        self.assertEqual(response.json()["defaults"]["comment_styles"], ["supportive", "custom-test"])

    def test_profile_update_accepts_translate_enabled(self):
        response = self.client.post(
            reverse("users_api:profile_update"),
            data=json.dumps({"translate_enabled": True}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.user.profile.refresh_from_db()
        self.assertTrue(self.user.profile.preferred_inline_translate_enabled)
        self.assertTrue(response.json()["defaults"]["translate_enabled"])

    def test_rotate_endpoint_reissues_extension_token(self):
        initial = ExtensionAccessToken.objects.create(user=self.user)
        previous_token = initial.token

        response = self.client.post(reverse("users_api:extension_token_rotate"))

        self.assertEqual(response.status_code, 200)
        initial.refresh_from_db()
        self.assertNotEqual(previous_token, initial.token)
        self.assertEqual(initial.token, response.json()["extension_token"])


class GoogleAdapterTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

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

    def test_account_adapter_prefers_safe_next_redirect(self):
        request = self.factory.get("/accounts/google/login/callback/", {"next": "/?checkout=pro#pricing"}, HTTP_HOST="testserver")

        redirect_url = PiglyAccountAdapter().get_login_redirect_url(request)

        self.assertEqual(redirect_url, "/?checkout=pro#pricing")


class NowPaymentsCheckoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="payer@example.com",
            username="payer",
            password="secret12345",
        )
        self.client.force_login(self.user)

    @override_settings(
        NOWPAYMENTS_API_KEY="api-key",
        NOWPAYMENTS_IPN_SECRET="ipn-secret",
        NOWPAYMENTS_API_BASE_URL="https://api.nowpayments.io",
        SITE_URL="https://pigly.example",
    )
    @patch("core.payment_views.requests.post")
    def test_create_invoice_returns_nowpayments_invoice_url(self, post_mock):
        response_mock = Mock()
        response_mock.raise_for_status.return_value = None
        response_mock.json.return_value = {
            "id": "invoice-123",
            "invoice_url": "https://nowpayments.io/payment/?iid=invoice-123",
            "status": "waiting",
        }
        post_mock.return_value = response_mock

        response = self.client.post(reverse("core:pricing_create_payment"), {"plan": "pro"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["invoice_url"], "https://nowpayments.io/payment/?iid=invoice-123")
        purchase = Purchase.objects.get(user=self.user)
        self.assertEqual(purchase.plan, "pro")
        self.assertEqual(purchase.provider, Purchase.PROVIDER_NOWPAYMENTS)
        self.assertEqual(purchase.amount_usd, 2)
        self.assertEqual(purchase.provider_invoice_id, "invoice-123")
        self.assertEqual(purchase.status, "waiting")
        sent_payload = post_mock.call_args.kwargs["json"]
        self.assertEqual(sent_payload["price_amount"], "2.00")
        self.assertEqual(sent_payload["ipn_callback_url"], "https://pigly.example/payments/nowpayments/ipn/")

    @override_settings(NOWPAYMENTS_API_KEY="", NOWPAYMENTS_IPN_SECRET="ipn-secret")
    def test_create_invoice_requires_nowpayments_settings(self):
        response = self.client.post(reverse("core:pricing_create_payment"), {"plan": "pro"})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"], "nowpayments_not_configured")


class NowPaymentsIpnTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="ipn-payer@example.com",
            username="ipnpayer",
            password="secret12345",
        )
        self.purchase = Purchase.objects.create(
            user=self.user,
            plan="pro",
            provider=Purchase.PROVIDER_NOWPAYMENTS,
            order_id="pigly-test-order",
            amount_usd=2,
            status="waiting",
        )

    @override_settings(NOWPAYMENTS_IPN_SECRET="ipn-secret")
    def test_finished_ipn_activates_subscription(self):
        payload = {
            "order_id": "pigly-test-order",
            "payment_id": 123456,
            "payment_status": "finished",
            "actually_paid": "2.10",
        }
        signature = nowpayments_signature(payload)

        response = self.client.post(
            reverse("core:nowpayments_ipn"),
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_NOWPAYMENTS_SIG=signature,
        )

        self.assertEqual(response.status_code, 200)
        self.purchase.refresh_from_db()
        self.user.plan_access.refresh_from_db()
        self.assertEqual(self.purchase.status, "finished")
        self.assertEqual(self.purchase.provider_payment_id, "123456")
        self.assertEqual(self.user.plan_access.plan, "pro")
        self.assertGreater(self.user.plan_access.expires_at, timezone.now())

    @override_settings(NOWPAYMENTS_IPN_SECRET="ipn-secret")
    def test_ipn_rejects_bad_signature(self):
        payload = {
            "order_id": "pigly-test-order",
            "payment_id": 123456,
            "payment_status": "finished",
        }

        response = self.client.post(
            reverse("core:nowpayments_ipn"),
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_NOWPAYMENTS_SIG="bad-signature",
        )

        self.assertEqual(response.status_code, 400)
        self.user.plan_access.refresh_from_db()
        self.assertEqual(self.user.plan_access.plan, "free")

    @override_settings(NOWPAYMENTS_IPN_SECRET="ipn-secret")
    def test_repeated_finished_ipn_does_not_extend_subscription_twice(self):
        payload = {
            "order_id": "pigly-test-order",
            "payment_id": 123456,
            "payment_status": "finished",
        }
        signature = nowpayments_signature(payload)

        first_response = self.client.post(
            reverse("core:nowpayments_ipn"),
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_NOWPAYMENTS_SIG=signature,
        )
        self.assertEqual(first_response.status_code, 200)
        self.user.plan_access.refresh_from_db()
        first_expiry = self.user.plan_access.expires_at

        second_response = self.client.post(
            reverse("core:nowpayments_ipn"),
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_NOWPAYMENTS_SIG=signature,
        )

        self.assertEqual(second_response.status_code, 200)
        self.user.plan_access.refresh_from_db()
        self.assertEqual(self.user.plan_access.expires_at, first_expiry)


class WalletPaymentTests(TestCase):
    receiver = "0x1111111111111111111111111111111111111111"
    payer = "0x2222222222222222222222222222222222222222"
    tx_hash = "0x" + "a" * 64

    def setUp(self):
        self.user = User.objects.create_user(
            email="wallet-payer@example.com",
            username="walletpayer",
            password="secret12345",
        )
        self.client.force_login(self.user)

    @override_settings(WEB3_PAYMENT_RECEIVER_ADDRESS="")
    def test_create_wallet_payment_requires_receiver_address(self):
        response = self.client.post(
            reverse("core:pricing_create_wallet_payment"),
            {"plan": "pro", "network": "base", "payer_address": self.payer},
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"], "web3_receiver_not_configured")

    @override_settings(WEB3_PAYMENT_RECEIVER_ADDRESS=receiver)
    def test_create_wallet_payment_returns_transfer_details(self):
        response = self.client.post(
            reverse("core:pricing_create_wallet_payment"),
            {"plan": "pro", "network": "base", "payer_address": self.payer},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["amount_units"], "2000000")
        self.assertEqual(data["receiver_address"], self.receiver.lower())
        self.assertEqual(data["chain"]["key"], "base")
        purchase = Purchase.objects.get(pk=data["payment_id"])
        self.assertEqual(purchase.status, Purchase.STATUS_WALLET_WAITING)

    @override_settings(WEB3_PAYMENT_RECEIVER_ADDRESS=receiver)
    def test_create_wallet_payment_supports_ethereum_mainnet(self):
        response = self.client.post(
            reverse("core:pricing_create_wallet_payment"),
            {"plan": "pro", "network": "ethereum", "payer_address": self.payer},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["chain"]["key"], "ethereum")
        self.assertEqual(data["chain"]["chain_id"], 1)
        self.assertEqual(data["token_address"], "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48")

    @override_settings(WEB3_PAYMENT_RECEIVER_ADDRESS=receiver)
    def test_create_wallet_payment_supports_abstract(self):
        response = self.client.post(
            reverse("core:pricing_create_wallet_payment"),
            {"plan": "pro", "network": "abstract", "payer_address": self.payer},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["chain"]["key"], "abstract")
        self.assertEqual(data["chain"]["chain_id"], 2741)
        self.assertEqual(data["chain"]["chain_id_hex"], "0xab5")
        self.assertEqual(data["token_address"], "0x84A71ccD554Cc1b02749b35d22F684CC8ec987e1")

    @override_settings(WEB3_PAYMENT_RECEIVER_ADDRESS=receiver, WEB3_BASE_RPC_URL="https://base.example/rpc")
    @patch("core.payment_views.requests.post")
    def test_verify_wallet_payment_activates_subscription(self, post_mock):
        create_response = self.client.post(
            reverse("core:pricing_create_wallet_payment"),
            {"plan": "pro", "network": "base", "payer_address": self.payer},
        )
        payment_id = create_response.json()["payment_id"]
        transfer_amount_hex = hex(2_000_000)
        receipt = {
            "status": "0x1",
            "logs": [{
                "address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                "topics": [
                    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
                    "0x0000000000000000000000002222222222222222222222222222222222222222",
                    "0x0000000000000000000000001111111111111111111111111111111111111111",
                ],
                "data": transfer_amount_hex,
            }],
        }
        response_mock = Mock()
        response_mock.raise_for_status.return_value = None
        response_mock.json.return_value = {"result": receipt}
        post_mock.return_value = response_mock

        response = self.client.post(
            reverse("core:pricing_verify_wallet_payment"),
            {"payment_id": payment_id, "tx_hash": self.tx_hash},
        )

        self.assertEqual(response.status_code, 200)
        purchase = Purchase.objects.get(pk=payment_id)
        self.user.plan_access.refresh_from_db()
        self.assertEqual(purchase.status, Purchase.STATUS_WALLET_CONFIRMED)
        self.assertEqual(purchase.tx_hash, self.tx_hash)
        self.assertEqual(self.user.plan_access.plan, "pro")
        self.assertGreater(self.user.plan_access.expires_at, timezone.now())

    @override_settings(WEB3_PAYMENT_RECEIVER_ADDRESS=receiver, WEB3_BASE_RPC_URL="https://base.example/rpc")
    @patch("core.payment_views.requests.post")
    def test_verify_wallet_payment_rejects_non_exact_usdc_amount(self, post_mock):
        create_response = self.client.post(
            reverse("core:pricing_create_wallet_payment"),
            {"plan": "pro", "network": "base", "payer_address": self.payer},
        )
        payment_id = create_response.json()["payment_id"]
        receipt = {
            "status": "0x1",
            "logs": [{
                "address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                "topics": [
                    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
                    "0x0000000000000000000000002222222222222222222222222222222222222222",
                    "0x0000000000000000000000001111111111111111111111111111111111111111",
                ],
                "data": hex(2_000_001),
            }],
        }
        response_mock = Mock()
        response_mock.raise_for_status.return_value = None
        response_mock.json.return_value = {"result": receipt}
        post_mock.return_value = response_mock

        response = self.client.post(
            reverse("core:pricing_verify_wallet_payment"),
            {"payment_id": payment_id, "tx_hash": self.tx_hash},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "expected_transfer_not_found")
        self.user.plan_access.refresh_from_db()
        self.assertEqual(self.user.plan_access.plan, "free")

    @override_settings(WEB3_PAYMENT_RECEIVER_ADDRESS=receiver, WEB3_ETHEREUM_RPC_URL="https://eth.example/rpc")
    @patch("core.payment_views.requests.post")
    def test_verify_eth_wallet_payment_activates_subscription(self, post_mock):
        create_response = self.client.post(
            reverse("core:pricing_create_wallet_payment"),
            {"plan": "pro", "network": "ethereum", "currency": "eth", "payer_address": self.payer},
        )
        payment_id = create_response.json()["payment_id"]
        amount_wei = int(create_response.json()["amount_wei"], 16)
        receipt = {"status": "0x1", "logs": []}
        transaction = {
            "from": self.payer,
            "to": self.receiver,
            "value": hex(amount_wei),
        }
        receipt_response = Mock()
        receipt_response.raise_for_status.return_value = None
        receipt_response.json.return_value = {"result": receipt}
        tx_response = Mock()
        tx_response.raise_for_status.return_value = None
        tx_response.json.return_value = {"result": transaction}
        post_mock.side_effect = [receipt_response, tx_response]

        response = self.client.post(
            reverse("core:pricing_verify_wallet_payment"),
            {"payment_id": payment_id, "tx_hash": self.tx_hash},
        )

        self.assertEqual(response.status_code, 200)
        purchase = Purchase.objects.get(pk=payment_id)
        self.user.plan_access.refresh_from_db()
        self.assertEqual(purchase.status, Purchase.STATUS_WALLET_CONFIRMED)
        self.assertEqual(self.user.plan_access.plan, "pro")

    @override_settings(WEB3_PAYMENT_RECEIVER_ADDRESS=receiver, WEB3_ETHEREUM_RPC_URL="https://eth.example/rpc")
    @patch("core.payment_views.requests.post")
    def test_verify_eth_wallet_payment_rejects_non_exact_amount(self, post_mock):
        create_response = self.client.post(
            reverse("core:pricing_create_wallet_payment"),
            {"plan": "pro", "network": "ethereum", "currency": "eth", "payer_address": self.payer},
        )
        payment_id = create_response.json()["payment_id"]
        amount_wei = int(create_response.json()["amount_wei"], 16)
        receipt = {"status": "0x1", "logs": []}
        transaction = {
            "from": self.payer,
            "to": self.receiver,
            "value": hex(amount_wei + 1),
        }
        receipt_response = Mock()
        receipt_response.raise_for_status.return_value = None
        receipt_response.json.return_value = {"result": receipt}
        tx_response = Mock()
        tx_response.raise_for_status.return_value = None
        tx_response.json.return_value = {"result": transaction}
        post_mock.side_effect = [receipt_response, tx_response]

        response = self.client.post(
            reverse("core:pricing_verify_wallet_payment"),
            {"payment_id": payment_id, "tx_hash": self.tx_hash},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "expected_transfer_not_found")
        self.user.plan_access.refresh_from_db()
        self.assertEqual(self.user.plan_access.plan, "free")

    @override_settings(WEB3_PAYMENT_RECEIVER_ADDRESS=receiver, WEB3_BASE_RPC_URL="https://base.example/rpc")
    @patch("core.payment_views.requests.post")
    def test_verify_wallet_payment_rejects_reused_tx_hash(self, post_mock):
        existing = Purchase.objects.create(
            user=self.user,
            plan="pro",
            provider=Purchase.PROVIDER_WALLET,
            amount_usd="2.00",
            status=Purchase.STATUS_WALLET_CONFIRMED,
            tx_hash=self.tx_hash,
        )
        create_response = self.client.post(
            reverse("core:pricing_create_wallet_payment"),
            {"plan": "pro", "network": "base", "payer_address": self.payer},
        )
        payment_id = create_response.json()["payment_id"]

        response = self.client.post(
            reverse("core:pricing_verify_wallet_payment"),
            {"payment_id": payment_id, "tx_hash": self.tx_hash},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "tx_already_used")
        self.assertTrue(existing.pk)
