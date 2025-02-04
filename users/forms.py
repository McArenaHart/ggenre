from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from .models import CustomUser, Role
from django.contrib.auth.forms import PasswordChangeForm
from django.core.exceptions import ValidationError




class UserRegistrationForm(UserCreationForm):
    role = forms.ChoiceField(choices=[])  # Initialize with empty choices

    class Meta:
        model = CustomUser
        fields = ['username', 'email', 'password1', 'password2', 'role']

    def __init__(self, *args, **kwargs):
        super(UserRegistrationForm, self).__init__(*args, **kwargs)
        # Filter out the 'admin' role from the choices
        self.fields['role'].choices = [choice for choice in Role.CHOICES if choice[0] != Role.ADMIN]


class LoginForm(AuthenticationForm):
    pass


class ProfileUpdateForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput,
        required=False,
        help_text="Leave blank to keep the current password.",
    )

    class Meta:
        model = CustomUser
        fields = ['username', 'email', 'profile_picture', 'bio']

    def clean_profile_picture(self):
        profile_picture = self.cleaned_data.get('profile_picture')
        if profile_picture:
            if profile_picture.size > 2 * 1024 * 1024:  # 2MB limit
                raise ValidationError("Profile picture size must be less than 2MB.")
            if not profile_picture.name.lower().endswith(('.png', '.jpg', '.jpeg')):
                raise ValidationError("Only PNG, JPG, and JPEG formats are allowed.")
        return profile_picture

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get('password')
        if password:
            user.set_password(password)
        if commit:
            user.save()
        return user
