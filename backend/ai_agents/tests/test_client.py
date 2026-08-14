from django.test import TestCase
from ai_agents.client import GeminiClient

class GeminiClientTests(TestCase):
    def test_singleton_returns_same_instance(self):
        a = GeminiClient.get_instance()
        b = GeminiClient.get_instance()
        self.assertIs(a, b)