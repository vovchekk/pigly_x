import json
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from assistant.services import GeminiGenerationError, build_reply_generation, build_shorten_generation
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

    @patch("assistant.services._call_gemini_text", return_value="1. Launch moved ahead of schedule, so the current number is not a full-month read.\n2. Rewards went out early, which makes this month’s total look smaller than a full cycle.\n3. The payout started early, so this figure is only a partial-month snapshot.")
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
        self.assertEqual(payload["request"]["request_data"]["result_styles"][0]["style_id"], "supportive")
        self.assertEqual(payload["request"]["request_data"]["result_styles"][1]["style_id"], "sharp")
        self.assertEqual(GenerationRequest.objects.filter(user=self.user, kind="reply").count(), 1)

    @patch("assistant.services._call_gemini_text", return_value="Hello, how are you?")
    def test_translate_returns_translated_text(self, _mock_gemini):
        response = self.client.post(
            reverse("assistant:translate"),
            data=json.dumps({"text": "Привет, как дела?"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["translation"], "Hello, how are you?")
        self.assertEqual(payload["request_data"]["language"], "en")
        self.assertEqual(GenerationRequest.objects.filter(user=self.user, kind="reply").count(), 0)
        self.assertEqual(GenerationRequest.objects.filter(user=self.user, kind="shorten").count(), 0)

    def test_unauthenticated_requests_are_rejected(self):
        self.client.logout()
        response = self.client.post(
            reverse("assistant:shorten"),
            data=json.dumps({"text": "Hello"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "not_authenticated")

    def test_translate_rejects_empty_text(self):
        response = self.client.post(
            reverse("assistant:translate"),
            data=json.dumps({"text": ""}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "missing_source_text")

    @patch("assistant.services._call_gemini_text", return_value="1. [supportive] Ship this week while the context is still hot.")
    def test_extension_token_can_call_api(self, _mock_gemini):
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

    @patch("assistant.services._call_gemini_text", return_value=None)
    def test_shorten_returns_error_when_gemini_is_unavailable(self, _mock_gemini):
        response = self.client.post(
            reverse("assistant:shorten"),
            data=json.dumps({"text": "Need a shorter version of this post.", "language": "en"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "invalid_gemini_output")

    @patch("assistant.services._call_gemini_text", return_value=None)
    def test_reply_returns_error_when_gemini_is_unavailable(self, _mock_gemini):
        response = self.client.post(
            reverse("assistant:reply"),
            data=json.dumps({"text": "Reply to this.", "language": "en"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "invalid_gemini_output")

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

    def test_temporary_generation_restriction_is_enforced(self):
        self.user.plan_access.generation_blocked_until = timezone.now() + timezone.timedelta(hours=2)
        self.user.plan_access.save(update_fields=["generation_blocked_until"])

        response = self.client.post(
            reverse("assistant:reply"),
            data=json.dumps({"text": "Blocked reply", "language": "en"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        payload = response.json()
        self.assertEqual(payload["error"]["code"], "generation_temporarily_blocked")
        self.assertIn("blocked_until", payload["error"])


class ReplyGenerationQualityTests(TestCase):
    @patch("assistant.services._call_gemini_text", return_value="1. Great point\n2. Interesting\n3. Well said")
    def test_reply_generation_rejects_generic_model_output(self, _mock_gemini):
        with self.assertRaises(GeminiGenerationError):
            build_reply_generation(
                source_text="Ship only after the API latency stays under 200ms at 10k requests per minute.",
                context_text="The thread is about rollout risk and reliability.",
                tone="neutral",
                language="en",
                variant_count=3,
            )

    @patch("assistant.services._call_gemini_text", return_value=None)
    def test_reply_generation_requires_gemini_in_russian(self, _mock_gemini):
        with self.assertRaises(GeminiGenerationError):
            build_reply_generation(
                source_text="Если продукт держится только на скидке, retention потом всё равно посыпется.",
                context_text="Обсуждают слабую экономику роста.",
                tone="confident",
                language="ru",
                variant_count=2,
            )

    @patch("assistant.services._call_gemini_text", return_value="1. [supportive] Retention breaks later if onboarding only works with hand-holding.\n2. [sharp] If onboarding needs hand-holding, retention will collapse later.")
    def test_reply_defaults_to_source_language_when_translate_language_is_empty(self, _mock_gemini):
        user = User.objects.create_user(
            email="langcase@example.com",
            username="langcase",
            password="pass12345",
        )
        user.profile.preferred_language = "ru"
        user.profile.preferred_translate_language = ""
        user.profile.save(update_fields=["preferred_language", "preferred_translate_language"])

        request_data, results = build_reply_generation(
            source_text="If the onboarding only works with hand-holding, retention will fall apart later.",
            context_text="",
            tone="neutral",
            language="",
            variant_count=2,
            profile=user.profile,
        )

        self.assertEqual(request_data["language"], "en")
        self.assertTrue(all(not any("А" <= char <= "я" for char in item) for item in results))

    @patch("assistant.services._call_gemini_text", return_value="1. [sharp] First option\n2. [sharp] Second option\n3. [sharp] Third option")
    def test_reply_styles_do_not_repeat_when_multiple_styles_are_selected(self, _mock_gemini):
        user = User.objects.create_user(
            email="styles@example.com",
            username="styles-user",
            password="pass12345",
        )
        user.profile.preferred_comment_styles = ["sharp", "supportive", "curious"]
        user.profile.save(update_fields=["preferred_comment_styles"])

        request_data, results = build_reply_generation(
            source_text="The product only works if users learn one tricky behavior early.",
            context_text="",
            tone="neutral",
            language="en",
            variant_count=3,
            profile=user.profile,
        )

        self.assertEqual(len(results), 3)
        style_ids = [item["style_id"] for item in request_data["result_styles"]]
        self.assertEqual(len(style_ids), 3)
        self.assertEqual(len(set(style_ids)), 3)

    @patch("assistant.services._call_gemini_text", side_effect=["1. [sharp] no stream today, recording the chinese mini-report in abstract today \\(ง'̀-'́)ง/Σ\n2. [supportive] same thing \\(ง'̀-'́)ง/Σ", None])
    def test_reply_generation_filters_broken_symbol_garbage(self, _mock_gemini):
        with self.assertRaises(GeminiGenerationError):
            build_reply_generation(
                source_text="No stream today because I'm recording the China mini-report.",
                context_text="The post is just an announcement about today's recording schedule.",
                tone="neutral",
                language="en",
                variant_count=2,
            )


class ShortenGenerationQualityTests(TestCase):
    @patch("assistant.services._call_gemini_text", return_value="1. In short, the point is the rewards went out early and it is not a full month.\n2. Overall, this post says rewards are out.\n3. Rewards went out early, so this month’s number is not a full-month picture.")
    def test_shorten_generation_filters_weak_wrappers(self, _mock_gemini):
        request_data, results = build_shorten_generation(
            source_text="~$125,000 of rewards was distributed early this month, so the total does not reflect a full month of rewards.",
            tone="neutral",
            language="en",
            variant_count=1,
            target_length=120,
        )

        self.assertEqual(request_data["engine"], "gemini")
        self.assertEqual(len(results), 1)
        self.assertNotIn("In short", results[0])
        self.assertNotIn("the point is", results[0].lower())

    @patch("assistant.services._call_gemini_text", return_value="1. Rewards went out early, so this month’s total is not a full-month read.\n2. Rewards went out early, so this month’s total is not a full-month read.")
    def test_shorten_generation_deduplicates_variants(self, _mock_gemini):
        with self.assertRaises(GeminiGenerationError):
            build_shorten_generation(
                source_text="Rewards went out ahead of schedule, so the current number does not reflect a full month.",
                tone="neutral",
                language="en",
                variant_count=2,
                target_length=120,
            )

    @patch("assistant.services._call_gemini_text", return_value="1. REWARDS ~$125,000 worth of $RAVE token has been distributed this month to participants.")
    def test_shorten_generation_rejects_variants_that_drop_key_reward_context(self, _mock_gemini):
        source_text = (
            "REWARDS 🎁 ~$125,000 worth of $RAVE token has been distributed this month to participants. "
            "This went out ahead of schedule, so it doesn’t reflect a full month of rewards. "
            "There’s still many months of $RAVE left to be distributed to those who took part in the Rave Caves."
        )

        with self.assertRaises(GeminiGenerationError):
            build_shorten_generation(
                source_text=source_text,
                tone="neutral",
                language="en",
                variant_count=1,
                target_length=180,
            )

    @patch("assistant.services._call_gemini_text", return_value="1. AI Builder Spotlight 3 builders making moves on Abstract this week: @OnchainChemists — Rugpull Bakery.")
    def test_shorten_generation_rejects_variants_that_collapse_multi_item_lists(self, _mock_gemini):
        source_text = (
            "AI Builder Spotlight\n\n"
            "3 builders making moves on Abstract this week:\n\n"
            "1️⃣ @OnchainChemists — Rugpull Bakery: An experimental onchain game for fun community participation and collective strategy.\n\n"
            "2️⃣ @play_witty — Lingo: A competitive word game where you wager real ETH against other players.\n\n"
            "3️⃣ @Litanygg — Litany is an agentic gaming protocol on Abstract.\n\n"
            "Builders build. Tap in with your agent today!"
        )

        with self.assertRaises(GeminiGenerationError):
            build_shorten_generation(
                source_text=source_text,
                tone="neutral",
                language="en",
                variant_count=1,
                target_length=180,
            )

    @patch("assistant.services._call_gemini_text", return_value="1. BREAKING In popular game: @OnchainChemists; @0xCygaar; @Zoloto231.")
    def test_shorten_generation_rejects_handle_only_rankings_rewrites(self, _mock_gemini):
        source_text = (
            "BREAKING In popular game @OnchainChemists Rugpull Bakery clan @0xCygaar quietly overtook "
            "Abstract CIS by @Zoloto231 in rankings... and everyone just keeps baking. How did that even happen?"
        )

        with self.assertRaises(GeminiGenerationError):
            build_shorten_generation(
                source_text=source_text,
                tone="neutral",
                language="en",
                variant_count=1,
                target_length=140,
            )

    @patch("assistant.services._call_gemini_text", return_value="1. Abstract Chain is listening, and it shows.: @cygaar; @ChrisJourdan — chain bring real value; @AbstractChain.")
    def test_shorten_generation_rejects_semicolon_handle_roll_calls(self, _mock_gemini):
        source_text = (
            "Abstract Chain is listening, and it shows. Huge respect to the team, especially @cygaar, "
            "for actually reading the community feedback and taking action. Bring more XP focus back to "
            "streamers and content creators. People like @ChrisJourdan doing quality shows daily on-chain "
            "bring real value. Still a massive believer in @AbstractChain as the #1 block chain."
        )

        with self.assertRaises(GeminiGenerationError):
            build_shorten_generation(
                source_text=source_text,
                tone="neutral",
                language="en",
                variant_count=1,
                target_length=140,
            )

    @patch(
        "assistant.services._call_gemini_text",
        side_effect=[
            "1. Abstract Chain implemented community feedback, notably adjusting active project XP evaluation and fixing Discord mod issues, showing responsiveness to users like @cygaar.",
            "1. Abstract Chain is listening, and it shows. Credit to @cygaar for course corrections like active-project XP, Discord/comms fixes, and the upvote streak. But there is still work to do: stop rewarding drain mechanics like Rugpull Bakery, give creators like @ChrisJourdan proper XP, and level up PR/community execution. Still bullish on @AbstractChain, but growth has to come from real usage.",
        ],
    )
    def test_shorten_generation_repairs_multi_section_summary_like_output(self, _mock_gemini):
        source_text = (
            "Abstract Chain is listening, and it shows.\n\n"
            "Huge respect to the team, especially @cygaar, for actually reading the community feedback and taking action:\n\n"
            "1. The active projects XP evaluation was a smart course correction. This is the right path.\n"
            "2. Fixing the Discord mod situation and centralizing comms moving forward is a massive W.\n"
            "3. The upvote streak is simple, brilliant, and keeps people engaged (on day 39).\n\n"
            "Now, a few things we still need to nail:\n\n"
            "1. Transaction farming is not the way. We need to stop pushing products designed to drain liquidity like Rugpull Bakery.\n"
            "2. Bring more XP focus back to streamers and content creators. People like @ChrisJourdan doing quality shows daily on-chain bring real value.\n"
            "3. Hire professional PR/community managers.\n\n"
            "Still a massive believer in @AbstractChain as the #1 block chain. Let's build a sustainable, thriving ecosystem together."
        )

        _request_data, results = build_shorten_generation(
            source_text=source_text,
            tone="neutral",
            language="en",
            variant_count=1,
            target_length=220,
        )

        self.assertEqual(len(results), 1)
        self.assertIn("still work to do", results[0].lower())
        self.assertIn("@chrisjourdan", results[0].lower())
        self.assertIn("@abstractchain", results[0].lower())
        self.assertGreaterEqual(len(results[0].split()), 34)

    @patch(
        "assistant.services._call_gemini_text",
        return_value="Abstract Chain is listening, and it shows. Credit to @cygaar for course corrections like active-project XP and Discord fixes, but there is still work to do: stop drain mechanics like Rugpull Bakery, give creators like @ChrisJourdan proper XP, and strengthen PR/community execution. Still bullish on @AbstractChain.",
    )
    def test_shorten_generation_accepts_single_unnumbered_candidate(self, _mock_gemini):
        source_text = (
            "Abstract Chain is listening, and it shows. Huge respect to the team, especially @cygaar, "
            "for actually reading the community feedback and taking action. Fixing the Discord mod situation "
            "was a massive W. Now, a few things we still need to nail: stop pushing drain mechanics like "
            "Rugpull Bakery, give creators like @ChrisJourdan proper XP, and hire professional PR/community "
            "managers. Still a massive believer in @AbstractChain as the #1 block chain."
        )

        _request_data, results = build_shorten_generation(
            source_text=source_text,
            tone="neutral",
            language="en",
            variant_count=1,
            target_length=220,
        )

        self.assertEqual(len(results), 1)
        self.assertIn("@abstractchain", results[0].lower())

    @patch(
        "assistant.services._call_gemini_text",
        return_value="Abstract Chain is listening. Credit to @cygaar for XP and Discord fixes, but it still needs better creator rewards, less drain farming, and stronger PR.",
    )
    def test_shorten_generation_salvages_single_candidate_that_is_usable_but_not_perfect(self, _mock_gemini):
        source_text = (
            "Abstract Chain is listening, and it shows. Huge respect to the team, especially @cygaar, "
            "for actually reading the community feedback and taking action. Fixing the Discord mod situation "
            "was a massive W. Now, a few things we still need to nail: stop pushing drain mechanics like "
            "Rugpull Bakery, give creators like @ChrisJourdan proper XP, and hire professional PR/community "
            "managers. Still a massive believer in @AbstractChain as the #1 block chain."
        )

        _request_data, results = build_shorten_generation(
            source_text=source_text,
            tone="neutral",
            language="en",
            variant_count=1,
            target_length=220,
        )

        self.assertEqual(len(results), 1)
        self.assertIn("@cygaar", results[0].lower())
