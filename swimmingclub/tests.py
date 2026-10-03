from django.test import TestCase, Client
from django.urls import reverse

class SwimmingClubViewsTest(TestCase):
    def setUp(self):
        self.client = Client()

    def test_set_language_valid_code(self):
        # Assuming 'en' is a valid code in VALID_CODES
        response = self.client.get(reverse('set_language'), {'lang': 'en'})
        self.assertEqual(response.status_code, 302)
        # Check if session was set (this depends on your middleware/session config)
        # We verify it redirects back

    def test_set_language_invalid_code(self):
        response = self.client.get(reverse('set_language'), {'lang': 'invalid'})
        self.assertEqual(response.status_code, 302)
