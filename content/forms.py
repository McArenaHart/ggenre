from django import forms
from .models import Content, Comment

class ContentUploadForm(forms.ModelForm):
    """
    ModelForm for uploading content by artists.
    """
    class Meta:
        model = Content
        fields = ['title', 'description', 'file', 'youtube_url', 'thumbnail', 'tags', 'genre']  # Include all required fields
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter content title'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'placeholder': 'Enter a description', 'rows': 5}),
            'file': forms.FileInput(attrs={'class': 'form-control'}),
            'youtube_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://www.youtube.com/watch?v=...'}),
            'tags': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter tags (comma-separated)'}),

        }

    def clean_file(self):
        upload_file = self.cleaned_data.get('file')
        if upload_file:
            if upload_file.size > 50 * 1024 * 1024:  # 50 MB size limit
                raise forms.ValidationError("File size must not exceed 50 MB.")
            allowed_file_types = ['video/mp4', 'video/mpeg', 'audio/mpeg', 'audio/mp3', 'image/jpeg', 'image/png', 'image/gif']
            if upload_file.content_type not in allowed_file_types:
                raise forms.ValidationError("Unsupported file type. Allowed types: MP4, MPEG, MP3, JPEG, PNG, GIF.")
        return upload_file

    def clean_youtube_url(self):
        youtube_url = self.cleaned_data.get('youtube_url')
        if not youtube_url:
            return youtube_url

        temp_content = Content(youtube_url=youtube_url)
        if not temp_content.youtube_video_id:
            raise forms.ValidationError("Enter a valid YouTube URL (watch, share, embed, or shorts link).")
        return youtube_url

    def clean(self):
        cleaned_data = super().clean()
        upload_file = cleaned_data.get('file')
        youtube_url = cleaned_data.get('youtube_url')

        if not upload_file and not youtube_url:
            raise forms.ValidationError("Upload a file or provide a YouTube link.")

        if upload_file and youtube_url:
            raise forms.ValidationError("Provide either a file upload or a YouTube link, not both.")

        return cleaned_data
    

class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ['text']
        widgets = {
            'text': forms.Textarea(attrs={
                'placeholder': 'Write your comment here...',
                'rows': 3,
                'class': 'form-control',
            }),
        }

class StartLiveStreamForm(forms.Form):
    title = forms.CharField(max_length=255)
    restrict_access = forms.BooleanField(required=False, label="Restrict access (voucher-only)")


class VoucherEntryForm(forms.Form):
    code = forms.CharField(label="Enter Voucher Code", max_length=20)
    

