from django import forms

from social.models import Interest

from .models import Profile

# Pulled directly from profile-setup.html's <select> options — keep in sync
# if the frontend list ever changes.
COUNTRY_CHOICES = [(c, c) for c in [
    'Bangladesh', 'India', 'Pakistan', 'Sri Lanka', 'Nepal', 'Malaysia',
    'Indonesia', 'Philippines', 'Japan', 'South Korea', 'China',
    'Saudi Arabia', 'United Arab Emirates', 'Turkey', 'Nigeria', 'Ghana',
    'Kenya', 'Brazil', 'Mexico', 'United Kingdom', 'Germany', 'France',
    'United States', 'Canada', 'Australia',
]]

LANGUAGE_CHOICES = [(l, l) for l in [
    'English', 'Bengali', 'Hindi', 'Urdu', 'Arabic', 'Mandarin', 'Spanish',
    'French', 'Portuguese', 'Malay', 'Turkish', 'Swahili',
]]

MAX_INTERESTS = 5


class ProfileSetupForm(forms.ModelForm):
    """
    Covers step 1 (name/country), step 2 (languages/gender/auto-translate)
    and step 3 (interests) of profile-setup.html in one form — the frontend's
    step-switching UI stays exactly as-is (pure JS/CSS), only the final
    submit needs to POST here.

    NOTE: the frontend also has a free-text "University" field (userUni).
    That's deliberately dropped here — per the project brief, University is
    meant to be auto-resolved from the verified email domain (Section 3),
    not typed by hand. It'll be set automatically once Google OAuth (Step 7)
    is wired up. Until then, test users just have university = None.
    """

    country = forms.ChoiceField(choices=COUNTRY_CHOICES)
    primary_language = forms.ChoiceField(choices=LANGUAGE_CHOICES)
    secondary_language = forms.ChoiceField(choices=LANGUAGE_CHOICES, required=False)

    # Interest is a social-app model, not a Profile field, so it's bolted on
    # here rather than living in Meta.fields. Rendered as checkboxes for now —
    # whoever builds the template can wire these to the existing .interest-tag
    # button markup with a bit of JS (check the hidden checkbox that matches
    # data-interest when a tag is clicked) instead of using default widget.
    interests = forms.ModelMultipleChoiceField(
        queryset=Interest.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        required=True,
    )

    class Meta:
        model = Profile
        fields = [
            'display_name', 'country', 'gender',
            'primary_language', 'secondary_language', 'auto_translate',
        ]

    def clean_interests(self):
        interests = self.cleaned_data['interests']
        count = interests.count()
        if count == 0:
            raise forms.ValidationError('Choose at least 1 interest.')
        if count > MAX_INTERESTS:
            raise forms.ValidationError(f'Choose at most {MAX_INTERESTS} interests.')
        return interests
