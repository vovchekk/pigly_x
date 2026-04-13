from django.test import TestCase
from django.urls import reverse


class LandingTests(TestCase):
    def test_landing_does_not_render_password_auth_ui(self):
        response = self.client.get(reverse("core:landing"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'type="password"', html=False)
        self.assertNotContains(response, "No account yet?")
        self.assertNotContains(response, "Already have an account?")
