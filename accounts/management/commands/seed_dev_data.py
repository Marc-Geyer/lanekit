"""Demo data for development: one account per access scenario (see accounts/permissions.py).

    python manage.py seed_dev_data            # create / refresh the demo world (idempotent)
    python manage.py seed_dev_data --reset    # delete the demo world first, then recreate it

Every demo account uses the password ``demo``. All demo objects carry the prefix ``demo_`` (users)
or ``Demo`` (groups, location), so --reset only ever removes what this command created.
Refuses to run with DEBUG=False unless --force is given.
"""
from datetime import date, time, timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from groups.models import Group, GroupMembership
from swimmers.models import PersonChangeRequest, Swimmer
from training.models import (
    Attendance, Location, PerformanceResult, RecurringSession, SessionException, SessionInstance,
    TrainingPlanEntry,
)

PASSWORD = 'demo'

# username, profile role, first, last, scenario
ACCOUNTS = [
    ('demo_admin',        'admin',   'Anna',   'Admin',    'Everything'),
    ('demo_trainer_a',    'trainer', 'Tom',    'Trainer-A', 'Trainer of Demo Group A'),
    ('demo_trainer_b',    'trainer', 'Tina',   'Trainer-B', 'Trainer of Demo Group B'),
    ('demo_trainer_free', 'trainer', 'Theo',   'Ohne-Gruppe', 'Profile trainer without any group'),
    ('demo_assistant',    'swimmer', 'Hilda',  'Hilfstrainer', 'Assistant in Group A, swimmer in Group B'),
    ('demo_swimmer_a',    'swimmer', 'Sven',   'Schwimmer-A', 'Plain swimmer in Group A'),
    ('demo_swimmer_b',    'swimmer', 'Sara',   'Schwimmer-B', 'Plain swimmer in Group B'),
]


class Command(BaseCommand):
    help = 'Create demo users, groups, sessions, plans and results for every access scenario.'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true', help='delete the demo world first')
        parser.add_argument('--force', action='store_true', help='allow running with DEBUG=False')

    def handle(self, *args, **opts):
        if not settings.DEBUG and not opts['force']:
            raise CommandError('Refusing to create demo accounts with DEBUG=False (use --force if you really mean it).')
        if opts['reset']:
            self.reset()
        world = self.build()
        self.report(world)

    # ── reset ────────────────────────────────────────────────────────────
    def reset(self):
        Swimmer.objects.filter(user__username__startswith='demo_').delete()
        Swimmer.objects.filter(email__endswith='@demo.lanekit.test').delete()
        User.objects.filter(username__startswith='demo_').delete()
        Group.objects.filter(name__startswith='Demo ').delete()
        Location.objects.filter(name__startswith='Demo ').delete()
        self.stdout.write('Demo data removed.')

    # ── build ────────────────────────────────────────────────────────────
    def user(self, username, role, first, last):
        user, created = User.objects.get_or_create(username=username, defaults={
            'email': f'{username}@demo.lanekit.test', 'first_name': first, 'last_name': last})
        user.set_password(PASSWORD)
        user.is_active = True
        user.is_staff = user.is_superuser = (role == 'admin')
        user.save()
        profile = user.profile
        profile.role = role
        profile.phone = '0151 000000'       # account and person must agree (sync signal)
        profile.save()
        person, _ = Swimmer.objects.get_or_create(user=user, defaults={
            'first_name': first, 'last_name': last, 'email': user.email, 'phone': profile.phone,
            'date_of_birth': date(1990, 5, 17) if role != 'swimmer' else date(2008, 5, 17)})
        return user, person

    def person(self, first, last, born, **extra):
        person, _ = Swimmer.objects.get_or_create(
            email=f'{first}.{last}@demo.lanekit.test'.lower(),
            defaults=dict(first_name=first, last_name=last, date_of_birth=born, phone='0170 111111', **extra))
        return person

    def member(self, group, swimmer, role='swimmer'):
        m, _ = GroupMembership.objects.get_or_create(group=group, swimmer=swimmer, defaults={'role': role})
        m.role, m.active = role, True
        m.save()

    def build(self):
        today = timezone.localdate()
        pool, _ = Location.objects.get_or_create(
            name='Demo Pool', defaults=dict(type='25m_Pool', city='Leipzig', street_address='Demostraße 1', lanes=6))
        grp_a, _ = Group.objects.get_or_create(name='Demo Group A', defaults={'color': '#0ea5e9', 'description': 'Advanced swimmers'})
        grp_b, _ = Group.objects.get_or_create(name='Demo Group B', defaults={'color': '#f97316', 'description': 'Beginners'})

        people = {}
        users = {}
        for username, role, first, last, _scenario in ACCOUNTS:
            users[username], people[username] = self.user(username, role, first, last)
        # an account without a person record (to try "link account to person" as admin)
        orphan, _ = User.objects.get_or_create(username='demo_unlinked', defaults={
            'email': 'demo_unlinked@demo.lanekit.test', 'first_name': 'Una', 'last_name': 'Unlinked'})
        orphan.set_password(PASSWORD)
        orphan.save()

        self.member(grp_a, people['demo_trainer_a'], 'trainer')
        self.member(grp_b, people['demo_trainer_b'], 'trainer')
        self.member(grp_a, people['demo_assistant'], 'trainer')      # → assistant: swimmer profile + trainer entry
        self.member(grp_b, people['demo_assistant'], 'swimmer')
        self.member(grp_a, people['demo_swimmer_a'])
        self.member(grp_b, people['demo_swimmer_b'])

        kids_a = [self.person('Emil', 'Alpha', date(2013, 3, 4), emergency_contact_name='Mum Alpha',
                              notes='Trainer note: shoulder, no butterfly'),
                  self.person('Lena', 'Alpha', date(2012, 9, 9))]
        kids_b = [self.person('Ben', 'Beta', date(2016, 1, 20)), self.person('Mia', 'Beta', date(2015, 7, 7))]
        guest = self.person('Gast', 'Gamma', date(2011, 11, 11))      # in no group; only a guest in sessions
        for k in kids_a:
            self.member(grp_a, k)
        for k in kids_b:
            self.member(grp_b, k)

        weekday = today.weekday()
        sessions = {}
        for grp, start in ((grp_a, time(17, 0)), (grp_b, time(18, 0))):
            sessions[grp] = RecurringSession.objects.get_or_create(
                group=grp, day_of_week=weekday, start_time=start,
                defaults=dict(end_time=time(start.hour + 1), valid_from=today - timedelta(days=120),
                              location=pool, lanes=2))[0]

        # last week: finished sessions with attendance, plan, times (participant view)
        # next week: not finished yet (participant sees nothing); today: no instance yet ("start session")
        last_week, next_week = today - timedelta(days=7), today + timedelta(days=7)
        for grp, rs in sessions.items():
            members = [m.swimmer for m in grp.memberships.filter(active=True)]
            for day, planned in ((last_week, True), (next_week, False)):
                inst, created = SessionInstance.objects.get_or_create(
                    recurring_session=rs, date=day, defaults={'trainer_notes': 'Internal trainer note – not for swimmers'})
                if not created:
                    continue
                for sw in members + ([guest] if grp is grp_a else []):
                    Attendance.objects.get_or_create(
                        session=inst, swimmer=sw, defaults={'status': 'present' if planned else 'unknown'})
                if planned:
                    for i, (cat, text) in enumerate((('warmup', '200 easy'), ('main', '8x50 free on 1:00'),
                                                     ('cooldown', '100 easy'))):
                        TrainingPlanEntry.objects.create(session=inst, category=cat, description=text, order=i, checked=i == 0)
                    for sw in members:
                        if sw.pk in (people['demo_trainer_a'].pk, people['demo_trainer_b'].pk):
                            continue
                        PerformanceResult.objects.get_or_create(
                            swimmer=sw, session=inst, date=day, stroke='free', distance_m=50,
                            defaults=dict(time_cs=3000 + 37 * sw.pk % 900, location=pool))
        # a competition-style result without session (admin-only to change)
        PerformanceResult.objects.get_or_create(
            swimmer=kids_a[0], session=None, date=today - timedelta(days=30), stroke='free', distance_m=100,
            defaults=dict(time_cs=7250, location=pool))

        # a cancelled session and a pending change proposal
        SessionException.objects.get_or_create(
            date=today + timedelta(days=14), reason='Pool closed for maintenance', defaults={'affects_all': True})
        if not PersonChangeRequest.objects.filter(swimmer=people['demo_swimmer_a'], status='pending').exists():
            PersonChangeRequest.objects.create(
                swimmer=people['demo_swimmer_a'], proposed_by=users['demo_swimmer_a'],
                changes={'phone': '0151 999999', 'emergency_contact_name': 'Oma Schwimmer'})
        return {'today': today, 'weekday': weekday}

    def report(self, world):
        self.stdout.write(self.style.SUCCESS('Demo world ready. Password for every account: %s' % PASSWORD))
        for username, role, first, last, scenario in ACCOUNTS:
            self.stdout.write(f'  {username:<18} {scenario}')
        self.stdout.write('  demo_unlinked      Account without a person (link it as admin)')
        self.stdout.write(
            'Sessions: one per group on today\'s weekday (not started – try "start session"), '
            'finished instances last week, upcoming instances next week.')
