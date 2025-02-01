from django.test import TestCase
from django.urls import reverse
from .models import Content, ArtistUploadLimit
from .forms import ContentUploadForm
from django.core.mail import outbox
# Import the custom user model
from users.models import CustomUser

# Test Models
class ContentModelTest(TestCase):

    def setUp(self):
        # Use CustomUser instead of User
        self.user = CustomUser.objects.create_user(username='artist1', password='password')
        self.content = Content.objects.create(title="Test Content", description="Test", artist=self.user)

    def test_content_creation(self):
        self.assertEqual(self.content.title, "Test Content")
        self.assertEqual(self.content.artist.username, "artist1")

    def test_upload_limit(self):
        upload_limit = ArtistUploadLimit.objects.create(artist=self.user, uploads_used=0, upload_limit=5)
        self.assertTrue(upload_limit.has_upload_quota())

# Test Views
class ContentViewTest(TestCase):

    def setUp(self):
        # Use CustomUser instead of User
        self.user = CustomUser.objects.create_user(username='artist1', password='password')
        self.client.login(username='artist1', password='password')

    def test_upload_content_view(self):
        response = self.client.get(reverse('upload_content'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'content/upload.html')

    def test_list_content_view(self):
        response = self.client.get(reverse('content_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Content")

# Test Forms
class ContentFormTest(TestCase):

    def setUp(self):
        # Use CustomUser instead of User
        self.user = CustomUser.objects.create_user(username='artist1', password='password')

    def test_valid_form(self):
        form_data = {'title': 'Test Content', 'description': 'Test Description', 'file': 'testfile.mp4'}
        form = ContentUploadForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_invalid_form(self):
        form_data = {'title': '', 'description': 'Test Description', 'file': 'testfile.mp4'}
        form = ContentUploadForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('title', form.errors)

# Test Authentication & Authorization
class AuthenticationTest(TestCase):

    def setUp(self):
        # Use CustomUser instead of User
        self.user = CustomUser.objects.create_user(username='artist1', password='password')

    def test_redirects_if_not_logged_in(self):
        response = self.client.get(reverse('upload_content'))
        self.assertRedirects(response, '/users/login/?next=/content/upload/')

    def test_upload_content_permission(self):
        self.client.login(username='artist1', password='password')
        response = self.client.get(reverse('upload_content'))
        self.assertEqual(response.status_code, 200)

# Run the tests
if __name__ == '__main__':
    import unittest
    unittest.main()
