from django.test import SimpleTestCase

from ai_agents.agents.verification_agent import VerificationAgent


class VerificationAgentBuildPromptTests(SimpleTestCase):

    def setUp(self):
        self.agent = VerificationAgent()

    def test_normal_input_domain_embedded_in_prompt(self):
        prompt = self.agent.build_prompt({"domain": "buet.ac.bd"})
        self.assertIn('"buet.ac.bd"', prompt)

    def test_behavior_prompt_includes_a_worked_example(self):
        # Behavior: the example pairing guards against a prompt-text
        # regression that could make Gemini return something other than
        # a plain institution name (e.g. an explanation sentence).
        prompt = self.agent.build_prompt({"domain": "buet.ac.bd"})
        self.assertIn("Bangladesh University of Engineering and Technology", prompt)

    def test_behavior_prompt_instructs_a_fallback_guess_rather_than_blank(self):
        # Behavior: guards the instruction that stops Gemini from
        # returning an empty/refused answer for an unrecognized domain.
        prompt = self.agent.build_prompt({"domain": "unknown-domain.ac.zz"})
        self.assertIn("best short guess", prompt)

    def test_boundary_single_segment_domain(self):
        # Boundary: an unusually short domain still formats without error.
        prompt = self.agent.build_prompt({"domain": "x.edu"})
        self.assertIn('"x.edu"', prompt)


class VerificationAgentConfigTests(SimpleTestCase):
    """
    Regression guards on class attributes — both are load-bearing per
    the project brief (secondary key pool, deterministic naming).
    """

    def test_behavior_uses_secondary_key_group(self):
        self.assertEqual(VerificationAgent.api_key_group, "secondary")

    def test_behavior_temperature_pinned_to_zero(self):
        self.assertEqual(VerificationAgent.temperature, 0)
