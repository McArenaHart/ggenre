from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from users.models import CustomUser, Role
from .models import PeerChatThread
from .services import peer_unread_total, users_can_peer_chat


class PeerUnreadPerformanceTests(TestCase):
    def test_bulk_unread_matches_access_rules_and_both_sides(self):
        older = CustomUser.objects.create_user(username="older", role=Role.FAN)
        user = CustomUser.objects.create_user(username="reader", role=Role.ARTIST)
        others = [CustomUser.objects.create_user(username=f"peer_{i}", role=Role.FAN) for i in range(8)]
        for i, other in enumerate([older, *others]):
            first, second = PeerChatThread.ordered_users(user, other)
            PeerChatThread.objects.create(user_one=first, user_two=second, admin_approved=i < 3, unlocked_until=timezone.now()+timedelta(hours=1) if i == 3 else timezone.now()-timedelta(hours=1), unread_count_user_one=5, unread_count_user_two=7)
        others[0].is_suspended_by_admin = True
        others[0].save()
        others[1].is_active = False
        others[1].save()
        others[2].role = Role.ADMIN
        others[2].save()
        threads = PeerChatThread.objects.filter(user_one=user) | PeerChatThread.objects.filter(user_two=user)
        expected = sum(thread.unread_count_for(user) for thread in threads.select_related("user_one", "user_two") if users_can_peer_chat(user, thread.other_user(user)))
        with self.assertNumQueries(1):
            self.assertEqual(peer_unread_total(user), expected)
        for i in range(25):
            partner = CustomUser.objects.create_user(username=f"more_peer_{i}", role=Role.FAN)
            PeerChatThread.objects.create(user_one=user, user_two=partner, admin_approved=True, unread_count_user_one=2)
        with self.assertNumQueries(1):
            self.assertEqual(peer_unread_total(user), expected + 50)

    def test_suspended_and_admin_users_have_no_peer_unread_access(self):
        user = CustomUser.objects.create_user(username="blocked_reader", role=Role.ARTIST, is_suspended_by_admin=True)
        with self.assertNumQueries(0):
            self.assertEqual(peer_unread_total(user), 0)
        user.is_suspended_by_admin = False
        user.role = Role.ADMIN
        with self.assertNumQueries(0):
            self.assertEqual(peer_unread_total(user), 0)


    def test_direct_chat_loads_each_controller_once_with_and_without_widget(self):
        from django.urls import reverse
        admin = CustomUser.objects.create_user(username="perf_admin", role=Role.ADMIN)
        user = CustomUser.objects.create_user(username="perf_player", role=Role.ARTIST)
        partner = CustomUser.objects.create_user(username="perf_partner", role=Role.FAN)
        PeerChatThread.objects.create(user_one=user, user_two=partner, admin_approved=True)
        self.client.force_login(user)
        for other in (partner, admin):
            response = self.client.get(reverse("chatapp:direct", args=[other.pk]))
            self.assertEqual(response.status_code, 200)
            html = response.content.decode()
            self.assertEqual(html.count('src="/static/js/pages/chatapp.js?'), 1)
            self.assertEqual(html.count('src="/static/js/pages/chatapp_missions.js?'), 1)
