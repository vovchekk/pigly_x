from django.test import TestCase
from django.urls import reverse

from history.models import GenerationRequest, GenerationResult
from users.models import User


class HistoryApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="history@example.com",
            username="history-user",
            password="pass12345",
        )
        self.client.force_login(self.user)

        self.item = GenerationRequest.objects.create(
            user=self.user,
            kind=GenerationRequest.KIND_REPLY,
            source_text="Original post text",
            tone="friendly",
            request_data={"language": "en", "variant_count": 2},
        )
        GenerationResult.objects.create(request=self.item, content="Reply one", position=1)
        GenerationResult.objects.create(request=self.item, content="Reply two", position=2)

    def test_history_list_returns_items(self):
        response = self.client.get(reverse("history:list"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["items"][0]["id"], self.item.id)
        self.assertEqual(len(payload["items"][0]["results"]), 2)

    def test_history_detail_returns_single_item(self):
        response = self.client.get(reverse("history:detail", args=[self.item.id]))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["item"]["id"], self.item.id)
        self.assertEqual(payload["item"]["results"][0]["content"], "Reply one")

    def test_history_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("history:list"))

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "not_authenticated")

    def test_history_page_renders_for_dashboard(self):
        response = self.client.get("/history/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Generation history")
        self.assertContains(response, "Original post text")
