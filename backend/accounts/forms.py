from django import forms

from social.models import Interest

from .models import Profile

# Pulled directly from profile-setup.html's <select> options — keep in sync
# if the frontend list ever changes.
COUNTRY_CHOICES = [('', 'Select your country')] + [(c, c) for c in [
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


class PlaceholderSelect(forms.Select):
    """
    Plain ChoiceField has no way to disable an individual <option> — the
    prototype's dropdowns use <option value="" disabled selected> so the
    placeholder can't accidentally be re-selected/submitted as a real
    value. This restores that behavior for any field using it.
    """
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        if value == '':
            option['attrs']['disabled'] = True
        return option


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

    country = forms.ChoiceField(choices=COUNTRY_CHOICES, widget=PlaceholderSelect)
    primary_language = forms.ChoiceField(
        choices=[('', 'Select your first language')] + LANGUAGE_CHOICES,
        widget=PlaceholderSelect,
    )
    secondary_language = forms.ChoiceField(
        choices=[('', 'Select your second language')] + LANGUAGE_CHOICES,
        widget=PlaceholderSelect,
    )  # required — matches original frontend validation

    # Default ModelForm widget for a choices CharField is a <select> dropdown;
    # the prototype uses two radio boxes (👨/👩), so override explicitly.
    gender = forms.ChoiceField(choices=Profile.GENDER_CHOICES, widget=forms.RadioSelect)

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
        widgets = {
            'display_name': forms.TextInput(attrs={
                'class': 'input-field', 'placeholder': 'e.g. Ahmad Rahman',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Applied here rather than Meta.widgets since these fields are
        # declared explicitly above (Meta.widgets only affects fields
        # Django derives automatically from the model).
        self.fields['country'].widget.attrs['class'] = 'input-field select-field'
        self.fields['primary_language'].widget.attrs['class'] = 'input-field select-field'
        self.fields['secondary_language'].widget.attrs['class'] = 'input-field select-field'

    def clean_interests(self):
        interests = self.cleaned_data['interests']
        count = interests.count()
        if count == 0:
            raise forms.ValidationError('Choose at least 1 interest.')
        if count > MAX_INTERESTS:
            raise forms.ValidationError(f'Choose at most {MAX_INTERESTS} interests.')
        return interests