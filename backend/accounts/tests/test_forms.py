from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from accounts.forms import PlaceholderSelect, ProfileSetupForm, MAX_INTERESTS


class PlaceholderSelectTests(SimpleTestCase):
    """
    create_option is plain dict manipulation on Django's own Select
    widget output — no model, no request, no rendering pipeline needed.
    """

    def setUp(self):
        self.widget = PlaceholderSelect()

    def test_boundary_empty_value_option_is_disabled(self):
        # Boundary: the placeholder option itself, value="".
        option = self.widget.create_option(
            name="country", value="", label="Select your country",
            selected=False, index=0,
        )
        self.assertTrue(option["attrs"].get("disabled"))

    def test_normal_input_real_value_option_not_disabled(self):
        # Normal input: an actual selectable choice must stay enabled.
        option = self.widget.create_option(
            name="country", value="Bangladesh", label="Bangladesh",
            selected=False, index=1,
        )
        self.assertNotIn("disabled", option["attrs"])

    def test_unexpected_input_none_value_not_treated_as_placeholder(self):
        # Unexpected input: None is not the same as "" — only an exact
        # empty-string value should be disabled, so a None value (which
        # Django can pass for some field types) must not accidentally
        # match the placeholder check.
        option = self.widget.create_option(
            name="country", value=None, label="—",
            selected=False, index=0,
        )
        self.assertNotIn("disabled", option["attrs"])


class FakeInterestQuerySet:
    """
    Stand-in for the real Interest queryset clean_interests() receives.
    Only .count() is needed for the logic under test, so a full
    QuerySet/DB round trip isn't — this is what keeps the test pure.
    """

    def __init__(self, size):
        self._size = size

    def count(self):
        return self._size


def _clean_interests_with(size):
    """
    Builds a ProfileSetupForm instance without running Django's normal
    __init__ (which would touch the Interest model's queryset) and
    without full form binding/validation — just enough to exercise
    clean_interests() in isolation.
    """
    form = ProfileSetupForm.__new__(ProfileSetupForm)
    form.cleaned_data = {"interests": FakeInterestQuerySet(size)}
    return form.clean_interests()


class ProfileSetupFormCleanInterestsTests(SimpleTestCase):

    def test_boundary_zero_interests_raises(self):
        # Boundary: minimum invalid value — nothing selected at all.
        with self.assertRaises(ValidationError):
            _clean_interests_with(0)

    def test_normal_input_one_interest_is_valid(self):
        # Normal input: smallest valid selection.
        result = _clean_interests_with(1)
        self.assertEqual(result.count(), 1)

    def test_normal_input_mid_range_selection_is_valid(self):
        # Normal input: an ordinary selection well within the allowed range.
        result = _clean_interests_with(3)
        self.assertEqual(result.count(), 3)

    def test_boundary_max_interests_is_valid(self):
        # Boundary: exactly at the upper limit — must be accepted, not
        # rejected as "too many" by an off-by-one error.
        result = _clean_interests_with(MAX_INTERESTS)
        self.assertEqual(result.count(), MAX_INTERESTS)

    def test_boundary_one_over_max_raises(self):
        # Boundary: one past the upper limit must be rejected.
        with self.assertRaises(ValidationError):
            _clean_interests_with(MAX_INTERESTS + 1)

    def test_input_category_far_over_max_raises(self):
        # Negative category: well past the limit, not just an edge case —
        # confirms the check isn't accidentally an equality check that
        # only catches MAX_INTERESTS + 1.
        with self.assertRaises(ValidationError):
            _clean_interests_with(MAX_INTERESTS + 10)
