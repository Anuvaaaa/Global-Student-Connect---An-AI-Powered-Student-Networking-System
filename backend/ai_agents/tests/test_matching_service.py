# TARGET PATH: ai_agents/tests/test_matching_service.py
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import Profile, University
from social.models import Interest, UserInterest
from ai_agents.services.matching_service import get_compatibility_score
from matching.utils import compute_compatibility_score

User = get_user_model()


def _make_user(email, country="Bangladesh", with_profile=True):
    university, _ = University.objects.get_or_create(
        domain="example.edu", defaults={"name": "Example University"},
    )
    user = User.objects.create_user(
        username=email, email=email, google_id=f"gid-{email}",
        university=university, is_verified=True, password="testpass123",
    )
    if with_profile:
        Profile.objects.create(
            user=user, display_name=email.split("@")[0], country=country,
            gender="Male", primary_language="English", secondary_language="",
            profile_setup_complete=True,
        )
    return user


def _add_interests(user, names):
    for name in names:
        interest, _ = Interest.objects.get_or_create(name=name)
        UserInterest.objects.create(user=user, interest=interest)


class GetCompatibilityScoreAiSuccessTests(TestCase):
    """Normal input: Gemini reachable and returns a valid score."""

    def setUp(self):
        self.user_a = _make_user("a@example.edu")
        self.user_b = _make_user("b@example.edu")
        _add_interests(self.user_a, ["Music", "Travel"])
        _add_interests(self.user_b, ["Music"])

    @patch("ai_agents.factory.AgentFactory.get_agent")
    def test_returns_ai_score_when_valid(self, mock_get_agent):
        mock_agent = mock_get_agent.return_value
        mock_agent.run.return_value = {"score": 91, "reasoning": "Shared music interest."}

        score = get_compatibility_score(self.user_a, self.user_b)

        self.assertEqual(score, 91.0)

    @patch("ai_agents.factory.AgentFactory.get_agent")
    def test_ai_agent_called_with_both_users_interests(self, mock_get_agent):
        mock_agent = mock_get_agent.return_value
        mock_agent.run.return_value = {"score": 50, "reasoning": "x"}

        get_compatibility_score(self.user_a, self.user_b)

        payload = mock_agent.run.call_args[0][0]
        self.assertIn("Music", payload["user_a_interests"])
        self.assertIn("Music", payload["user_b_interests"])


class GetCompatibilityScoreBoundaryTests(TestCase):
    """Boundary values: score exactly at 0, exactly at 100, and just outside both ends."""

    def setUp(self):
        self.user_a = _make_user("a@example.edu")
        self.user_b = _make_user("b@example.edu")

    @patch("ai_agents.factory.AgentFactory.get_agent")
    def test_score_of_zero_is_accepted_as_is(self, mock_get_agent):
        mock_get_agent.return_value.run.return_value = {"score": 0, "reasoning": "No overlap."}

        score = get_compatibility_score(self.user_a, self.user_b)

        self.assertEqual(score, 0.0)

    @patch("ai_agents.factory.AgentFactory.get_agent")
    def test_score_of_one_hundred_is_accepted_as_is(self, mock_get_agent):
        mock_get_agent.return_value.run.return_value = {"score": 100, "reasoning": "Perfect match."}

        score = get_compatibility_score(self.user_a, self.user_b)

        self.assertEqual(score, 100.0)

    @patch("ai_agents.factory.AgentFactory.get_agent")
    def test_score_of_negative_one_falls_back(self, mock_get_agent):
        mock_get_agent.return_value.run.return_value = {"score": -1, "reasoning": "Bad output."}

        score = get_compatibility_score(self.user_a, self.user_b)

        self.assertEqual(score, compute_compatibility_score(self.user_a, self.user_b))

    @patch("ai_agents.factory.AgentFactory.get_agent")
    def test_score_of_one_hundred_and_one_falls_back(self, mock_get_agent):
        mock_get_agent.return_value.run.return_value = {"score": 101, "reasoning": "Bad output."}

        score = get_compatibility_score(self.user_a, self.user_b)

        self.assertEqual(score, compute_compatibility_score(self.user_a, self.user_b))


class GetCompatibilityScoreFailOpenTests(TestCase):
    """
    Core requirement: matching NEVER stops, regardless of why Gemini
    failed. Every failure mode below must still return a usable float
    computed by the exact same fallback formula, not raise.
    """

    def setUp(self):
        self.user_a = _make_user("a@example.edu")
        self.user_b = _make_user("b@example.edu")
        _add_interests(self.user_a, ["Music", "Travel", "Coding"])
        _add_interests(self.user_b, ["Music", "Coding"])
        self.expected_fallback = compute_compatibility_score(self.user_a, self.user_b)

    # --- behavior: API down entirely ---
    @patch("ai_agents.factory.AgentFactory.get_agent")
    def test_falls_back_when_agent_construction_raises_connection_error(self, mock_get_agent):
        mock_get_agent.side_effect = ConnectionError("could not reach Gemini")

        score = get_compatibility_score(self.user_a, self.user_b)

        self.assertEqual(score, self.expected_fallback)

    # --- behavior: request times out ---
    @patch("ai_agents.factory.AgentFactory.get_agent")
    def test_falls_back_on_timeout(self, mock_get_agent):
        mock_get_agent.return_value.run.side_effect = TimeoutError("request timed out")

        score = get_compatibility_score(self.user_a, self.user_b)

        self.assertEqual(score, self.expected_fallback)

    # --- behavior: free-tier / rate limit exceeded ---
    @patch("ai_agents.factory.AgentFactory.get_agent")
    def test_falls_back_on_rate_limit_exceeded(self, mock_get_agent):
        mock_get_agent.return_value.run.side_effect = Exception("429 RESOURCE_EXHAUSTED")

        score = get_compatibility_score(self.user_a, self.user_b)

        self.assertEqual(score, self.expected_fallback)

    # --- unexpected input: malformed response missing the score key ---
    @patch("ai_agents.factory.AgentFactory.get_agent")
    def test_falls_back_when_response_missing_score_key(self, mock_get_agent):
        mock_get_agent.return_value.run.return_value = {"reasoning": "forgot the score"}

        score = get_compatibility_score(self.user_a, self.user_b)

        self.assertEqual(score, self.expected_fallback)

    # --- unexpected input: score is a string instead of a number ---
    @patch("ai_agents.factory.AgentFactory.get_agent")
    def test_falls_back_when_score_is_non_numeric(self, mock_get_agent):
        mock_get_agent.return_value.run.return_value = {"score": "high", "reasoning": "x"}

        score = get_compatibility_score(self.user_a, self.user_b)

        self.assertEqual(score, self.expected_fallback)

    # --- unexpected input: score is a bool (True/False are ints in Python) ---
    @patch("ai_agents.factory.AgentFactory.get_agent")
    def test_falls_back_when_score_is_boolean(self, mock_get_agent):
        # isinstance(True, int) is True in Python, so this is guarded
        # against explicitly rather than accidentally accepted as 1/0.
        mock_get_agent.return_value.run.side_effect = None
        mock_get_agent.return_value.run.return_value = {"score": True, "reasoning": "x"}

        score = get_compatibility_score(self.user_a, self.user_b)

        self.assertEqual(score, self.expected_fallback)

    # --- unexpected input: run() returns something that isn't a dict at all ---
    @patch("ai_agents.factory.AgentFactory.get_agent")
    def test_falls_back_when_response_is_not_a_dict(self, mock_get_agent):
        mock_get_agent.return_value.run.return_value = "just a string, not a dict"

        score = get_compatibility_score(self.user_a, self.user_b)

        self.assertEqual(score, self.expected_fallback)

    # --- unexpected input: one user has no profile at all ---
    @patch("ai_agents.factory.AgentFactory.get_agent")
    def test_never_raises_when_second_user_has_no_profile(self, mock_get_agent):
        no_profile_user = _make_user("no-profile@example.edu", with_profile=False)
        mock_get_agent.return_value.run.side_effect = Exception("simulated outage")

        score = get_compatibility_score(self.user_a, no_profile_user)

        # Fallback itself tolerates a missing profile (getattr(...,None)
        # in compute_compatibility_score), so this must not raise either.
        self.assertIsInstance(score, (int, float))
