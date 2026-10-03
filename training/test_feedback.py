import json
from datetime import date
from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse
from swimmers.models import Swimmer
from groups.models import Group, GroupMembership
from training.models import RecurringSession, SessionInstance, Attendance


def mkuser(name, role='swimmer', superuser=False):
    u = User.objects.create_user(name, password='x', first_name=name, last_name='U')
    u.profile.role = role; u.profile.save()
    sw = Swimmer.objects.create(user=u, first_name=name, last_name='U')
    return u, sw


class Feedback(TestCase):
    def setUp(self):
        self.g1 = Group.objects.create(name='A'); self.g2 = Group.objects.create(name='B')
        self.tu, self.tsw = mkuser('trainer')                 # profile role swimmer, trainer of g1 only
        GroupMembership.objects.create(group=self.g1, swimmer=self.tsw, role='trainer')
        self.m1 = Swimmer.objects.create(first_name='Mia', last_name='Eins')
        self.m2 = Swimmer.objects.create(first_name='Max', last_name='Zwei')
        GroupMembership.objects.create(group=self.g1, swimmer=self.m1)
        GroupMembership.objects.create(group=self.g2, swimmer=self.m2)
        self.rs = RecurringSession.objects.create(group=self.g1, day_of_week=0,
            start_time='18:00', end_time='19:00', valid_from=date(2026,1,1))
        self.inst = SessionInstance.objects.create(recurring_session=self.rs, date=date(2026,10,5))
        self.c = self.client; self.c.login(username='trainer', password='x')

    # 3) Liste
    def test_list_shows_group_members(self):
        r = self.c.get(reverse('swimmer_list'))
        names = {s.pk for s in r.context['swimmers']}
        self.assertIn(self.m1.pk, names); self.assertNotIn(self.m2.pk, names)

    # 2) Bearbeiten
    def test_group_trainer_can_edit_member_not_foreign(self):
        self.assertTrue(self.c.get(reverse('swimmer_detail', args=[self.m1.pk])).context['can_edit'])
        self.assertFalse(self.c.get(reverse('swimmer_detail', args=[self.m2.pk])).context['can_edit'])
        r = self.c.post(reverse('swimmer_detail', args=[self.m1.pk]), {
            'first_name': 'Mia2', 'last_name': 'Eins', 'active': 'on'})
        self.assertEqual(r.status_code, 302); self.m1.refresh_from_db(); self.assertEqual(self.m1.first_name, 'Mia2')
        self.c.post(reverse('swimmer_detail', args=[self.m2.pk]), {'first_name': 'Hack', 'last_name': 'X', 'active': 'on'})
        self.m2.refresh_from_db(); self.assertEqual(self.m2.first_name, 'Max')

    def test_membership_scope(self):
        self.c.post(reverse('swimmer_membership_add', args=[self.m2.pk]), {'group': self.g2.pk})   # fremde Gruppe
        self.assertEqual(GroupMembership.objects.filter(swimmer=self.m2, group=self.g2).count(), 1)
        self.c.post(reverse('swimmer_membership_remove', args=[self.m2.pk, self.g2.pk]))
        self.assertTrue(GroupMembership.objects.get(swimmer=self.m2, group=self.g2).active)       # unverändert
        self.c.post(reverse('swimmer_membership_add', args=[self.m2.pk]), {'group': self.g1.pk, 'role': 'bogus'})
        self.assertEqual(GroupMembership.objects.get(swimmer=self.m2, group=self.g1).role, 'swimmer')

    def test_plain_swimmer_no_rights(self):
        mkuser('plain'); self.c.login(username='plain', password='x')
        self.assertFalse(self.c.get(reverse('swimmer_detail', args=[self.m1.pk])).context['can_edit'])

    # Gruppen-Erstellung
    def test_group_member_create(self):
        r = self.c.post(reverse('group_member_create', args=[self.g1.pk]),
                        {'first_name': 'Neu', 'last_name': 'Ling', 'role': 'swimmer', 'active': 'on'})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(GroupMembership.objects.filter(group=self.g1, swimmer__first_name='Neu').exists())
        r = self.c.post(reverse('group_member_create', args=[self.g2.pk]), {'first_name': 'X', 'last_name': 'Y', 'role': 'swimmer'})
        self.assertFalse(Swimmer.objects.filter(first_name='X').exists())

    # Session-Shortcut
    def post(self, **p):
        return self.c.post(reverse('session_add_swimmer_api', args=[self.inst.pk]), json.dumps(p), content_type='application/json')

    def test_add_new_and_join(self):
        r = self.post(first_name='  Nina ', last_name='Neu', join_group=True, phone='123')
        self.assertEqual(r.status_code, 200, r.content)
        sw = Swimmer.objects.get(first_name='Nina')
        self.assertTrue(GroupMembership.objects.get(group=self.g1, swimmer=sw).active)
        self.assertEqual(Attendance.objects.get(session=self.inst, swimmer=sw).status, 'present')
        self.assertTrue(r.json()['created'])

    def test_add_guest_no_join_and_existing(self):
        r = self.post(swimmer_id=self.m2.pk, join_group=False)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(GroupMembership.objects.filter(group=self.g1, swimmer=self.m2).exists())
        self.assertEqual(Attendance.objects.get(session=self.inst, swimmer=self.m2).status, 'present')

    def test_duplicate_and_validation_and_perms(self):
        self.assertEqual(self.post(first_name='mia', last_name='EINS').status_code, 409)
        j = self.post(first_name='mia', last_name='EINS').json(); self.assertEqual(j['ids'], [self.m1.pk])
        self.assertEqual(self.post(first_name='', last_name='x').status_code, 400)
        self.assertEqual(self.post(swimmer_id=99999).status_code, 404)
        mkuser('plain'); self.c.login(username='plain', password='x')
        self.assertEqual(self.post(first_name='A', last_name='B').status_code, 403)
        self.c.logout(); self.assertEqual(self.post(first_name='A', last_name='B').status_code, 302)

    def test_modal_has_options_only_for_trainer(self):
        r = self.c.get(reverse('session_modal', args=[self.rs.pk, '2026-10-05']))
        html = r.json()['html']
        self.assertIn('addSwimmerPanel', html); self.assertIn('Max Zwei', html)
        self.assertIn('Mia Eins', html)   # already on the list -> still searchable (shown as 'in Liste')
        self.c.logout()
        html = self.c.get(reverse('session_modal', args=[self.rs.pk, '2026-10-05'])).json()['html']
        self.assertNotIn('addSwimmerPanel', html); self.assertNotIn('Max Zwei', html)

    def test_picker_options_contain_groups_and_all_active(self):
        Swimmer.objects.create(first_name='Off', last_name='Duty', active=False)
        html = self.c.get(reverse('session_modal', args=[self.rs.pk, '2026-10-05'])).json()['html']
        self.assertIn('Max Zwei', html); self.assertNotIn('Off Duty', html)
        self.assertIn('B', html)
