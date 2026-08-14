from django.test import TestCase
from ai_agents.factory import AgentFactory

class AgentFactoryTests(TestCase):
    def test_unknown_agent_raises(self):
        with self.assertRaises(ValueError):
            AgentFactory.get_agent("not_a_real_agent")