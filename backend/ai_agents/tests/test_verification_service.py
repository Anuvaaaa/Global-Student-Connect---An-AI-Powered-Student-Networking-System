from unittest.mock import patch, MagicMock

from django.test import SimpleTestCase

from ai_agents.services.verification_service import resolve_university, _fallback_name


class FallbackNameTests(SimpleTestCase):
    # --- pure tests start here ---
    # _fallback_name is plain string splitting, no DB or agent involved.

    def test_normal_input_typical_domain(self):
        self.assertEqual(_fallback_name("buet.ac.bd"), "buet")

    def test_normal_input_dot_edu_domain(self):
        self.assertEqual(_fallback_name("mit.edu"), "mit")

    def test_boundary_single_segment_domain(self):
        # Boundary: a domain with no dots at all — split still returns
        # the whole string as element 0 rather than raising.
        self.assertEqual(_fallback_name("localhost"), "localhost")


# --- non-pure tests start here ---
# resolve_university touches University.objects (mocked) and the
# Verification agent via AgentFactory (also mocked) — no real DB row
# or Gemini call happens in any test below.


class ResolveUniversityTests(SimpleTestCase):

    def test_normal_input_existing_domain_skips_agent_entirely(self):
        # Normal input: a domain that's already been seen before — must
        # return the existing row and never call the agent at all.
        existing = MagicMock(name="existing_university")
        with patch("accounts.models.University.objects") as mock_manager:
            mock_manager.get_or_create.return_value = (existing, False)
            with patch("ai_agents.factory.AgentFactory.get_agent") as mock_get_agent:
                result = resolve_university("buet.ac.bd")

        self.assertIs(result, existing)
        mock_get_agent.assert_not_called()

    def test_behavior_new_domain_created_with_fallback_name_first(self):
        # Behavior: get_or_create must be called with the deterministic
        # fallback name as the default — this is what guarantees the row
        # already has a usable name even before the agent is attempted.
        with patch("accounts.models.University.objects") as mock_manager:
            new_uni = MagicMock()
            mock_manager.get_or_create.return_value = (new_uni, True)
            with patch("ai_agents.factory.AgentFactory.get_agent") as mock_get_agent:
                mock_get_agent.return_value.run.return_value = {
                    "university_name": "Bangladesh University of Engineering and Technology"
                }
                resolve_university("buet.ac.bd")

        _, kwargs = mock_manager.get_or_create.call_args
        self.assertEqual(kwargs["defaults"]["name"], "buet")

    def test_normal_input_new_domain_upgraded_via_agent(self):
        # Normal input: brand-new domain, agent succeeds — the row's
        # name should be upgraded and saved.
        new_uni = MagicMock()
        with patch("accounts.models.University.objects") as mock_manager:
            mock_manager.get_or_create.return_value = (new_uni, True)
            with patch("ai_agents.factory.AgentFactory.get_agent") as mock_get_agent:
                mock_get_agent.return_value.run.return_value = {
                    "university_name": "Bangladesh University of Engineering and Technology"
                }
                result = resolve_university("buet.ac.bd")

        self.assertEqual(
            result.name, "Bangladesh University of Engineering and Technology"
        )
        new_uni.save.assert_called_once_with(update_fields=["name"])

    def test_unexpected_input_agent_failure_keeps_fallback_name(self):
        # Unexpected input: agent is unreachable for a brand-new domain —
        # the row must keep its fallback name and the function must not
        # raise, matching "account creation is never blocked".
        new_uni = MagicMock(name="northsouth")
        with patch("accounts.models.University.objects") as mock_manager:
            mock_manager.get_or_create.return_value = (new_uni, True)
            with patch(
                "ai_agents.factory.AgentFactory.get_agent",
                side_effect=RuntimeError("quota exhausted"),
            ):
                result = resolve_university("northsouth.edu")

        # save() is only called on the success path — on failure, the
        # row created by get_or_create's own defaults is left untouched.
        new_uni.save.assert_not_called()
        self.assertIs(result, new_uni)

    def test_unexpected_input_agent_returns_empty_name_keeps_fallback(self):
        # Unexpected input: the agent "succeeds" but returns an empty or
        # non-string name — treated the same as a failure, not saved.
        new_uni = MagicMock()
        with patch("accounts.models.University.objects") as mock_manager:
            mock_manager.get_or_create.return_value = (new_uni, True)
            with patch("ai_agents.factory.AgentFactory.get_agent") as mock_get_agent:
                mock_get_agent.return_value.run.return_value = {"university_name": ""}
                resolve_university("buet.ac.bd")

        new_uni.save.assert_not_called()
