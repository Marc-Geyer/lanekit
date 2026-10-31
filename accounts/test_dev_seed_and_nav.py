"""The dev demo world must really contain every access scenario, and the navbar must offer the own profile."""
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts import permissions as perm
from accounts.permissions import Level
from groups.models import Group
from swimmers.models import PersonChangeRequest, Swimmer
from training.models import SessionInstance


def seed(**kw):
    call_command('seed_dev_data', stdout=StringIO(), force=True, **kw)


class SeedDevDataTests(TestCase):
    def test_every_scenario_is_present(self):
        seed()
        u = {name: User.objects.get(username=f'demo_{name}') for name in
             ('admin', 'trainer_a', 'trainer_b', 'trainer_free', 'assistant', 'swimmer_a', 'swimmer_b')}
        a, b = (Group.objects.get(name=f'Demo Group {x}').pk for x in 'AB')
        self.assertEqual(perm.level(u['admin']), Level.ADMIN)
        self.assertEqual(perm.level(u['trainer_a']), Level.TRAINER)
        self.assertEqual(perm.level(u['trainer_free']), Level.TRAINER)
        self.assertEqual(perm.level(u['assistant']), Level.ASSISTANT)
        self.assertEqual(perm.level(u['swimmer_a']), Level.SWIMMER)
        self.assertEqual(perm.group_level(u['trainer_a'], a), Level.TRAINER)
        self.assertEqual(perm.group_level(u['trainer_a'], b), Level.SWIMMER)
        self.assertEqual(perm.group_level(u['trainer_free'], a), Level.SWIMMER)
        self.assertEqual(perm.group_level(u['assistant'], a), Level.ASSISTANT)
        self.assertEqual(perm.group_level(u['assistant'], b), Level.SWIMMER)
        for user in u.values():
            self.assertTrue(user.check_password('demo'))
        self.assertTrue(User.objects.filter(username='demo_unlinked', swimmer__isnull=True).exists())
        self.assertTrue(PersonChangeRequest.objects.filter(status='pending').exists())

    def test_finished_and_upcoming_sessions_exist(self):
        seed()
        sv = perm.SessionView
        swimmer_a = User.objects.get(username='demo_swimmer_a')
        views = {perm.session_view(swimmer_a, i) for i in SessionInstance.objects.filter(
            recurring_session__group__name='Demo Group A')}
        self.assertEqual(views, {sv.PARTICIPANT, sv.NONE})        # last week visible, next week not yet

    def test_idempotent_and_reset(self):
        seed()
        counts = (User.objects.count(), Swimmer.objects.count(), SessionInstance.objects.count())
        seed()
        self.assertEqual((User.objects.count(), Swimmer.objects.count(), SessionInstance.objects.count()), counts)
        seed(reset=True)
        self.assertEqual((User.objects.count(), Swimmer.objects.count(), SessionInstance.objects.count()), counts)
        call_command('seed_dev_data', stdout=StringIO(), force=True, reset=True)

    def test_reset_leaves_real_data_alone(self):
        real = Swimmer.objects.create(first_name='Real', last_name='Member', email='real@club.org')
        seed()
        seed(reset=True)
        self.assertTrue(Swimmer.objects.filter(pk=real.pk).exists())

    def test_refuses_without_debug(self):
        with override_settings(DEBUG=False):
            with self.assertRaises(CommandError):
                call_command('seed_dev_data', stdout=StringIO())


class NavbarProfileLinkTests(TestCase):
    def setUp(self):
        seed()

    def nav(self, username, url_name='calendar', **kwargs):
        self.client.force_login(User.objects.get(username=username))
        r = self.client.get(reverse(url_name, kwargs=kwargs))
        return r, r.content.decode()

    def test_everybody_with_a_person_gets_the_profile_link_trainers_keep_people(self):
        for username in ('demo_swimmer_a', 'demo_assistant', 'demo_trainer_a', 'demo_admin'):
            user = User.objects.get(username=username)
            own = reverse('swimmer_detail', args=[user.swimmer.pk])
            _, html = self.nav(username)
            self.assertIn(f'href="{own}"', html, username)
        _, plain = self.nav('demo_swimmer_a')
        self.assertNotIn(f'href="{reverse("swimmer_list")}"', plain)           # swimmers have no people list
        for username in ('demo_assistant', 'demo_trainer_a', 'demo_admin'):
            _, html = self.nav(username)
            self.assertIn(f'href="{reverse("swimmer_list")}"', html, username)

    def test_active_state_is_separated(self):
        trainer = User.objects.get(username='demo_trainer_a')
        r, _ = self.nav('demo_trainer_a', 'swimmer_detail', pk=trainer.swimmer.pk)
        self.assertTrue(r.context['nav_on_own_person'])
        other = Swimmer.objects.get(email='emil.alpha@demo.lanekit.test')
        r, _ = self.nav('demo_trainer_a', 'swimmer_detail', pk=other.pk)
        self.assertFalse(r.context['nav_on_own_person'])
        r, _ = self.nav('demo_trainer_a', 'swimmer_list')
        self.assertFalse(r.context['nav_on_own_person'])

    def test_anonymous_has_no_profile_link(self):
        self.client.logout()
        r = self.client.get(reverse('calendar'))
        self.assertIsNone(r.context['own_swimmer_id'])
