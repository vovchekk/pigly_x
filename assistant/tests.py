import json
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from history.models import GenerationRequest
from users.models import ExtensionAccessToken, User


class AssistantApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="tester@example.com",
            username="tester",
            password="pass12345",
        )
        self.client.force_login(self.user)

    @patch("assistant.services._call_gemini_text", return_value="1. Clearer short version\n2. Tighter idea\n3. Compact summary")
    def test_shorten_creates_history_item(self, _mock_gemini):
        response = self.client.post(
            reverse("assistant:shorten"),
            data=json.dumps(
                {
                    "text": "This is a long post that should be shorter and clearer for X/Twitter readers.",
                    "tone": "concise",
                    "language": "en",
                    "variant_count": 3,
                    "target_length": 120,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["request"]["kind"], GenerationRequest.KIND_SHORTEN)
        self.assertEqual(len(payload["request"]["results"]), 3)
        self.assertEqual(payload["request"]["request_data"]["engine"], "gemini")
        self.assertEqual(GenerationRequest.objects.filter(user=self.user, kind="shorten").count(), 1)

    @patch("assistant.services._call_gemini_text", return_value="1. [supportive] Ship it now while the context is still hot\n2. [sharp] MVP this week matters more than polish")
    def test_reply_creates_history_item(self, _mock_gemini):
        response = self.client.post(
            reverse("assistant:reply"),
            data=json.dumps(
                {
                    "text": "I think this launch is going to be great.",
                    "context": "A user is asking about shipping the MVP today.",
                    "tone": "friendly",
                    "language": "en",
                    "variant_count": 2,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["request"]["kind"], GenerationRequest.KIND_REPLY)
        self.assertEqual(payload["request"]["request_data"]["context_text"], "A user is asking about shipping the MVP today.")
        self.assertEqual(len(payload["request"]["results"]), 2)
        self.assertEqual(payload["request"]["request_data"]["engine"], "gemini")
        self.assertEqual(GenerationRequest.objects.filter(user=self.user, kind="reply").count(), 1)

    def test_unauthenticated_requests_are_rejected(self):
        self.client.logout()
        response = self.client.post(
            reverse("assistant:shorten"),
            data=json.dumps({"text": "Hello"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "not_authenticated")

    def test_extension_token_can_call_api(self):
        self.client.logout()
        token = ExtensionAccessToken.objects.create(user=self.user)

        response = self.client.post(
            reverse("assistant:reply"),
            data=json.dumps({"text": "Ship the MVP this week.", "language": "en"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token.token}",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["status"], "ok")

    def test_plan_limit_is_enforced(self):
        self.user.plan_access.ai_reply_limit = 1
        self.user.plan_access.save(update_fields=["ai_reply_limit"])

        self.client.post(
            reverse("assistant:reply"),
            data=json.dumps({"text": "First reply", "language": "en"}),
            content_type="application/json",
        )
        response = self.client.post(
            reverse("assistant:reply"),
            data=json.dumps({"text": "Second reply", "language": "en"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "plan_limit_reached")
