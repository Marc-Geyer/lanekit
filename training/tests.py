from datetime import date, time

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from groups.models import Group, GroupMembership
from swimmers.models import Swimmer
from .models import Attendance, Location, RecurringSession, SessionInstance


class TrainerReportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('coach', password='pw')
        self.coach = Swimmer.objects.create(first_name='Co', last_name='Ach', user=self.user)
        self.group = Group.objects.create(name='Masters')
        GroupMembership.objects.create(group=self.group, swimmer=self.coach, role='trainer')
        self.swimmers = [
            Swimmer.objects.create(first_name=f'S{i}', last_name='X') for i in range(3)
        ]
        for s in self.swimmers:
            GroupMembership.objects.create(group=self.group, swimmer=s)
        self.pool = Location.objects.create(name='SH Süd', type='25m_Pool', city='Leipzig', street_address='x')
        self.rec = RecurringSession.objects.create(
            group=self.group, day_of_week=2, start_time=time(19, 0), end_time=time(20, 45),
            location=self.pool, valid_from=date(2026, 1, 1),
        )
        self.client.login(username='coach', password='pw')

    def _instance(self, day, coach_status, present_swimmers):
        inst = SessionInstance.objects.create(recurring_session=self.rec, date=day)
        Attendance.objects.create(session=inst, swimmer=self.coach, status=coach_status)
        for s in self.swimmers[:present_swimmers]:
            Attendance.objects.create(session=inst, swimmer=s, status='present')
        return inst

    def test_non_trainer_is_redirected(self):
        User.objects.create_user('plain', password='pw')
        self.client.login(username='plain', password='pw')
        self.assertRedirects(self.client.get(reverse('trainer_report')), reverse('calendar'))

    def test_rows_hours_and_swimmer_count(self):
        self._instance(date(2026, 7, 1), 'present', 2)
        self._instance(date(2026, 7, 8), 'present', 3)
        self._instance(date(2026, 10, 7), 'present', 3)   # other quarter
        r = self.client.get(reverse('trainer_report'), {'year': 2026, 'q': 3})
        rows = r.context['rows']
        self.assertEqual([x['swimmer_count'] for x in rows], [2, 3])   # coach not counted
        self.assertEqual(rows[0]['hours'], '1.75')
        self.assertEqual(r.context['total_hours'], '3.5')

    def test_only_sessions_with_trainer_present(self):
        self._instance(date(2026, 7, 1), 'absent', 3)
        self._instance(date(2026, 7, 8), 'unknown', 3)
        r = self.client.get(reverse('trainer_report'), {'year': 2026, 'q': 3})
        self.assertEqual(r.context['rows'], [])
        self.assertEqual(len(r.context['unmarked']), 1)

    def test_other_trainers_sessions_not_listed(self):
        other = Group.objects.create(name='Other')
        rec2 = RecurringSession.objects.create(
            group=other, day_of_week=4, start_time=time(20, 0), end_time=time(21, 0),
            valid_from=date(2026, 1, 1))
        inst = SessionInstance.objects.create(recurring_session=rec2, date=date(2026, 7, 3))
        Attendance.objects.create(session=inst, swimmer=self.coach, status='present')
        r = self.client.get(reverse('trainer_report'), {'year': 2026, 'q': 3})
        self.assertEqual(r.context['rows'], [])

    def test_invalid_params_fall_back(self):
        self.assertEqual(self.client.get(reverse('trainer_report'), {'year': 'x', 'q': 9}).status_code, 200)

    def test_nav_link_only_for_trainers(self):
        self.assertContains(self.client.get(reverse('calendar')), reverse('trainer_report'))
        User.objects.create_user('plain', password='pw')
        self.client.login(username='plain', password='pw')
        self.assertNotContains(self.client.get(reverse('calendar')), reverse('trainer_report'))
