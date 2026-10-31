import json
from datetime import date, time

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from groups.models import Group, GroupMembership
from swimmers.models import Swimmer
from . import stats
from .forms import RecurringSessionForm
from .models import Attendance, Location, RecurringSession, SessionInstance


def mkuser(name, role='swimmer'):
    u = User.objects.create_user(name, password='x')
    u.profile.role = role
    u.profile.save()
    return u, Swimmer.objects.create(first_name=name.title(), last_name='T', user=u)


class StatsBase(TestCase):
    def setUp(self):
        self.g1 = Group.objects.create(name='A')
        self.g2 = Group.objects.create(name='B')
        self.coach_u, self.coach = mkuser('coach')
        GroupMembership.objects.create(group=self.g1, swimmer=self.coach, role='trainer')
        self.mia = Swimmer.objects.create(first_name='Mia', last_name='Eins')
        self.max = Swimmer.objects.create(first_name='Max', last_name='Zwei')
        for s in (self.mia, self.max):
            GroupMembership.objects.create(group=self.g1, swimmer=s)
        self.pool = Location.objects.create(name='Pool', type='25m_Pool', city='L', street_address='x', lanes=6)
        self.rs = RecurringSession.objects.create(
            group=self.g1, day_of_week=0, start_time=time(18), end_time=time(19),
            valid_from=date(2026, 1, 1), location=self.pool, lanes=4)
        self.rs2 = RecurringSession.objects.create(
            group=self.g2, day_of_week=1, start_time=time(18), end_time=time(19),
            valid_from=date(2026, 1, 1))

    def session(self, day, marks, rs=None, **kw):
        inst = SessionInstance.objects.create(recurring_session=rs or self.rs, date=day, **kw)
        for swimmer, status in marks.items():
            Attendance.objects.create(session=inst, swimmer=swimmer, status=status)
        return inst


class RangeTests(TestCase):
    def test_presets(self):
        today = date(2026, 10, 22)
        self.assertEqual(stats.resolve_range({'range': 'prev_month'}, today),
                         ('prev_month', date(2026, 9, 1), date(2026, 9, 30)))
        self.assertEqual(stats.resolve_range({'range': 'prev_quarter'}, today),
                         ('prev_quarter', date(2026, 7, 1), date(2026, 9, 30)))
        self.assertEqual(stats.resolve_range({'range': 'prev_quarter'}, date(2026, 2, 3))[1:],
                         (date(2025, 10, 1), date(2025, 12, 31)))
        # current quarter is clamped to today
        self.assertEqual(stats.resolve_range({'range': 'this_quarter'}, today)[1:],
                         (date(2026, 10, 1), today))
        self.assertEqual(stats.resolve_range({}, today)[0], '30d')

    def test_custom_and_invalid(self):
        today = date(2026, 10, 22)
        self.assertEqual(stats.resolve_range(
            {'range': 'custom', 'from': '2026-08-01', 'to': '2026-08-31'}, today),
            ('custom', date(2026, 8, 1), date(2026, 8, 31)))
        self.assertEqual(stats.resolve_range(
            {'range': 'custom', 'from': 'x', 'to': '2026-08-31'}, today)[0], '30d')
        self.assertEqual(stats.resolve_range(
            {'range': 'custom', 'from': '2026-09-01', 'to': '2026-08-01'}, today)[0], '30d')
        self.assertEqual(stats.resolve_range({'range': 'bogus'}, today)[0], '30d')


class PersonStatsTests(StatsBase):
    def test_counts_quota_streak_and_optional(self):
        self.session(date(2026, 9, 7), {self.mia: 'present'})
        self.session(date(2026, 9, 14), {self.mia: 'excused'})
        self.session(date(2026, 9, 21), {self.mia: 'absent'})
        self.session(date(2026, 9, 28), {self.mia: 'unknown'})            # ignored for streak
        self.session(date(2026, 10, 5), {self.mia: 'absent'}, is_optional=True)
        args = (self.mia, {self.g1.pk}, date(2026, 9, 1), date(2026, 10, 31))
        s = stats.person_stats(*args)
        self.assertEqual((s['present'], s['absent'], s['excused'], s['unknown']), (1, 1, 1, 1))
        self.assertEqual(s['quota'], 33.3)
        self.assertEqual(s['excused_share'], 50.0)
        self.assertEqual(s['miss_streak'], 2)
        self.assertEqual(s['optional_hidden'], 1)
        s = stats.person_stats(*args, include_optional=True)
        self.assertEqual(s['absent'], 2)
        self.assertEqual(s['miss_streak'], 3)

    def test_only_visible_groups_and_empty(self):
        GroupMembership.objects.create(group=self.g2, swimmer=self.mia)
        self.session(date(2026, 9, 7), {self.mia: 'absent'}, rs=self.rs2)
        s = stats.person_stats(self.mia, {self.g1.pk}, date(2026, 9, 1), date(2026, 9, 30))
        self.assertEqual(s['rows'], [])
        self.assertIsNone(s['quota'])

    def test_detail_view_permissions(self):
        self.session(date.today(), {self.mia: 'present'})
        url = reverse('swimmer_detail', args=[self.mia.pk])
        # profile trainer of NO group of the person: basic info + swim times only, no attendance stats
        mkuser('boss', role='trainer')
        self.client.login(username='boss', password='x')
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('stats', r.context)
        self.assertIn('perf_data', r.context)
        # trainer (profile trainer + trainer of the person's group): statistics over their own groups
        _, head = mkuser('head', role='trainer')
        GroupMembership.objects.create(group=self.g1, swimmer=head, role='trainer')
        self.client.login(username='head', password='x')
        self.assertEqual(self.client.get(url).context['stats']['present'], 1)
        mkuser('chief', role='admin')
        self.client.login(username='chief', password='x')
        self.assertIn('stats', self.client.get(url).context)
        # an assistant (profile swimmer, trainer entry in the group) gets no statistics
        self.client.login(username='coach', password='x')
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('stats', r.context)
        mkuser('plain')
        self.client.login(username='plain', password='x')
        self.assertEqual(self.client.get(url).status_code, 302)       # not even the record


class GroupStatsTests(StatsBase):
    def test_trainers_excluded_and_ranking(self):
        self.session(date(2026, 9, 7), {self.coach: 'present', self.mia: 'present', self.max: 'absent'})
        self.session(date(2026, 9, 14), {self.coach: 'present', self.mia: 'present', self.max: 'excused'})
        g = stats.group_stats(self.g1, date(2026, 9, 1), date(2026, 9, 30))
        self.assertEqual(g['summary']['present'], 2)          # coach not counted
        self.assertEqual(g['summary']['sessions'], 2)
        self.assertEqual(g['summary']['avg_present'], 1.0)
        self.assertEqual([p['swimmer'] for p in g['people']], [self.max, self.mia])
        self.assertEqual(g['rows'][0]['absent'], 1)

    def test_optional_and_per_lane(self):
        self.session(date(2026, 9, 7), {self.mia: 'present', self.max: 'present'})            # 4 lanes
        self.session(date(2026, 9, 14), {self.mia: 'present'}, is_optional=True)
        no_lane = self.session(date(2026, 9, 21), {self.mia: 'present'})
        SessionInstance.objects.filter(pk=no_lane.pk).update(lanes=None)
        g = stats.group_stats(self.g1, date(2026, 9, 1), date(2026, 9, 30), per_lane=True)
        self.assertEqual(g['summary']['sessions'], 2)
        self.assertEqual(g['summary']['optional_hidden'], 1)
        self.assertEqual(g['summary']['avg_per_lane'], 0.5)      # only the 4-lane session
        self.assertEqual(g['summary']['sessions_without_lanes'], 1)
        g = stats.group_stats(self.g1, date(2026, 9, 1), date(2026, 9, 30), include_optional=True)
        self.assertEqual(g['summary']['sessions'], 3)

    def test_view_permissions(self):
        url = reverse('group_stats', args=[self.g1.pk])
        other = reverse('group_stats', args=[self.g2.pk])
        detail = reverse('group_detail', args=[self.g1.pk])
        # assistant (profile swimmer, trainer entry): no statistics, no link
        self.client.login(username='coach', password='x')
        self.assertRedirects(self.client.get(url), reverse('group_list'))
        self.assertNotContains(self.client.get(detail), url)
        mkuser('plain')
        self.client.login(username='plain', password='x')
        self.assertEqual(self.client.get(url).status_code, 302)
        # profile trainer without a trainer entry in the group: nothing
        mkuser('boss', role='trainer')
        self.client.login(username='boss', password='x')
        self.assertEqual(self.client.get(url).status_code, 302)
        # trainer of g1: statistics of g1 only
        _, head = mkuser('head', role='trainer')
        GroupMembership.objects.create(group=self.g1, swimmer=head, role='trainer')
        self.client.login(username='head', password='x')
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get(url, {'range': 'prev_month', 'lanes': '1', 'optional': '1'}).status_code, 200)
        self.assertEqual(self.client.get(other).status_code, 302)
        self.assertContains(self.client.get(detail), url)
        # admin: everything
        mkuser('chief', role='admin')
        self.client.login(username='chief', password='x')
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get(other).status_code, 200)


class LaneModelTests(StatsBase):
    def test_validation_against_location(self):
        self.rs.lanes = 7
        with self.assertRaises(ValidationError):
            self.rs.clean()
        self.rs.location = None                      # location stays optional
        self.rs.clean()
        form = RecurringSessionForm(data={
            'day_of_week': 0, 'start_time': '18:00', 'end_time': '19:00', 'location': self.pool.pk,
            'lanes': 8, 'valid_from': '2026-01-01', 'active': 'on'})
        self.assertFalse(form.is_valid())
        self.assertIn('lanes', form.errors)
        self.pool.lanes = 3                          # location shrinks below existing slot
        with self.assertRaises(ValidationError):
            self.pool.clean()

    def test_new_session_defaults_and_instance_copies(self):
        rs = RecurringSession.objects.create(
            group=self.g1, day_of_week=3, start_time=time(18), end_time=time(19),
            valid_from=date(2026, 1, 1), location=self.pool)
        self.assertEqual(rs.lanes, 6)                # defaulted from the location
        self.assertEqual(self.session(date(2026, 9, 7), {}).lanes, 4)   # copied from the slot

    def test_backfill_when_slot_lanes_added_later(self):
        rs = self.rs2
        old = self.session(date(2026, 9, 7), {}, rs=rs)
        self.assertIsNone(old.lanes)
        rs.lanes = 5
        rs.save()
        old.refresh_from_db()
        self.assertEqual(old.lanes, 5)
        # later change leaves history alone
        rs.lanes = 3
        rs.save()
        old.refresh_from_db()
        self.assertEqual(old.lanes, 5)

    def test_corrected_instance_is_not_overwritten(self):
        rs = self.rs2
        inst = self.session(date(2026, 9, 7), {}, rs=rs, lanes=2)
        rs.lanes = 5
        rs.save()
        inst.refresh_from_db()
        self.assertEqual(inst.lanes, 2)

    def test_backfill_when_location_lanes_added_later(self):
        hall = Location.objects.create(name='Hall', type='25m_Pool', city='L', street_address='x')
        rs = RecurringSession.objects.create(
            group=self.g1, day_of_week=4, start_time=time(18), end_time=time(19),
            valid_from=date(2026, 1, 1), location=hall)
        inst = self.session(date(2026, 9, 11), {}, rs=rs)
        self.assertIsNone(rs.lanes)
        hall.lanes = 5
        hall.save()
        rs.refresh_from_db(); inst.refresh_from_db()
        self.assertEqual((rs.lanes, inst.lanes), (5, 5))


class SessionSettingsApiTests(StatsBase):
    def post(self, inst, payload):
        return self.client.post(reverse('session_settings_api', args=[inst.pk]),
                                json.dumps(payload), content_type='application/json')

    def test_trainer_updates_and_validation(self):
        inst = self.session(date(2026, 9, 7), {})
        self.client.login(username='coach', password='x')
        r = self.post(inst, {'is_optional': True, 'lanes': 3})
        self.assertEqual(r.status_code, 200)
        inst.refresh_from_db()
        self.assertTrue(inst.is_optional); self.assertEqual(inst.lanes, 3)
        self.assertEqual(self.post(inst, {'lanes': 9}).status_code, 400)      # more than the pool has
        self.assertEqual(self.post(inst, {'lanes': 0}).status_code, 400)
        self.assertEqual(self.post(inst, {'lanes': 'x'}).status_code, 400)
        self.assertEqual(self.post(inst, {'lanes': None}).status_code, 200)
        inst.refresh_from_db()
        self.assertIsNone(inst.lanes)

    def test_non_trainer_forbidden(self):
        inst = self.session(date(2026, 9, 7), {})
        mkuser('plain')
        self.client.login(username='plain', password='x')
        self.assertEqual(self.post(inst, {'is_optional': True}).status_code, 403)
