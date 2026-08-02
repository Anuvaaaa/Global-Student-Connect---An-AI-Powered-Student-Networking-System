from django import forms

from .models import Comment, Post


class PostForm(forms.ModelForm):
    """
    A moment/post, matching the frontend's 200-character limit exactly.
    """

    class Meta:
        model = Post
        fields = ['text']
        widgets = {
            'text': forms.Textarea(attrs={
                'class': 'moment-textarea',
                'id': 'momentText',
                'placeholder': "What's on your mind? Share a university moment...",
                'maxlength': 200,
            })
        }

    def clean_text(self):
        text = self.cleaned_data['text'].strip()
        if not text:
            raise forms.ValidationError("Your moment can't be empty.")
        if len(text) > 200:
            raise forms.ValidationError("Moments are limited to 200 characters.")
        return text


class CommentForm(forms.ModelForm):
    """A single comment on a post."""

    class Meta:
        model = Comment
        fields = ['text']
        widgets = {
            'text': forms.TextInput(attrs={
                'class': 'comment-input',
                'placeholder': 'Write a comment...',
            })
        }

    def clean_text(self):
        text = self.cleaned_data['text'].strip()
        if not text:
            raise forms.ValidationError("Comment can't be empty.")
        return text
