from django import forms

from .models import Message


class MessageForm(forms.ModelForm):
    class Meta:
        model = Message
        fields = ['text']

    def clean_text(self):
        text = self.cleaned_data['text'].strip()
        if not text:
            raise forms.ValidationError("Message can't be empty.")
        if len(text) > 500:
            raise forms.ValidationError("Message is too long (max 500 characters).")
        return text
