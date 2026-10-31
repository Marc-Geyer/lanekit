"""Shared fixture for the permission tests (see accounts/permissions.py for the rules).

World
-----
Groups A and B. Session A (Mondays 18-19) has a FINISHED instance (``past``) and an upcoming one
(``future``).

====================  ================  =================================================
role key              profile role      entries
====================  ================  =================================================
``admin``             admin
``trainer_a``         trainer           trainer of A
``trainer_b``         trainer           trainer of B
``trainer_free``      trainer           trainer of nothing, member of nothing
``assist_a``          swimmer           trainer entry in A (= assistant), swimmer in B
``swim_a``            swimmer           swimmer in A (own record can only be proposed)
``swim_b``            swimmer           swimmer in B
``anon``              –                 not logged in
====================  ================  =================================================
"""
import io
import json
import tempfile
from datetime import date, time

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, TransactionTestCase, override_settings

from groups.models import Group, GroupMembership
from swimmers.models import Swimmer
from training.models import (
    Attendance, Location, PerformanceResult, RecurringSession, SessionInstance, TrainingPlanEntry,
)

ROLES = ['anon', 'swim_a', 'swim_b', 'assist_a', 'trainer_a', 'trainer_b', 'trainer_free', 'admin']
LOGGED_IN = [r for r in ROLES if r != 'anon']
PAST = date(2026, 1, 5)      # a Monday, long finished
FUTURE = date(2030, 1, 7)    # a Monday, not yet happened

_MEDIA = tempfile.mkdtemp(prefix='lanekit-test-media-')


def png(name='p.png'):
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (4, 4), 'red').save(buf, 'PNG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')


def make_user(name, profile_role='swimmer'):
    user = User.objects.create_user(name, email=f'{name}@example.org', password='x',
                                    first_name=name.title(), last_name='User')
    user.profile.role = profile_role
    user.profile.phone = '0123'          # account and person must agree, or the sync signal rewrites the person
    user.profile.save()
    swimmer = Swimmer.objects.create(user=user, first_name=name.title(), last_name='User',
                                     email=f'{name}@example.org', phone='0123',
                                     date_of_birth=date(2000, 1, 1))
    return user, swimmer


class PermWorld:
    def setUp(self):
        self.grp_a = Group.objects.create(name='Group A')
        self.grp_b = Group.objects.create(name='Group B')
        self.pool = Location.objects.create(name='Pool', type='25m_Pool', city='L', street_address='x', lanes=6)

        self.users, self.people = {}, {}
        for key, role in (('admin', 'admin'), ('trainer_a', 'trainer'), ('trainer_b', 'trainer'),
                          ('trainer_free', 'trainer'), ('assist_a', 'swimmer'),
                          ('swim_a', 'swimmer'), ('swim_b', 'swimmer')):
            self.users[key], self.people[key] = make_user(key, role)
        M = GroupMembership.objects.create
        M(group=self.grp_a, swimmer=self.people['trainer_a'], role='trainer')
        M(group=self.grp_b, swimmer=self.people['trainer_b'], role='trainer')
        M(group=self.grp_a, swimmer=self.people['assist_a'], role='trainer')
        M(group=self.grp_b, swimmer=self.people['assist_a'], role='swimmer')
        M(group=self.grp_a, swimmer=self.people['swim_a'], role='swimmer')
        M(group=self.grp_b, swimmer=self.people['swim_b'], role='swimmer')

        self.linkee = User.objects.create_user('linkee', email='linkee@example.org', password='x')

        # people without an account
        self.kid_a = Swimmer.objects.create(first_name='Kid', last_name='Alpha', email='kid@a.org',
                                            phone='111', date_of_birth=date(2015, 6, 1),
                                            emergency_contact_name='Mum A', notes='secret note A')
        self.kid_b = Swimmer.objects.create(first_name='Kid', last_name='Beta', email='kid@b.org',
                                            phone='222', date_of_birth=date(2014, 3, 2))
        self.guest = Swimmer.objects.create(first_name='Guest', last_name='Gamma', email='g@x.org')
        M(group=self.grp_a, swimmer=self.kid_a)
        M(group=self.grp_b, swimmer=self.kid_b)

        self.rs = RecurringSession.objects.create(
            group=self.grp_a, day_of_week=0, start_time=time(18), end_time=time(19),
            valid_from=date(2025, 1, 1), location=self.pool)
        self.past = SessionInstance.objects.create(recurring_session=self.rs, date=PAST,
                                                   trainer_notes='internal trainer note')
        self.future = SessionInstance.objects.create(recurring_session=self.rs, date=FUTURE)
        for inst in (self.past, self.future):
            for sw in (self.kid_a, self.people['swim_a'], self.guest):
                Attendance.objects.create(session=inst, swimmer=sw, status='present')
        self.entry = TrainingPlanEntry.objects.create(session=self.past, description='4x50 free', order=0)
        self.res_a = PerformanceResult.objects.create(
            swimmer=self.kid_a, session=self.past, date=PAST, stroke='free', distance_m=50,
            time_cs=3300, location=self.pool)
        self.res_a_swim = PerformanceResult.objects.create(
            swimmer=self.people['swim_a'], session=self.past, date=PAST, stroke='back', distance_m=50,
            time_cs=4000, location=self.pool)
        self.res_free = PerformanceResult.objects.create(     # competition result, no session
            swimmer=self.kid_a, session=None, date=PAST, stroke='free', distance_m=100,
            time_cs=7000, location=self.pool)

    # helpers ---------------------------------------------------------------
    def login(self, role):
        self.client.logout()
        if role != 'anon':
            self.client.force_login(self.users[role])

    def post_json(self, url, payload):
        return self.client.post(url, json.dumps(payload), content_type='application/json')


@override_settings(MEDIA_ROOT=_MEDIA)
class PermFixture(PermWorld, TestCase):
    pass


@override_settings(MEDIA_ROOT=_MEDIA)
class PermFixtureTx(PermWorld, TransactionTestCase):
    """For WebSocket tests (the consumer talks to the database from another thread)."""
