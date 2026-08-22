# TARGET PATH: ai_agents/agents/platform_assistant_agent.py
"""
Help/FAQ chatbot scoped to Global Student Connect's own features only
(matching, groups, chat/translation, badges/missions, reporting/blocking,
navigation). Refuses anything outside that scope.

Gemini's API is stateless per call, so "remembering" earlier turns in the
same conversation means flattening prior thread messages into the prompt
text by hand on every request, rather than relying on any session state
on Google's side.
"""

import random

from pydantic import BaseModel

from ai_agents.base import AIAgent

# GROUNDING NOTE: without an actual feature list, Gemini has nothing real
# to answer FAQ questions from and will invent plausible-sounding but
# false UI steps (e.g. a "notification preferences" toggle that doesn't
# exist in this build). Everything below reflects what's actually built,
# per the current models/views — review and correct this list yourself
# as features land or change, since I generated it from the schema/class
# diagrams, not a live walkthrough of your UI.
PLATFORM_FACTS = """What actually exists in GSC right now:

- MATCHING: students get matched into small same-gender groups based on
  shared interests (Connect page). No 1:1 "swipe" matching beyond the
  existing MatchRequest/Connection flow.
- CHAT: 1:1 conversations (from an accepted Connection) and group
  conversations (from a StudentGroup). Auto-translation is available per
  message via the translate action.
- PROFILE: display name, country, gender, primary/secondary language,
  auto-translate on/off, and a default translate-into language. This is
  the only settings surface that currently exists — there is no separate
  "Settings" page or tab.
- NOTIFICATIONS: a single Notifications page lists all notifications
  (matches, groups, messages, badges, missions, system). You can mark one
  or all as read. There is currently NO per-type notification preference
  toggle — students receive all notification types, and there is no way
  to opt out of specific categories yet.
- BADGES & MISSIONS: badges are earned automatically by crossing usage
  thresholds (messages sent, groups joined, etc.), shown in tiers
  (bronze/silver/gold) on the profile page. Missions are daily/weekly
  goals also shown on the profile page. Neither is configurable by the
  student — both are fully automatic.
- REPORTING/BLOCKING: available from within a conversation or profile,
  filed as a Report reviewed by moderators. There is no user-facing
  moderation dashboard — only staff see report outcomes.
- SIGN-IN: currently email/password during development; Google Sign-In
  is planned but not live yet.

If a student asks about a feature not described above (notification
preferences, account deletion, dark mode, privacy settings, etc.), say
plainly that GSC doesn't have that yet, rather than guessing where it
might be. Never invent a menu path, icon, or settings screen you can't
confirm from the list above."""

PLATFORM_SCOPE = f"""You are the GSC Platform Assistant, a help chatbot for
Global Student Connect, a university student networking and matching
platform. You ONLY answer questions about how the GSC platform works:
signing in, profile setup, matching and groups, chat and translation,
missions and badges, notifications, reporting/blocking, and general
navigation.

{PLATFORM_FACTS}

You do NOT have access to any individual student's live data (their
matches, messages, or progress) — if asked something personal like "why
haven't I matched yet," direct them to the relevant page (e.g. "check your
Matching page") rather than guessing an answer.

If asked to do anything unrelated to the GSC platform — writing essays,
solving homework, writing code, general conversation, or anything else
outside how GSC works — politely decline and redirect: say you can only
help with questions about using GSC, and ask what they'd like to know
about the platform."""

# Rotated so a Gemini outage doesn't show the exact same line on every retry.
FALLBACK_MESSAGES = [
    "My brain just did the spinning-wheel-of-doom thing. Give me a second and ask again?",
    "I dropped that thought somewhere between here and Google's servers. One more try?",
    "Assistant.exe has stopped responding (dramatically). Try again in a moment?",
]

# Older turns add little value for platform-FAQ questions and cost tokens on
# every single call, since the whole history is re-sent each time.
MAX_HISTORY_TURNS = 6


class AssistantResponse(BaseModel):
    answer: str
    in_scope: bool


def format_history(messages: list[dict]) -> str:
    """
    Turn a list of {"role": "user"/"assistant", "content": str} dicts into a
    flat transcript block for the prompt. Only the most recent
    MAX_HISTORY_TURNS entries are kept. A role other than "user" is treated
    as the assistant's own turn, so a bad/missing role never disappears
    silently from the transcript.

    Deliberately takes generic {"role", "content"} dicts rather than
    AssistantMessage instances, so this function has no dependency on the
    DB field names (AssistantMessage.text, not .content) — the caller maps
    ORM rows into this shape.
    """
    if not messages:
        return "(no earlier messages in this conversation)"

    trimmed = messages[-MAX_HISTORY_TURNS:]
    lines = []
    for turn in trimmed:
        speaker = "Student" if turn.get("role") == "user" else "Assistant"
        content = turn.get("content", "")
        lines.append(f"{speaker}: {content}")
    return "\n".join(lines)


def get_fallback_message() -> str:
    """Casual apology shown when the Gemini call fails outright."""
    return random.choice(FALLBACK_MESSAGES)


class PlatformAssistantAgent(AIAgent):
    # Routes on the shared secondary key group, alongside Verification and
    # Translation. Safety/Nudge/Matching stay on the primary key untouched.
    api_key_group = "secondary"
    response_schema = AssistantResponse
    # Grounded FAQ answers should stay consistent call to call, not vary
    # creatively — same reasoning as Verification's temperature=0.
    temperature = 0

    def build_prompt(self, payload: dict) -> str:
        history_block = format_history(payload.get("history", []))
        question = payload["question"]
        return f"""{PLATFORM_SCOPE}

Conversation so far:
{history_block}

Student's new question: "{question}"

Respond ONLY with JSON, no markdown fences:
{{"answer": "...", "in_scope": true/false}}"""

    def parse_response(self, raw_text: str) -> dict:
        return self.parse_json(raw_text)
