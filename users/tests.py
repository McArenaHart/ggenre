from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

CustomUser = get_user_model()

class UsersAppTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.register_url = reverse('register')
        self.login_url = reverse('login')
        self.logout_url = reverse('logout')
        self.dashboard_url = reverse('dashboard')
        self.profile_url = reverse('profile')

        # Sample data for users
        self.admin_data = {
            "username": "admin_user",
            "email": "admin@example.com",
            "password": "adminpass123",
            "role": "admin",
        }
        self.artist_data = {
            "username": "artist_user",
            "email": "artist@example.com",
            "password": "artistpass123",
            "role": "artist",
        }
        self.fan_data = {
            "username": "fan_user",
            "email": "fan@example.com",
            "password": "fanpass123",
            "role": "fan",
        }

        # Create sample users
        self.admin_user = CustomUser.objects.create_user(**self.admin_data)
        self.artist_user = CustomUser.objects.create_user(**self.artist_data)
        self.fan_user = CustomUser.objects.create_user(**self.fan_data)

    def test_register_view(self):
        response = self.client.post(self.register_url, {
            "username": "new_user",
            "email": "new_user@example.com",
            "password1": "newuserpass123",
            "password2": "newuserpass123",
            "role": "fan"
        })
        self.assertEqual(response.status_code, 302)  # Should redirect to the dashboard
        self.assertTrue(CustomUser.objects.filter(username="new_user").exists())

    def test_login_view(self):
        response = self.client.post(self.login_url, {
            "username": self.admin_user.username,
            "password": self.admin_data["password"],
        })
        self.assertEqual(response.status_code, 302)  # Should redirect to the dashboard
        self.assertIn('_auth_user_id', self.client.session)

    def test_logout_view(self):
        self.client.login(username=self.admin_user.username, password=self.admin_data["password"])
        response = self.client.get(self.logout_url)
        self.assertEqual(response.status_code, 302)  # Should redirect to login
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_dashboard_access(self):
        self.client.login(username=self.admin_user.username, password=self.admin_data["password"])
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)  # Dashboard should be accessible

        self.client.login(username=self.artist_user.username, password=self.artist_data["password"])
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)

        self.client.login(username=self.fan_user.username, password=self.fan_data["password"])
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)

    def test_dashboard_roles(self):
        self.client.login(username=self.admin_user.username, password=self.admin_data["password"])
        response = self.client.get(self.dashboard_url)
        self.assertTemplateUsed(response, 'users/admin_dashboard.html')

        self.client.login(username=self.artist_user.username, password=self.artist_data["password"])
        response = self.client.get(self.dashboard_url)
        self.assertTemplateUsed(response, 'users/artist_dashboard.html')

        self.client.login(username=self.fan_user.username, password=self.fan_data["password"])
        response = self.client.get(self.dashboard_url)
        self.assertTemplateUsed(response, 'users/fan_dashboard.html')

    def test_profile_update(self):
        self.client.login(username=self.artist_user.username, password=self.artist_data["password"])

        # Create a valid image file for testing
        valid_image = SimpleUploadedFile(
            "profile.jpg", 
            b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xFF\xFF\xFF\x21\xF9\x04\x01\x00\x00\x01\x00\x2C\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x4C\x01\x00\x3B', 
            content_type="image/jpeg"
        )

        # Update the profile with valid data
        response = self.client.post(self.profile_url, {
            "username": self.artist_user.username,  # Required field
            "email": self.artist_user.email,  # Optional but good to include
            "bio": "Updated bio",
            "profile_picture": valid_image,  # Valid image file
        })

        # Check if the response redirects after successful form submission
        self.assertEqual(response.status_code, 302)  # Should redirect to profile

        # Refresh the user instance and validate updates
        self.artist_user.refresh_from_db()
        self.assertEqual(self.artist_user.bio, "Updated bio")


    def test_access_restrictions(self):
        # Ensure dashboard is restricted for unauthenticated users
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 302)  # Redirect to login

        # Ensure profile is restricted for unauthenticated users
        response = self.client.get(self.profile_url)
        self.assertEqual(response.status_code, 302)  # Redirect to login


# users/tests.py
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from .models import Announcement, DismissedAnnouncement, Role

CustomUser = get_user_model()

class AnnouncementTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(username='testuser', password='testpass', role=Role.FAN)
        self.admin = CustomUser.objects.create_user(username='admin', password='adminpass', role=Role.ADMIN, is_staff=True)
        self.announcement = Announcement.objects.create(title='Test', message='Test message', created_by=self.admin)

    def test_get_announcements(self):
        self.client.login(username='testuser', password='testpass')
        response = self.client.get(reverse('get_announcements'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('announcements', response.json())

    def test_dismiss_announcement(self):
        self.client.login(username='testuser', password='testpass')
        response = self.client.post(reverse('dismiss_announcement', args=[self.announcement.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(DismissedAnnouncement.objects.filter(user=self.user, announcement=self.announcement).exists())

class UsersAppTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(username='testuser', password='testpass', role=Role.FAN)
        self.admin = CustomUser.objects.create_user(username='admin', password='adminpass', role=Role.ADMIN, is_staff=True)

    def test_dashboard_access(self):
        self.client.login(username='testuser', password='testpass')
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)

    def test_dashboard_roles(self):
        self.client.login(username='admin', password='adminpass')
        response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'users/admin_dashboard.html')

    def test_register_view(self):
        response = self.client.post(reverse('register'), data={
            'username': 'newuser',
            'password1': 'complexpassword123',
            'password2': 'complexpassword123',
        })
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('verify_otp', args=[CustomUser.objects.latest('id').id]))