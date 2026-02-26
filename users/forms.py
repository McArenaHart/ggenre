from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from .models import CustomUser, Role, Announcement
from django.contrib.auth.forms import PasswordChangeForm
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User



CustomUser = get_user_model()

class UserRegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True, label="Email")
    password1 = forms.CharField(widget=forms.PasswordInput, label="Password")
    password2 = forms.CharField(widget=forms.PasswordInput, label="Confirm Password")
    
    role = forms.ChoiceField(choices=[choice for choice in Role.CHOICES if choice[0] != Role.ADMIN])
    terms_accepted = forms.BooleanField(required=True, label="I agree to the Terms and Conditions")

    class Meta:
        model = CustomUser
        fields = ['username', 'email', 'password1', 'password2', 'role']


    def clean_username(self):
        username = self.cleaned_data.get('username')
        if CustomUser.objects.filter(username=username).exists():
            raise forms.ValidationError("This username is already taken. Please choose another.")
        return username
    
    def clean_terms_accepted(self):
        terms_accepted = self.cleaned_data.get('terms_accepted')
        if not terms_accepted:
            raise ValidationError("You must agree to the Terms and Conditions to sign up.")
        return terms_accepted

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")

        if password1 and password2 and password1 != password2:
            raise forms.ValidationError("Passwords do not match.")

        return cleaned_data
    


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




class AnnouncementForm(forms.ModelForm):
    class Meta:
        model = Announcement
        fields = ["title", "message"]
        widgets = {
            "message": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
        }
