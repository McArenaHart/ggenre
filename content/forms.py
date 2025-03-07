from django import forms
from .models import Content, Comment

class ContentUploadForm(forms.ModelForm):
    """
    ModelForm for uploading content by artists.
    """
    class Meta:
        model = Content
        fields = ['title', 'description', 'file','thumbnail', 'tags', 'genre']  # Include all required fields
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter content title'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'placeholder': 'Enter a description', 'rows': 5}),
            'file': forms.FileInput(attrs={'class': 'form-control'}),
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

