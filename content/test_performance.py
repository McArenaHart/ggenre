from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.urls import reverse

from users.models import CustomUser, Role
from .models import Comment, Content, Vote
from .querysets import with_content_stats
from .views import get_featured_contents, track_content_view


class ContentReadPerformanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.artist = CustomUser.objects.create_user(username="read_artist", role=Role.ARTIST)
        cls.fans = [CustomUser.objects.create_user(username=f"read_fan_{i}", role=Role.FAN) for i in range(3)]
        cls.posts = [Content.objects.create(artist=cls.artist, title=f"Read post {i}", file="content/test.mp4", is_approved=True) for i in range(25)]
        cls.post = cls.posts[0]
        cls.post.viewers.add(*cls.fans)
        Vote.objects.bulk_create([Vote(content=cls.post, fan=fan, base_value=8, value=8, otp_code="FREE") for fan in cls.fans[:2]])

    def test_feed_counts_do_not_grow_queries_or_multiply_relations(self):
        for limit in (1, 25):
            with self.assertNumQueries(1):
                items = list(get_featured_contents(limit=limit))
                for item in items:
                    self.assertTrue(item.safe_file_url)
                    self.assertEqual(item.artist.username, self.artist.username)
                    self.assertGreaterEqual(item.view_count, 0)
                    self.assertGreaterEqual(item.vote_count, 0)
        item = with_content_stats(Content.objects.all()).get(pk=self.post.pk)
        self.assertEqual((item.view_count, item.vote_count), (3, 2))
        empty = with_content_stats(Content.objects.all()).get(pk=self.posts[1].pk)
        self.assertEqual((empty.view_count, empty.vote_count), (0, 0))

    def test_counts_are_fresh_on_each_query_and_view_increment(self):
        item = with_content_stats(Content.objects.all()).get(pk=self.posts[1].pk)
        self.assertEqual(item.view_count, 0)
        self.assertEqual(track_content_view(item, self.fans[0]), 1)
        self.assertEqual(item.view_count, 1)
        track_content_view(item, self.fans[0])
        self.assertEqual(item.view_count, 1)
        Vote.objects.create(content=item, fan=self.fans[0], base_value=9, value=9, otp_code="FREE")
        fresh = with_content_stats(Content.objects.all()).get(pk=item.pk)
        self.assertEqual((fresh.view_count, fresh.vote_count), (1, 1))

    def test_comment_authors_are_loaded_in_bulk(self):
        self.client.force_login(self.fans[0])
        url = reverse("content_detail", args=[self.post.pk])
        self.client.get(url)
        with CaptureQueriesContext(connection) as before:
            self.assertEqual(self.client.get(url).status_code, 200)
        Comment.objects.bulk_create([Comment(content=self.post, user=self.fans[i % 3], text=f"Visible comment {i}") for i in range(30)])
        with CaptureQueriesContext(connection) as after:
            response = self.client.get(url)
            self.assertContains(response, "Visible comment 29")
        self.assertEqual(len(before), len(after))
