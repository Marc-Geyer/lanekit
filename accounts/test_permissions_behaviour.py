"""What each role actually SEES and may DO – the content side of the permission rules.

The endpoint matrix (test_permissions.py) proves *who gets in*; these tests prove *what they get*
and the rules that do not fit a single request (levels, proposals, locked fields, live updates).
"""
import asyncio
from datetime import date, time

from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import AnonymousUser, User
from django.urls import reverse

from accounts import permissions as perm
from accounts.permissions import Level, PersonAccess
from groups.models import Group, GroupMembership
from swimmers.models import PersonChangeRequest, Swimmer
from training import performance
from training.consumers import SessionConsumer
from training.models import (
    Attendance, RecurringSession, SessionException, SessionInstance, TrainingPlanEntry,
)
from translations import de, en

from .permtest_fixtures import FUTURE, PAST, PermFixture, PermFixtureTx

AGE_UNITS = {de.STRINGS['age_years'], en.STRINGS['age_years']}


# ── Levels and object-level rules (pure functions) ───────────────────────────

class LevelTests(PermFixture):
    def test_global_levels(self):
        expect = {'swim_a': Level.SWIMMER, 'swim_b': Level.SWIMMER, 'assist_a': Level.ASSISTANT,
                  'trainer_a': Level.TRAINER, 'trainer_free': Level.TRAINER, 'admin': Level.ADMIN}
        for role, lvl in expect.items():
            self.assertEqual(perm.level(self.users[role]), lvl, role)
        self.assertEqual(perm.level(AnonymousUser()), Level.ANONYMOUS)

    def test_group_levels_are_per_group(self):
        a, b = self.grp_a.pk, self.grp_b.pk
        U = self.users
        self.assertEqual(perm.group_level(U['trainer_a'], a), Level.TRAINER)
        self.assertEqual(perm.group_level(U['trainer_a'], b), Level.SWIMMER)       # trainer only where entered
        self.assertEqual(perm.group_level(U['assist_a'], a), Level.ASSISTANT)      # swimmer profile + trainer entry
        self.assertEqual(perm.group_level(U['assist_a'], b), Level.SWIMMER)        # swimmer in B
        self.assertEqual(perm.group_level(U['trainer_free'], a), Level.SWIMMER)    # profile alone grants nothing
        self.assertEqual(perm.group_level(U['admin'], b), Level.ADMIN)
        self.assertEqual(perm.group_level(AnonymousUser(), a), Level.ANONYMOUS)

    def test_inactive_trainer_entry_withdraws_rights(self):
        GroupMembership.objects.filter(group=self.grp_a, swimmer=self.people['trainer_a']).update(active=False)
        self.assertEqual(perm.group_level(self.users['trainer_a'], self.grp_a.pk), Level.SWIMMER)
        self.assertFalse(perm.can_operate_session(self.users['trainer_a'], self.grp_a.pk))

    def test_login_never_promotes_group_trainers(self):
        """An assistant stays a swimmer in the profile (the old login hook promoted them to trainer)."""
        self.client.post(reverse('login'), {'username': 'assist_a', 'password': 'x'})
        self.users['assist_a'].profile.refresh_from_db()
        self.assertEqual(self.users['assist_a'].profile.role, 'swimmer')
        self.assertEqual(perm.level(self.users['assist_a']), Level.ASSISTANT)

    def test_person_access(self):
        U, P = self.users, self.people
        F, B, N = PersonAccess.FULL, PersonAccess.BASIC, PersonAccess.NONE
        cases = [
            ('trainer_a', self.kid_a, F), ('trainer_a', self.kid_b, B), ('trainer_a', self.guest, B),
            ('trainer_b', self.kid_a, B), ('trainer_free', self.kid_a, B),
            ('assist_a', self.kid_a, B), ('assist_a', self.kid_b, N), ('assist_a', self.guest, N),
            ('swim_a', P['swim_a'], F), ('swim_a', self.kid_a, N), ('swim_b', self.kid_a, N),
            ('admin', self.kid_a, F), ('admin', self.guest, F),
        ]
        for role, person, expected in cases:
            self.assertEqual(perm.person_access(U[role], person), expected, f'{role} -> {person}')
        self.assertEqual(perm.person_access(AnonymousUser(), self.kid_a), N)

    def test_edit_and_create_person(self):
        U, P = self.users, self.people
        self.assertTrue(perm.can_edit_person(U['trainer_a'], self.kid_a))
        self.assertFalse(perm.can_edit_person(U['trainer_a'], self.kid_b))      # other group
        self.assertFalse(perm.can_edit_person(U['trainer_a'], self.guest))      # no group at all
        self.assertFalse(perm.can_edit_person(U['assist_a'], self.kid_a))       # assistants never
        self.assertFalse(perm.can_edit_person(U['swim_a'], P['swim_a']))        # swimmers never (propose instead)
        self.assertTrue(perm.can_edit_person(U['admin'], self.guest))
        self.assertTrue(perm.can_create_person(U['trainer_a'], self.grp_a.pk))
        self.assertFalse(perm.can_create_person(U['trainer_a'], self.grp_b.pk))
        self.assertFalse(perm.can_create_person(U['trainer_a'], None))          # group is mandatory
        self.assertFalse(perm.can_create_person(U['assist_a'], self.grp_a.pk))
        self.assertTrue(perm.can_create_person(U['admin'], None))

    def test_group_rules(self):
        U, a = self.users, self.grp_a.pk
        self.assertTrue(perm.can_edit_plan(U['trainer_a'], a))
        self.assertFalse(perm.can_edit_plan(U['assist_a'], a))
        self.assertTrue(perm.can_check_plan_entries(U['assist_a'], a))
        self.assertFalse(perm.can_check_plan_entries(U['swim_a'], a))
        self.assertFalse(perm.can_manage_group(U['trainer_b'], a))
        self.assertTrue(perm.can_create_group(U['admin']))
        self.assertFalse(perm.can_create_group(U['trainer_a']))
        self.assertFalse(perm.can_create_global_exception(U['trainer_a']))
        self.assertEqual(perm.exception_group_ids(U['trainer_a']), {a})

    def test_session_view(self):
        past, future = self.past, self.future
        sv = perm.SessionView
        self.assertEqual(perm.session_view(self.users['assist_a'], past), sv.STAFF)
        self.assertEqual(perm.session_view(self.users['assist_a'], future), sv.STAFF)
        self.assertEqual(perm.session_view(self.users['swim_a'], past), sv.PARTICIPANT)
        self.assertEqual(perm.session_view(self.users['swim_a'], future), sv.NONE)      # not finished yet
        self.assertEqual(perm.session_view(self.users['swim_b'], past), sv.NONE)        # not in this group
        self.assertEqual(perm.session_view(self.users['trainer_b'], past), sv.NONE)
        self.assertEqual(perm.session_view(AnonymousUser(), past), sv.NONE)


# ── Anonymous visitors and swimmers: what the calendar / group list reveal ───

class PublicExposureTests(PermFixture):
    def events(self, role):
        self.login(role)
        r = self.client.get(reverse('calendar_events_api'), {'start': '2026-01-01', 'end': '2026-01-31'})
        self.assertEqual(r.status_code, 200)
        return r.json()

    def test_anonymous_sees_group_names_only(self):
        SessionException.objects.create(date=date(2026, 1, 12), reason='secret reason', affects_all=True)
        events = self.events('anon')
        self.assertTrue(events)
        for e in events:
            self.assertEqual(set(e['extendedProps']), {'type', 'group'}, e)
            self.assertEqual(e['extendedProps']['type'], 'public')
            self.assertNotIn('secret reason', e['title'])
            self.assertTrue(e['id'].startswith('pub_'))
        self.assertIn('Group A', {e['extendedProps']['group'] for e in events})

    def test_logged_in_users_get_details(self):
        for role in ('swim_b', 'assist_a'):
            first = self.events(role)[0]['extendedProps']
            self.assertIn('location', first)
            self.assertIn('session_id', first)

    def test_group_list_names_and_session_count_for_everybody_roster_for_trainers(self):
        a, b = (reverse('group_detail', args=[g.pk]) for g in (self.grp_a, self.grp_b))
        for role in ('anon', 'swim_a', 'swim_b'):
            self.login(role)
            r = self.client.get(reverse('group_list'))
            html = r.content.decode()
            self.assertIn('Group A', html)
            self.assertNotIn(a, html, role)
            self.assertNotIn(b, html, role)
            self.assertNotIn('Alpha', html)
            self.assertEqual({g.name: g.current_session_count for g in r.context['groups']},
                             {'Group A': 1, 'Group B': 0}, role)
        # trainers may look into the roster of EVERY group (read-only) ...
        for role in ('trainer_a', 'trainer_b', 'trainer_free', 'admin'):
            self.login(role)
            html = self.client.get(reverse('group_list')).content.decode()
            self.assertIn(a, html, role)
            self.assertIn(b, html, role)
        # ... assistants only of the groups they assist
        self.login('assist_a')
        html = self.client.get(reverse('group_list')).content.decode()
        self.assertIn(a, html)
        self.assertNotIn(b, html)

    def test_session_count_only_counts_current_sessions(self):
        mk = lambda **kw: RecurringSession.objects.create(
            group=self.grp_b, day_of_week=2, start_time=time(17), end_time=time(18),
            valid_from=date(2020, 1, 1), **kw)
        mk(valid_until=date(2021, 1, 1))                       # run out long ago
        mk(active=False)                                       # switched off
        mk(valid_until=date(2999, 1, 1))                       # still running
        self.login('anon')
        counts = {g.name: g.current_session_count for g in self.client.get(reverse('group_list')).context['groups']}
        self.assertEqual(counts['Group B'], 1)
        self.assertEqual(counts['Group A'], 1)

    def test_trainer_sees_foreign_roster_and_sessions_but_nothing_deeper(self):
        self.login('trainer_b')
        r = self.client.get(reverse('group_detail', args=[self.grp_a.pk]))
        html = r.content.decode()
        self.assertEqual(r.status_code, 200)
        self.assertIn('Alpha', html)                                   # who is in the group
        self.assertIn('Pool', html)                                    # its recurring sessions
        self.assertFalse(r.context['is_trainer'])                      # read-only: no edit / add / remove
        self.assertFalse(r.context['can_view_stats'])
        for hidden in ('kid@a.org', '111', 'Mum A', 'secret note A'):
            self.assertNotIn(hidden, html)
        self.assertEqual(self.client.get(reverse('group_stats', args=[self.grp_a.pk])).status_code, 302)
        self.assertEqual(self.client.get(reverse('group_edit', args=[self.grp_a.pk])).status_code, 302)
        modal = self.client.get(reverse('session_modal', args=[self.rs.pk, PAST.isoformat()])).json()
        self.assertFalse(modal['is_trainer'])
        self.assertNotIn('Alpha', modal['html'])
        self.assertNotIn('4x50', modal['html'])

    def test_anonymous_cannot_open_modal(self):
        self.login('anon')
        r = self.client.get(reverse('session_modal', args=[self.rs.pk, PAST.isoformat()]))
        self.assertEqual(r.status_code, 403)
        self.assertNotIn('4x50', r.content.decode())


# ── Session modal per role ───────────────────────────────────────────────────

class ModalContentTests(PermFixture):
    def html(self, role, day=PAST):
        self.login(role)
        r = self.client.get(reverse('session_modal', args=[self.rs.pk, day.isoformat()]))
        self.assertEqual(r.status_code, 200)
        return r.json()['html'], r.json()

    def test_participant_sees_only_ticked_plan_entries_without_strike_through(self):
        TrainingPlanEntry.objects.create(session=self.past, description='Unticked drill', order=1)
        self.entry.checked = True
        self.entry.save()
        html, _ = self.html('swim_a')
        self.assertIn('4x50 free', html)
        self.assertNotIn('Unticked drill', html)            # open items stay with the trainers
        self.assertNotIn('is-checked', html)                # strike-through is a trainer-side aid
        data = self.client.get(reverse('session_state_api', args=[self.past.pk])).json()
        self.assertEqual([e['description'] for e in data['plan_entries']], ['4x50 free'])
        # trainers still get the full list, ticked or not
        self.login('trainer_a')
        data = self.client.get(reverse('session_state_api', args=[self.past.pk])).json()
        self.assertEqual({e['description'] for e in data['plan_entries']}, {'4x50 free', 'Unticked drill'})

    def test_participant_sees_plan_own_status_and_own_times_only(self):
        self.entry.checked = True
        self.entry.save()
        html, meta = self.html('swim_a')
        self.assertIn('4x50 free', html)
        self.assertIn(performance.format_time(self.res_a_swim.time_cs), html)           # own time
        self.assertNotIn(performance.format_time(self.res_a.time_cs), html)             # somebody else's
        for hidden in ('Alpha', 'Gamma', 'internal trainer note', 'addSwimmerPanel', 'trainerNotes', 'attendanceTableBody'):
            self.assertNotIn(hidden, html)
        self.assertFalse(meta['is_trainer'])
        self.assertFalse(meta['can_edit_plan'])

    def test_participant_sees_nothing_before_the_session_is_over(self):
        html, _ = self.html('swim_a', FUTURE)
        self.assertNotIn('4x50', html)
        self.assertNotIn('Alpha', html)

    def test_unrelated_swimmer_and_foreign_trainer_get_the_header_only(self):
        for role in ('swim_b', 'trainer_b', 'trainer_free'):
            html, meta = self.html(role)
            for hidden in ('4x50 free', 'Alpha', 'internal trainer note', 'addSwimmerPanel'):
                self.assertNotIn(hidden, html, role)
            self.assertFalse(meta['is_trainer'])

    def test_assistant_operates_but_cannot_structure_the_plan(self):
        html, meta = self.html('assist_a')
        self.assertTrue(meta['is_trainer'])
        self.assertFalse(meta['can_edit_plan'])
        self.assertIn('plan-check', html)                 # may tick entries off
        self.assertIn('trainerNotes', html)               # notes, attendance, times: yes
        self.assertIn('attendanceTableBody', html)
        for forbidden in ('planQuickAdd', 'drag-handle', 'deletePlanEntry', 'planPhotoInput', 'startPlanEntryEdit'):
            self.assertNotIn(forbidden, html)
        # no person creation, no membership change
        self.assertIn('id="addSwimmerFirst" type="hidden"', html)
        self.assertNotIn('add_swimmer_join_group', html)

    def test_trainer_and_admin_get_everything(self):
        for role in ('trainer_a', 'admin'):
            html, meta = self.html(role)
            self.assertTrue(meta['can_edit_plan'], role)
            for needed in ('planQuickAdd', 'drag-handle', 'deletePlanEntry', 'planPhotoInput', 'Alpha'):
                self.assertIn(needed, html, role)
            self.assertNotIn('id="addSwimmerFirst" type="hidden"', html)

    def test_state_api_never_leaks_to_outsiders(self):
        self.login('swim_a')
        data = self.client.get(reverse('session_state_api', args=[self.past.pk])).json()
        self.assertEqual(data['trainer_notes'], '')
        self.assertEqual([a['swimmer_id'] for a in data['attendances']], [self.people['swim_a'].pk])
        self.assertFalse(data['is_trainer'])
        self.login('swim_b')
        self.assertEqual(self.client.get(reverse('session_state_api', args=[self.past.pk])).status_code, 403)

    def test_assistant_picker_has_no_group_names_but_trainer_has(self):
        self.login('assist_a')
        self.assertNotIn('Group B', self.client.get(
            reverse('session_modal', args=[self.rs.pk, PAST.isoformat()])).json()['html'])
        self.login('trainer_a')
        self.assertIn('Group B', self.client.get(
            reverse('session_modal', args=[self.rs.pk, PAST.isoformat()])).json()['html'])


# ── Person pages and list ────────────────────────────────────────────────────

class PersonVisibilityTests(PermFixture):
    SECRETS = ('kid@a.org', '111', 'Mum A', 'secret note A', '01.06.2015')

    def page(self, role, person):
        self.login(role)
        r = self.client.get(reverse('swimmer_detail', args=[person.pk]))
        return r, r.content.decode() if r.status_code == 200 else ''

    def test_group_trainer_sees_everything_incl_notes_and_stats(self):
        r, html = self.page('trainer_a', self.kid_a)
        for s in self.SECRETS:
            self.assertIn(s, html)
        self.assertIn('stats', r.context)
        self.assertTrue(r.context['can_edit'])

    def test_other_trainers_and_assistants_get_basic_info_and_times_only(self):
        for role in ('trainer_b', 'trainer_free', 'assist_a'):
            r, html = self.page(role, self.kid_a)
            self.assertEqual(r.status_code, 200, role)
            for s in self.SECRETS:
                self.assertNotIn(s, html, f'{role} must not see {s!r}')
            self.assertNotIn('Group A', html, role)                    # no group memberships either
            self.assertNotIn('stats', r.context, role)                 # no attendance statistics
            self.assertIn('perf_data', r.context, role)                # but swim-time statistics
            self.assertFalse(r.context['can_edit'], role)
            self.assertTrue(any(f'{self.kid_a.age} {u}' in html for u in AGE_UNITS), role)   # age, not birthday

    def test_swimmer_sees_own_record_without_trainer_notes(self):
        own = self.people['swim_a']
        own.notes = 'trainer only remark'
        own.save()
        r, html = self.page('swim_a', own)
        self.assertEqual(r.status_code, 200)
        self.assertIn(own.email, html)
        self.assertNotIn('trainer only remark', html)
        self.assertIn('stats', r.context)                               # own attendance statistics
        self.assertIn('perf_data', r.context)
        self.assertFalse(r.context['can_edit'])
        self.assertTrue(r.context['can_propose'])
        r, html = self.page('trainer_a', own)
        self.assertIn('trainer only remark', html)

    def test_swimmers_cannot_open_other_people(self):
        for role in ('swim_a', 'swim_b'):
            r, _ = self.page(role, self.kid_a)
            self.assertEqual(r.status_code, 302, role)

    def test_attendance_statistics_only_cover_the_viewers_own_groups(self):
        # kid_a (member of A) also swims in B; a trainer of A must not see B's sessions in the statistics
        GroupMembership.objects.create(group=self.grp_b, swimmer=self.kid_a)
        self.assertEqual(perm.attendance_stats_group_ids(self.users['trainer_a'], self.kid_a), {self.grp_a.pk})
        self.assertEqual(perm.attendance_stats_group_ids(self.users['admin'], self.kid_a),
                         {self.grp_a.pk, self.grp_b.pk})
        # ... and only the groups they are staff of show up on the page
        r, html = self.page('trainer_a', self.kid_a)
        self.assertEqual(r.context['stats']['present'], 0)             # nothing counted from B's sessions

    def test_direct_edit_only_for_trainers_of_the_persons_group(self):
        url = reverse('swimmer_detail', args=[self.kid_a.pk])
        body = {'first_name': 'Edited', 'last_name': 'Alpha', 'active': 'on'}
        for role in ('trainer_b', 'trainer_free', 'assist_a', 'swim_a', 'swim_b', 'anon'):
            self.login(role)
            self.client.post(url, body)
            self.kid_a.refresh_from_db()
            self.assertEqual(self.kid_a.first_name, 'Kid', role)
        self.login('trainer_a')
        self.client.post(url, body)
        self.kid_a.refresh_from_db()
        self.assertEqual(self.kid_a.first_name, 'Edited')

    def test_swimmer_cannot_edit_own_record_directly(self):
        own = self.people['swim_a']
        self.login('swim_a')
        self.client.post(reverse('swimmer_detail', args=[own.pk]),
                         {'first_name': 'Hacked', 'last_name': 'User', 'active': 'on'})
        own.refresh_from_db()
        self.assertEqual(own.first_name, 'Swim_A')

    def test_person_list_scopes(self):
        def names(role, **params):
            self.login(role)
            r = self.client.get(reverse('swimmer_list'), params)
            self.assertEqual(r.status_code, 200, role)
            return {s.last_name + s.first_name: s for s in r.context['swimmers']}
        # trainers: everybody (name + age) ...
        seen = names('trainer_b')
        self.assertIn('AlphaKid', seen)
        self.assertIn('GammaGuest', seen)
        # ... but contact data and group badges only for people of their own groups
        self.assertFalse(seen['AlphaKid'].show_contact)
        # group pills for every group, but still no deeper insight
        self.assertEqual([m.group.name for m in seen['AlphaKid'].vis_memberships], ['Group A'])
        self.assertTrue(names('trainer_a')['AlphaKid'].show_contact)
        # assistants: only the members of the groups they assist
        seen = names('assist_a')
        self.assertIn('AlphaKid', seen)
        self.assertNotIn('BetaKid', seen)
        self.assertNotIn('GammaGuest', seen)
        # swimmers: no list at all
        for role in ('swim_a', 'swim_b'):
            self.login(role)
            self.assertEqual(self.client.get(reverse('swimmer_list')).status_code, 302)

    def test_search_cannot_be_used_to_dig_for_contact_data(self):
        def found(role, q):
            self.login(role)
            return {s.pk for s in self.client.get(reverse('swimmer_list'), {'q': q}).context['swimmers']}
        self.assertIn(self.kid_a.pk, found('trainer_a', 'kid@a.org'))          # own group member: fine
        self.assertNotIn(self.kid_a.pk, found('trainer_b', 'kid@a.org'))       # e-mail of a stranger
        self.assertNotIn(self.kid_a.pk, found('trainer_b', '111'))             # phone of a stranger
        self.assertIn(self.kid_a.pk, found('trainer_b', 'Group A'))            # group pills are visible to trainers
        self.assertIn(self.kid_a.pk, found('trainer_b', 'alpha'))              # the name is public to trainers
        self.assertIn(self.kid_a.pk, found('admin', 'kid@a.org'))

    def test_trainers_may_filter_by_any_group_assistants_only_by_their_own(self):
        self.login('trainer_b')
        r = self.client.get(reverse('swimmer_list'), {'group': self.grp_a.pk})
        self.assertEqual(str(r.context['selected_group']), str(self.grp_a.pk))
        self.assertIn(self.kid_a.pk, {s.pk for s in r.context['swimmers']})
        self.assertNotIn(self.kid_b.pk, {s.pk for s in r.context['swimmers']})
        self.assertEqual({g.pk for g in r.context['groups']}, {self.grp_a.pk, self.grp_b.pk})
        self.login('assist_a')
        r = self.client.get(reverse('swimmer_list'), {'group': self.grp_b.pk})        # B: only a swimmer there
        self.assertEqual(r.context['selected_group'], '')
        self.assertEqual({g.pk for g in r.context['groups']}, {self.grp_a.pk})

    def test_account_filter_is_admin_only(self):
        self.login('trainer_a')
        r = self.client.get(reverse('swimmer_list'), {'account': 'without'})
        self.assertEqual(r.context['account'], '')


# ── Memberships, creating people, trainer rights ─────────────────────────────

class MembershipRuleTests(PermFixture):
    def add(self, role, person, group, member_role='swimmer'):
        self.login(role)
        self.client.post(reverse('swimmer_membership_add', args=[person.pk]), {'group': group.pk, 'role': member_role})
        return GroupMembership.objects.filter(group=group, swimmer=person, active=True)

    def test_trainers_manage_only_their_own_groups(self):
        self.assertFalse(self.add('trainer_a', self.guest, self.grp_b).exists())       # foreign group
        self.assertFalse(self.add('assist_a', self.guest, self.grp_a).exists())        # assistant
        self.assertFalse(self.add('trainer_free', self.guest, self.grp_a).exists())
        self.assertTrue(self.add('trainer_a', self.guest, self.grp_a).exists())
        self.assertTrue(self.add('trainer_b', self.kid_a, self.grp_b).exists())        # may take over any visible person

    def test_trainer_hands_out_trainer_rights_only_in_own_group(self):
        self.assertTrue(self.add('trainer_a', self.guest, self.grp_a, 'trainer').filter(role='trainer').exists())
        self.assertFalse(self.add('trainer_a', self.guest, self.grp_b, 'trainer').exists())     # foreign group
        self.assertFalse(self.add('assist_a', self.kid_b, self.grp_a, 'trainer').exists())      # assistants cannot

    def test_new_trainer_entry_makes_a_swimmer_an_assistant(self):
        helper_u, helper = (self.users['swim_b'], self.people['swim_b'])
        self.assertEqual(perm.level(helper_u), Level.SWIMMER)
        self.add('trainer_a', helper, self.grp_a, 'trainer')
        self.assertEqual(perm.level(helper_u), Level.ASSISTANT)                         # still a swimmer in the profile
        self.assertEqual(perm.group_level(helper_u, self.grp_a.pk), Level.ASSISTANT)
        self.assertEqual(perm.group_level(helper_u, self.grp_b.pk), Level.SWIMMER)

    def test_trainer_creates_people_only_into_own_group(self):
        self.login('trainer_a')
        url = reverse('swimmer_create')
        self.client.post(url, {'first_name': 'Into', 'last_name': 'B', 'group': self.grp_b.pk, 'group_role': 'swimmer'})
        self.assertFalse(Swimmer.objects.filter(first_name='Into').exists())
        self.client.post(url, {'first_name': 'Without', 'last_name': 'Group'})              # group is mandatory
        self.assertFalse(Swimmer.objects.filter(first_name='Without').exists())
        self.client.post(url, {'first_name': 'Into', 'last_name': 'A', 'group': self.grp_a.pk, 'group_role': 'swimmer'})
        self.assertTrue(GroupMembership.objects.filter(group=self.grp_a, swimmer__first_name='Into').exists())

    def test_admin_may_create_without_group(self):
        self.login('admin')
        self.client.post(reverse('swimmer_create'), {'first_name': 'Loose', 'last_name': 'End'})
        self.assertTrue(Swimmer.objects.filter(first_name='Loose').exists())

    def test_trainer_form_offers_only_own_groups(self):
        self.login('trainer_a')
        form = self.client.get(reverse('swimmer_create')).context['form']
        self.assertEqual({g.pk for g in form.fields['group'].queryset}, {self.grp_a.pk})

    def test_session_shortcut_never_creates_people_for_assistants(self):
        self.login('assist_a')
        r = self.post_json(reverse('session_add_swimmer_api', args=[self.future.pk]),
                           {'first_name': 'Walk', 'last_name': 'In', 'join_group': False})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Swimmer.objects.filter(first_name='Walk').exists())

    def test_person_created_in_session_always_joins_the_group(self):
        self.login('trainer_a')
        r = self.post_json(reverse('session_add_swimmer_api', args=[self.future.pk]),
                           {'first_name': 'Walk', 'last_name': 'In', 'join_group': False})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(GroupMembership.objects.filter(group=self.grp_a, swimmer__first_name='Walk', active=True).exists())

    def test_attendance_only_for_people_on_the_session(self):
        self.login('trainer_a')
        url = reverse('session_attendance_update_api', args=[self.past.pk])
        r = self.post_json(url, {'swimmer_id': self.kid_b.pk, 'status': 'present'})    # member of B, not on this session
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Attendance.objects.filter(session=self.past, swimmer=self.kid_b).exists())
        r = self.post_json(url, {'swimmer_id': self.guest.pk, 'status': 'absent'})     # guest already on the list
        self.assertEqual(r.status_code, 200)

    def test_excuse_link_only_for_people_of_the_session(self):
        self.login('trainer_a')
        r = self.post_json(reverse('generate_excuse_token'),
                           {'swimmer_id': self.kid_b.pk, 'session_id': self.rs.pk, 'date': PAST.isoformat()})
        self.assertEqual(r.status_code, 403)


# ── Swim times ───────────────────────────────────────────────────────────────

class ResultRuleTests(PermFixture):
    def record(self, role, swimmer):
        self.login(role)
        return self.post_json(reverse('session_results_api', args=[self.past.pk]),
                              {'stroke': 'free', 'distance': 25, 'entries': [{'swimmer_id': swimmer.pk, 'time': '15,00'}]})

    def test_times_for_guests_of_the_session_are_fine(self):
        for role in ('assist_a', 'trainer_a', 'admin'):
            self.assertEqual(self.record(role, self.guest).status_code, 200, role)

    def test_times_only_for_people_with_a_session_link(self):
        """Even a trainer cannot time somebody who is not on that session's attendance list."""
        for role in ('assist_a', 'trainer_a', 'admin'):
            r = self.record(role, self.kid_b)
            self.assertEqual(r.status_code, 400, role)
            self.assertEqual(r.json()['errors'], {str(self.kid_b.pk): 'unknown_swimmer'})
        self.assertEqual(self.past.results.filter(swimmer=self.kid_b).count(), 0)

    def test_foreign_trainers_cannot_touch_the_session_results(self):
        for role in ('trainer_b', 'trainer_free', 'swim_a', 'swim_b'):
            self.assertIn(self.record(role, self.guest).status_code, (403,), role)

    def test_results_without_session_are_admin_only(self):
        for role in ('trainer_a', 'assist_a', 'trainer_b'):
            self.login(role)
            r = self.post_json(reverse('result_update_api', args=[self.res_free.pk]), {'time': '1,00'})
            self.assertEqual(r.status_code, 403, role)
        self.login('admin')
        self.assertEqual(self.post_json(reverse('result_update_api', args=[self.res_free.pk]), {'time': '1,00'}).status_code, 200)


# ── Exceptions ───────────────────────────────────────────────────────────────

class ExceptionRuleTests(PermFixture):
    def setUp(self):
        super().setUp()
        self.rs_b = RecurringSession.objects.create(
            group=self.grp_b, day_of_week=1, start_time=time(18), end_time=time(19), valid_from=date(2025, 1, 1))

    def post(self, role, **extra):
        self.login(role)
        return self.client.post(reverse('exception_create'), {'date': '12.01.2026', 'reason': extra.pop('reason', 'x'), **extra})

    def test_trainer_cannot_cancel_foreign_sessions(self):
        self.post('trainer_a', reason='foreign', affected_sessions=[self.rs_b.pk])
        self.assertFalse(SessionException.objects.filter(reason='foreign').exists())

    def test_trainer_form_has_no_affects_all_and_needs_a_session(self):
        self.login('trainer_a')
        form = self.client.get(reverse('exception_create')).context['form']
        self.assertNotIn('affects_all', form.fields)
        self.assertEqual({s.pk for s in form.fields['affected_sessions'].queryset}, {self.rs.pk})
        self.post('trainer_a', reason='nothing selected')
        self.assertFalse(SessionException.objects.filter(reason='nothing selected').exists())

    def test_trainer_cannot_smuggle_affects_all(self):
        self.post('trainer_a', reason='sneaky', affects_all='on', affected_sessions=[self.rs.pk])
        exc = SessionException.objects.get(reason='sneaky')
        self.assertFalse(exc.affects_all)
        self.assertEqual(list(exc.affected_sessions.all()), [self.rs])

    def test_admin_may_cancel_everything(self):
        self.post('admin', reason='all', affects_all='on')
        self.assertTrue(SessionException.objects.get(reason='all').affects_all)


# ── Change proposals ─────────────────────────────────────────────────────────

class ProposalTests(PermFixture):
    def propose(self, role='swim_a', **fields):
        person = self.people[role]
        body = {'first_name': person.first_name, 'last_name': person.last_name, 'phone': person.phone,
                'date_of_birth': '01.01.2000', 'emergency_contact_name': '', 'emergency_contact_phone': ''}
        body.update(fields)
        self.login(role)
        return self.client.post(reverse('swimmer_propose', args=[person.pk]), body)

    def pending(self):
        return PersonChangeRequest.objects.filter(swimmer=self.people['swim_a'], status='pending')

    def test_proposal_changes_nothing_until_accepted(self):
        self.propose(first_name='Newname', phone='999')
        req = self.pending().get()
        self.assertEqual(req.changes, {'first_name': 'Newname', 'phone': '999'})       # only what differs
        person = Swimmer.objects.get(pk=self.people['swim_a'].pk)
        self.assertEqual((person.first_name, person.phone), ('Swim_A', '0123'))

    def test_only_whitelisted_fields_can_be_proposed(self):
        self.propose(first_name='Newname', email='evil@x.org', notes='gotcha', active='')
        self.assertEqual(set(self.pending().get().changes), {'first_name'})

    def test_new_proposal_replaces_the_open_one(self):
        self.propose(first_name='One')
        self.propose(first_name='Two')
        self.assertEqual(self.pending().count(), 1)
        self.assertEqual(self.pending().get().changes['first_name'], 'Two')

    def test_nothing_to_propose_and_invalid_input(self):
        self.propose()
        self.propose(first_name='')
        self.propose(date_of_birth='31.02.2000')
        self.assertEqual(self.pending().count(), 0)

    def test_only_the_person_themself_may_propose(self):
        for role in ('swim_b', 'trainer_a', 'assist_a', 'admin'):
            self.login(role)
            self.client.post(reverse('swimmer_propose', args=[self.people['swim_a'].pk]),
                             {'first_name': 'Hijack', 'last_name': 'User'})
        self.assertEqual(self.pending().count(), 0)

    def test_trainer_of_the_persons_group_accepts_and_the_account_follows(self):
        self.propose(first_name='Newname', phone='999')
        req = self.pending().get()
        self.login('trainer_a')
        self.client.post(reverse('swimmer_proposal_approve', args=[req.swimmer_id, req.pk]))
        person = Swimmer.objects.get(pk=req.swimmer_id)
        self.assertEqual((person.first_name, person.phone), ('Newname', '999'))
        user = User.objects.get(pk=self.users['swim_a'].pk)
        self.assertEqual(user.first_name, 'Newname')                                   # account stays in sync
        self.assertEqual(user.profile.phone, '999')
        req.refresh_from_db()
        self.assertEqual((req.status, req.reviewed_by), ('approved', self.users['trainer_a']))
        # an already decided proposal cannot be applied twice
        person.first_name = 'Later'
        person.save()
        self.client.post(reverse('swimmer_proposal_approve', args=[req.swimmer_id, req.pk]))
        person.refresh_from_db()
        self.assertEqual(person.first_name, 'Later')

    def test_rejected_proposal_changes_nothing(self):
        self.propose(first_name='Newname')
        req = self.pending().get()
        self.login('admin')
        self.client.post(reverse('swimmer_proposal_reject', args=[req.swimmer_id, req.pk]))
        self.assertEqual(Swimmer.objects.get(pk=req.swimmer_id).first_name, 'Swim_A')
        self.assertEqual(PersonChangeRequest.objects.get(pk=req.pk).status, 'rejected')

    def test_nobody_else_can_decide(self):
        self.propose(first_name='Newname')
        req = self.pending().get()
        for role in ('assist_a', 'trainer_b', 'trainer_free', 'swim_a', 'swim_b', 'anon'):
            self.login(role)
            self.client.post(reverse('swimmer_proposal_approve', args=[req.swimmer_id, req.pk]))
            self.client.post(reverse('swimmer_proposal_reject', args=[req.swimmer_id, req.pk]))
        req.refresh_from_db()
        self.assertEqual(req.status, 'pending')
        self.assertEqual(Swimmer.objects.get(pk=req.swimmer_id).first_name, 'Swim_A')

    def test_reviewers_see_the_open_proposal_swimmer_sees_the_notice(self):
        self.propose(first_name='Newname')
        self.login('trainer_a')
        r = self.client.get(reverse('swimmer_detail', args=[self.people['swim_a'].pk]))
        self.assertEqual(len(r.context['pending_requests']), 1)
        self.assertTrue(r.context['can_review'])
        self.login('swim_a')
        r = self.client.get(reverse('swimmer_detail', args=[self.people['swim_a'].pk]))
        self.assertFalse(r.context['can_review'])


class ProposalOverviewTests(PermFixture):
    """The notification bell and the overview page of open change proposals."""

    def setUp(self):
        super().setUp()
        self.req_a = PersonChangeRequest.objects.create(          # swim_a is a member of group A
            swimmer=self.people['swim_a'], proposed_by=self.users['swim_a'],
            changes={'first_name': 'Newname', 'date_of_birth': '2001-02-03'})
        self.req_b = PersonChangeRequest.objects.create(          # swim_b is a member of group B
            swimmer=self.people['swim_b'], proposed_by=self.users['swim_b'], changes={'phone': '555'})

    def overview(self, role):
        self.login(role)
        return self.client.get(reverse('proposal_list'))

    def test_everybody_sees_exactly_the_proposals_they_may_decide_on(self):
        ids = lambda role: {r.pk for r in self.overview(role).context['pending_requests']}
        self.assertEqual(ids('trainer_a'), {self.req_a.pk})
        self.assertEqual(ids('trainer_b'), {self.req_b.pk})
        self.assertEqual(ids('admin'), {self.req_a.pk, self.req_b.pk})

    def test_nobody_else_gets_the_page(self):
        for role in ('assist_a', 'trainer_free', 'swim_a', 'swim_b', 'anon'):
            self.assertEqual(self.overview(role).status_code, 302, role)

    def test_bell_with_count_only_for_those_who_can_decide(self):
        expect = {'trainer_a': 1, 'trainer_b': 1, 'admin': 2}
        for role, count in expect.items():
            self.login(role)
            r = self.client.get(reverse('calendar'))
            self.assertTrue(r.context['can_review_proposals'], role)
            self.assertEqual(r.context['pending_proposal_count'], count, role)
            self.assertIn(f'>{count}</span>', r.content.decode())
            self.assertIn('bi-bell-fill', r.content.decode())
        for role in ('assist_a', 'trainer_free', 'swim_a', 'anon'):
            self.login(role)
            r = self.client.get(reverse('calendar'))
            self.assertFalse(r.context['can_review_proposals'], role)
            self.assertEqual(r.context['pending_proposal_count'], 0, role)
            self.assertNotIn(reverse('proposal_list'), r.content.decode(), role)

    def test_bell_without_open_proposals_has_no_badge(self):
        PersonChangeRequest.objects.all().delete()
        self.login('trainer_a')
        html = self.client.get(reverse('calendar')).content.decode()
        self.assertIn(reverse('proposal_list'), html)           # still reachable
        self.assertNotIn('bi-bell-fill', html)

    def test_rows_show_current_and_proposed_values(self):
        html = self.overview('trainer_a').content.decode()
        for needed in ('Swim_A User', 'Swim_A', 'Newname', '01.01.2000', '03.02.2001'):
            self.assertIn(needed, html)
        self.assertNotIn('555', html)                           # somebody else's proposal

    def test_deciding_from_the_overview_returns_to_it(self):
        self.login('trainer_a')
        r = self.client.post(reverse('swimmer_proposal_approve', args=[self.req_a.swimmer_id, self.req_a.pk]),
                             {'next': 'proposals'})
        self.assertRedirects(r, reverse('proposal_list'))
        self.assertEqual(Swimmer.objects.get(pk=self.req_a.swimmer_id).first_name, 'Newname')
        self.assertEqual(self.client.get(reverse('proposal_list')).context['pending_requests'], [])
        # the foreign proposal is still out of reach for this trainer
        r = self.client.post(reverse('swimmer_proposal_approve', args=[self.req_b.swimmer_id, self.req_b.pk]),
                             {'next': 'proposals'})
        self.assertEqual(PersonChangeRequest.objects.get(pk=self.req_b.pk).status, 'pending')

    def test_decided_proposals_leave_the_list_and_the_count(self):
        self.login('admin')
        self.client.post(reverse('swimmer_proposal_reject', args=[self.req_b.swimmer_id, self.req_b.pk]),
                         {'next': 'proposals'})
        r = self.client.get(reverse('calendar'))
        self.assertEqual(r.context['pending_proposal_count'], 1)

    def test_withdrawn_group_membership_withdraws_the_proposal(self):
        GroupMembership.objects.filter(group=self.grp_a, swimmer=self.people['swim_a']).update(active=False)
        self.assertEqual(self.overview('trainer_a').context['pending_requests'], [])

    def test_the_overview_uses_the_same_rule_as_the_person_page(self):
        for role in ('trainer_a', 'trainer_b', 'admin', 'assist_a', 'trainer_free'):
            visible = {r.pk for r in perm.reviewable_change_requests(self.users[role])}
            for req in (self.req_a, self.req_b):
                self.assertEqual(req.pk in visible, perm.can_review_person_change(self.users[role], req.swimmer), role)


class AccountFormLockTests(PermFixture):
    """Name and phone on the account form sync into the person record – swimmers go through proposals."""

    def save_profile(self, who, **extra):
        user = self.users[who]
        self.login(who)
        body = {'first_name': user.first_name, 'last_name': user.last_name, 'email': user.email,
                'phone': user.profile.phone, 'bio': 'hello', 'role': user.profile.role}
        body.update(extra)
        self.client.post(reverse('profile'), body)

    def test_swimmer_cannot_rename_via_the_account_form(self):
        self.save_profile('swim_a', first_name='Hacked', phone='666')
        user = User.objects.get(pk=self.users['swim_a'].pk)
        person = Swimmer.objects.get(pk=self.people['swim_a'].pk)
        self.assertEqual((user.first_name, person.first_name, person.phone), ('Swim_A', 'Swim_A', '0123'))
        self.assertEqual(user.profile.bio, 'hello')                                    # account things stay editable

    def test_assistant_is_locked_too(self):
        self.save_profile('assist_a', first_name='Hacked')
        self.assertEqual(Swimmer.objects.get(pk=self.people['assist_a'].pk).first_name, 'Assist_A')

    def test_admin_and_group_trainers_may_edit_their_own_data(self):
        self.save_profile('admin', first_name='Boss')
        self.assertEqual(Swimmer.objects.get(pk=self.people['admin'].pk).first_name, 'Boss')
        self.save_profile('trainer_a', first_name='Coach')
        self.assertEqual(Swimmer.objects.get(pk=self.people['trainer_a'].pk).first_name, 'Coach')

    def test_roles_cannot_be_self_assigned(self):
        self.save_profile('swim_a', role='admin')   # posted role is ignored for non-admins
        self.assertEqual(User.objects.get(pk=self.users['swim_a'].pk).profile.role, 'swimmer')


# ── WebSocket ────────────────────────────────────────────────────────────────

class LiveSessionPermissionTests(PermFixtureTx):
    """The consumer is a second front door: same rules, re-checked for every message."""

    def open(self, user):
        comm = WebsocketCommunicator(SessionConsumer.as_asgi(), f'/ws/session/{self.past.pk}/')
        comm.scope['user'] = user
        comm.scope['url_route'] = {'kwargs': {'session_id': str(self.past.pk)}}
        return comm

    def run_async(self, coro):
        asyncio.run(coro)

    def test_only_staff_of_the_group_may_connect(self):
        async def scenario():
            for role in ('swim_a', 'swim_b', 'trainer_b', 'trainer_free'):
                comm = self.open(self.users[role])
                connected, _ = await comm.connect()
                self.assertFalse(connected, f'{role} must not receive live data')
            comm = self.open(AnonymousUser())
            connected, _ = await comm.connect()
            self.assertFalse(connected)
            for role in ('assist_a', 'trainer_a', 'admin'):
                comm = self.open(self.users[role])
                connected, _ = await comm.connect()
                self.assertTrue(connected, role)
                init = await comm.receive_json_from()
                self.assertEqual(init['type'], 'init')
                self.assertEqual(init['can_edit_plan'], role != 'assist_a')
                await comm.disconnect()
        self.run_async(scenario())

    def test_assistant_may_tick_but_not_structure(self):
        async def scenario():
            comm = self.open(self.users['assist_a'])
            await comm.connect()
            await comm.receive_json_from()
            n_before = await sync_to_async(TrainingPlanEntry.objects.count)()
            # structure: add / delete / reorder / photo broadcast
            for action, data in (('add_plan_entry', {'description': 'sneaky'}),
                                 ('delete_plan_entry', {'id': self.entry.pk}),
                                 ('reorder_plan', {'order': [{'id': self.entry.pk, 'order': 9}]}),
                                 ('photo_updated', {'id': self.entry.pk})):
                await comm.send_json_to({'action': action, 'data': data})
                msg = await comm.receive_json_from()
                self.assertEqual(msg['type'], 'error', action)
            self.assertEqual(await sync_to_async(TrainingPlanEntry.objects.count)(), n_before)
            # editing: only `checked` gets through
            await comm.send_json_to({'action': 'update_plan_entry',
                                     'data': {'id': self.entry.pk, 'checked': True, 'description': 'hacked'}})
            msg = await comm.receive_json_from()
            self.assertEqual(msg['type'], 'plan_update')
            entry = await sync_to_async(TrainingPlanEntry.objects.get)(pk=self.entry.pk)
            self.assertTrue(entry.checked)
            self.assertEqual(entry.description, '4x50 free')
            # everything else in the modal works
            await comm.send_json_to({'action': 'update_notes', 'data': {'notes': 'from assistant'}})
            self.assertEqual((await comm.receive_json_from())['type'], 'notes_update')
            await comm.send_json_to({'action': 'update_attendance',
                                     'data': {'swimmer_id': self.kid_a.pk, 'status': 'absent'}})
            self.assertEqual((await comm.receive_json_from())['type'], 'attendance_update')
            await comm.disconnect()
        self.run_async(scenario())

    def test_trainer_may_structure_the_plan(self):
        async def scenario():
            comm = self.open(self.users['trainer_a'])
            await comm.connect()
            await comm.receive_json_from()
            await comm.send_json_to({'action': 'add_plan_entry', 'data': {'description': 'new set'}})
            self.assertEqual((await comm.receive_json_from())['type'], 'plan_add')
            await comm.send_json_to({'action': 'update_plan_entry',
                                     'data': {'id': self.entry.pk, 'description': 'changed'}})
            self.assertEqual((await comm.receive_json_from())['type'], 'plan_update')
            await comm.disconnect()
        self.run_async(scenario())
        self.assertTrue(TrainingPlanEntry.objects.filter(description='new set').exists())

    def test_photo_broadcast_cannot_inject_client_data(self):
        """The server re-reads the entry; whatever the client claims is never relayed."""
        async def scenario():
            comm = self.open(self.users['trainer_a'])
            await comm.connect()
            await comm.receive_json_from()
            await comm.send_json_to({'action': 'photo_updated',
                                     'data': {'id': self.entry.pk, 'description': 'FORGED', 'photo_url': 'http://evil'}})
            msg = await comm.receive_json_from()
            self.assertEqual(msg['data']['description'], '4x50 free')
            self.assertNotEqual(msg['data']['photo_url'], 'http://evil')
            await comm.disconnect()
        self.run_async(scenario())

    def test_rights_withdrawn_during_a_connection_apply_immediately(self):
        async def scenario():
            comm = self.open(self.users['trainer_a'])
            await comm.connect()
            await comm.receive_json_from()
            await sync_to_async(GroupMembership.objects.filter(
                group=self.grp_a, swimmer=self.people['trainer_a']).update)(active=False)
            await comm.send_json_to({'action': 'update_notes', 'data': {'notes': 'too late'}})
            self.assertEqual((await comm.receive_json_from())['type'], 'error')
            await comm.disconnect()
        self.run_async(scenario())
        self.assertNotEqual(SessionInstance.objects.get(pk=self.past.pk).trainer_notes, 'too late')
