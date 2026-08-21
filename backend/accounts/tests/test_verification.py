from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from accounts.verification import (
    extract_domain_from_email,
    is_academic_domain,
    get_verification_block_message,
    complete_verification,
    UNVERIFIED_EMAIL_MESSAGE,
)

# --- pure tests start here ---
# No DB, no mocks, no external calls — plain functions of their inputs.


class ExtractDomainFromEmailTests(SimpleTestCase):

    def test_normal_input_standard_email(self):
        self.assertEqual(extract_domain_from_email("student@buet.ac.bd"), "buet.ac.bd")

    def test_behavior_lowercases_the_domain(self):
        # Behavior: case shouldn't matter for later domain matching.
        self.assertEqual(extract_domain_from_email("student@BUET.AC.BD"), "buet.ac.bd")

    def test_unexpected_input_missing_at_symbol_raises(self):
        with self.assertRaises(ValueError):
            extract_domain_from_email("not-an-email")

    def test_unexpected_input_empty_string_raises(self):
        with self.assertRaises(ValueError):
            extract_domain_from_email("")

    def test_boundary_multiple_at_symbols_uses_last_one(self):
        # Boundary: an unusual but not impossible local-part containing
        # "@" (rare, technically legal in a quoted local-part) — must
        # split on the LAST "@" so the domain is still correct.
        self.assertEqual(extract_domain_from_email('"a@b"@buet.ac.bd'), "buet.ac.bd")


class IsAcademicDomainTests(SimpleTestCase):

    def test_normal_input_ac_bd_suffix(self):
        self.assertTrue(is_academic_domain("buet.ac.bd"))

    def test_normal_input_edu_suffix(self):
        self.assertTrue(is_academic_domain("mit.edu"))

    def test_input_category_edu_country_suffix(self):
        # Positive category: .edu.<cc> form, distinct from plain .edu.
        self.assertTrue(is_academic_domain("monash.edu.au"))

    def test_input_category_non_academic_domain(self):
        # Negative category: an ordinary commercial domain.
        self.assertFalse(is_academic_domain("gmail.com"))

    def test_behavior_subdomain_still_matches_suffix(self):
        # Behavior: the pattern is anchored to the end of the string, so
        # a mail subdomain in front of an academic suffix still matches.
        self.assertTrue(is_academic_domain("mail.buet.ac.bd"))

    def test_unexpected_input_empty_string_returns_false(self):
        self.assertFalse(is_academic_domain(""))

    def test_unexpected_input_none_returns_false(self):
        self.assertFalse(is_academic_domain(None))

    def test_boundary_suffix_as_substring_not_at_end_does_not_match(self):
        # Boundary: ".edu" appearing mid-string, not as the actual
        # suffix, must NOT match — otherwise "edu.fakescam.com" would
        # incorrectly pass.
        self.assertFalse(is_academic_domain("edu.fakescam.com"))

    def test_behavior_whitelist_entry_matches_regardless_of_pattern(self):
        # Behavior: the manual whitelist is checked independently of the
        # regex, for real institutions whose domain doesn't fit the
        # standard suffix shape.
        with patch("accounts.verification.ACADEMIC_DOMAIN_WHITELIST", {"nsu.edu.example"}):
            self.assertTrue(is_academic_domain("nsu.edu.example"))


class GetVerificationBlockMessageTests(SimpleTestCase):

    def test_normal_input_academic_email_returns_none(self):
        self.assertIsNone(get_verification_block_message("student@buet.ac.bd"))

    def test_input_category_non_academic_email_returns_message(self):
        # Negative category: valid email, non-academic domain.
        result = get_verification_block_message("student@gmail.com")
        self.assertEqual(result, UNVERIFIED_EMAIL_MESSAGE)

    def test_unexpected_input_malformed_email_propagates_error(self):
        # Unexpected input: this function doesn't swallow a malformed
        # email — it should surface the same ValueError
        # extract_domain_from_email raises, not fail silently.
        with self.assertRaises(ValueError):
            get_verification_block_message("not-an-email")


# --- non-pure tests start here ---
# complete_verification writes to the database and calls into
# ai_agents.services.verification_service, so both are mocked here
# rather than hitting a real DB row or the Gemini API.


class CompleteVerificationTests(SimpleTestCase):

    def test_normal_input_new_user_gets_verified_and_university_resolved(self):
        # Normal input: user has no university yet — resolve_university
        # must be called and its result assigned.
        fake_university = SimpleNamespace(name="BUET")
        user = SimpleNamespace(
            email="student@buet.ac.bd", is_verified=False, university=None, save=lambda **kw: None
        )

        with patch(
            "ai_agents.services.verification_service.resolve_university",
            return_value=fake_university,
        ) as mock_resolve:
            complete_verification(user)

        mock_resolve.assert_called_once_with("buet.ac.bd")
        self.assertTrue(user.is_verified)
        self.assertIs(user.university, fake_university)

    def test_behavior_existing_university_is_not_overwritten(self):
        # Behavior: a user who already has a university set (e.g. an
        # admin manually assigned one) must not have it silently
        # replaced by resolve_university on a later verification pass.
        existing_university = SimpleNamespace(name="Manually Set Uni")
        user = SimpleNamespace(
            email="student@buet.ac.bd",
            is_verified=False,
            university=existing_university,
            save=lambda **kw: None,
        )

        with patch(
            "ai_agents.services.verification_service.resolve_university"
        ) as mock_resolve:
            complete_verification(user)

        mock_resolve.assert_not_called()
        self.assertIs(user.university, existing_university)
        self.assertTrue(user.is_verified)

    def test_behavior_saves_only_the_two_changed_fields(self):
        # Behavior: save() should be scoped to is_verified/university,
        # not a full save() that could clobber concurrent changes to
        # other fields on the same row.
        saved_fields = {}

        def fake_save(update_fields=None):
            saved_fields["update_fields"] = update_fields

        user = SimpleNamespace(
            email="student@buet.ac.bd", is_verified=False, university=None, save=fake_save
        )

        with patch(
            "ai_agents.services.verification_service.resolve_university",
            return_value=SimpleNamespace(name="BUET"),
        ):
            complete_verification(user)

        self.assertEqual(set(saved_fields["update_fields"]), {"is_verified", "university"})
