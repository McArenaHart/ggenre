from django import forms

from users.models import CustomUser, Role

from .models import LiveStream


class LiveStreamForm(forms.ModelForm):
    class Meta:
        model = LiveStream
        fields = ["title", "description", "scheduled_for", "is_restricted", "allow_free_access"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control", "placeholder": "Stream title"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            "scheduled_for": forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
            "is_restricted": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "allow_free_access": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class LiveStreamAccessForm(forms.Form):
    user = forms.ModelChoiceField(
        queryset=CustomUser.objects.none(),
        widget=forms.Select(attrs={"class": "form-control"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user"].queryset = CustomUser.objects.exclude(role=Role.ADMIN).order_by("username")
