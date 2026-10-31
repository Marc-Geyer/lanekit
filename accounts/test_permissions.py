"""Access-control tests: positive AND negative, for every endpoint and every role.

How to extend
-------------
* New endpoint?  Add it to ``ENDPOINTS`` (who may use it, and – for writes – an ``effect`` that proves
  the action really happened) or, if it is deliberately public, to ``PUBLIC_ENDPOINTS``.
  ``test_every_endpoint_is_classified`` fails until you do.
* New rule?  Put it in ``accounts/permissions.py`` first, then add a unit test below and a matrix row.

The matrix calls each endpoint once per role inside a rolled-back savepoint, so calls cannot
influence each other. "Denied" means HTTP 403, a redirect to the login page, or a redirect carrying
the "no permission" message; for writes the ``effect`` must additionally be present exactly for the
allowed roles (a harmless-looking 200 that silently did the work would be caught).
"""
import json
from datetime import date

from django.contrib.messages import get_messages
from django.db import transaction
from django.urls import get_resolver, reverse

from accounts import permissions as perm
from groups.models import Group, GroupMembership
from swimmers.models import PersonChangeRequest, Swimmer
from training.models import (
    Attendance, ExcuseToken, PerformanceResult, RecurringSession, SessionException, SessionInstance,
    TrainingPlanEntry,
)
from translations import de, en, uk, ar

from .permtest_fixtures import (
    FUTURE, LOGGED_IN, PAST, ROLES, PermFixture, png,
)

NO_PERMISSION = {m.STRINGS['msg_no_permission'] for m in (de, en, uk, ar)}

ALL = set(ROLES)
AUTH = set(LOGGED_IN)
ADMIN = {'admin'}
A_MANAGE = {'trainer_a', 'admin'}                       # trainer of group A + admin
A_OPERATE = {'assist_a', 'trainer_a', 'admin'}          # + assistant of group A
PEOPLE_LIST = {'assist_a', 'trainer_a', 'trainer_b', 'trainer_free', 'admin'}

# Endpoints that are public or token-based by design (no role matrix needed).
PUBLIC_ENDPOINTS = {
    'calendar', 'set_language', 'robots_txt', 'honeypot_trap', 'pwa_manifest', 'pwa_sw', 'pwa_offline',
    'login', 'logout', 'register', 'activate', 'verify_email',
    'use_excuse_token',        # one-time link, no login by design
}


class E:
    """One matrix row."""

    def __init__(self, name, allowed, url, method='get', data=None, json_body=None, files=None, effect=None,
                 label=None):
        self.name, self.allowed, self.url = name, set(allowed), url
        self.method, self.data, self.json_body, self.files, self.effect = method, data, json_body, files, effect
        self.label = label or name


def rows(fx):
    """Built per test (needs fixture ids)."""
    P, U = fx.people, fx.users
    A, B, rs = fx.grp_a, fx.grp_b, fx.rs
    past, future = fx.past, fx.future
    r = []

    # ── accounts ──────────────────────────────────────────────────────────
    r += [
        E('profile', AUTH, reverse('profile')),
        E('user_list', ADMIN, reverse('user_list')),
        E('user_detail', ADMIN | {'swim_a'}, reverse('user_detail', args=[U['swim_a'].pk]), label='user_detail(own or admin)'),
        E('user_link_swimmer', ADMIN, reverse('user_link_swimmer', args=[fx.linkee.pk]), 'post',
          data={'swimmer': fx.guest.pk},
          effect=lambda: Swimmer.objects.get(pk=fx.guest.pk).user_id == fx.linkee.pk),
        E('user_unlink_swimmer', ADMIN, reverse('user_unlink_swimmer', args=[U['swim_a'].pk]), 'post',
          effect=lambda: Swimmer.objects.get(pk=P['swim_a'].pk).user is None),
    ]

    # ── persons ───────────────────────────────────────────────────────────
    r += [
        E('swimmer_list', PEOPLE_LIST, reverse('swimmer_list')),
        E('swimmer_create', {'trainer_a', 'trainer_b', 'admin'}, reverse('swimmer_create'),
          label='swimmer_create (form: only admin or trainer of a group)'),
        E('swimmer_create', {'trainer_a', 'admin'}, reverse('swimmer_create'), 'post',
          data={'first_name': 'New', 'last_name': 'Kid', 'group': A.pk, 'group_role': 'swimmer'},
          effect=lambda: Swimmer.objects.filter(first_name='New', last_name='Kid').exists(),
          label='swimmer_create POST into group A'),
        E('swimmer_detail', {'assist_a', 'trainer_a', 'trainer_b', 'trainer_free', 'admin'},
          reverse('swimmer_detail', args=[fx.kid_a.pk]),
          label='swimmer_detail(kid of A): basic for any trainer/assistant of A, nothing for swimmers'),
        E('swimmer_detail', AUTH - {'swim_b'}, reverse('swimmer_detail', args=[P['swim_a'].pk]),
          label='swimmer_detail(account holder in A): themself, trainers/assistants, admin – not other swimmers'),
        E('swimmer_propose', {'swim_a'}, reverse('swimmer_propose', args=[P['swim_a'].pk]), 'post',
          data={'first_name': 'Changed', 'last_name': 'User', 'phone': '0123', 'date_of_birth': '01.01.2000',
                'emergency_contact_name': '', 'emergency_contact_phone': ''},
          effect=lambda: PersonChangeRequest.objects.filter(swimmer=P['swim_a'], status='pending').exists(),
          label='swimmer_propose (only the person themself)'),
        E('swimmer_proposal_approve', A_MANAGE, '__approve__', 'post',
          effect=lambda: Swimmer.objects.get(pk=P['swim_a'].pk).first_name == 'Proposed',
          label='swimmer_proposal_approve (trainer of a group of the person, admin)'),
        E('swimmer_proposal_reject', A_MANAGE, '__reject__', 'post',
          effect=lambda: PersonChangeRequest.objects.get(swimmer=P['swim_a']).status == 'rejected',
          label='swimmer_proposal_reject'),
        E('swimmer_delete', ADMIN, reverse('swimmer_delete', args=[fx.kid_a.pk]), 'post',
          effect=lambda: not Swimmer.objects.get(pk=fx.kid_a.pk).active),
        E('swimmer_membership_add', A_MANAGE, reverse('swimmer_membership_add', args=[fx.kid_b.pk]), 'post',
          data={'group': A.pk, 'role': 'swimmer'},
          effect=lambda: GroupMembership.objects.filter(group=A, swimmer=fx.kid_b, active=True).exists(),
          label='swimmer_membership_add (into group A: trainers of A)'),
        E('swimmer_membership_add', A_MANAGE, reverse('swimmer_membership_add', args=[fx.kid_b.pk]), 'post',
          data={'group': A.pk, 'role': 'trainer'},
          effect=lambda: GroupMembership.objects.filter(group=A, swimmer=fx.kid_b, role='trainer').exists(),
          label='swimmer_membership_add as TRAINER (handing out trainer rights: trainers of that group only)'),
        E('swimmer_membership_remove', A_MANAGE,
          reverse('swimmer_membership_remove', args=[fx.kid_a.pk, A.pk]), 'post',
          effect=lambda: not GroupMembership.objects.get(group=A, swimmer=fx.kid_a).active),
    ]

    # ── groups ────────────────────────────────────────────────────────────
    r += [
        E('group_list', ALL, reverse('group_list'), label='group_list (public: names only)'),
        E('group_create', ADMIN, reverse('group_create')),
        E('group_create', ADMIN, reverse('group_create'), 'post',
          data={'name': 'Brand New', 'color': '#112233', 'active': 'on'},
          effect=lambda: Group.objects.filter(name='Brand New').exists(), label='group_create POST'),
        E('group_detail', A_OPERATE | {'trainer_b', 'trainer_free'}, reverse('group_detail', args=[A.pk]),
          label='group_detail (roster + sessions: every trainer read-only, assistants of that group, admin)'),
        E('group_edit', A_MANAGE, reverse('group_edit', args=[A.pk])),
        E('group_edit', A_MANAGE, reverse('group_edit', args=[A.pk]), 'post',
          data={'name': 'Renamed A', 'color': '#112233', 'active': 'on'},
          effect=lambda: Group.objects.get(pk=A.pk).name == 'Renamed A', label='group_edit POST'),
        E('group_member_create', A_MANAGE, reverse('group_member_create', args=[A.pk])),
        E('group_member_create', A_MANAGE, reverse('group_member_create', args=[A.pk]), 'post',
          data={'first_name': 'Fresh', 'last_name': 'Face', 'role': 'swimmer', 'active': 'on'},
          effect=lambda: GroupMembership.objects.filter(group=A, swimmer__first_name='Fresh').exists(),
          label='group_member_create POST'),
        E('membership_remove', A_MANAGE, reverse('membership_remove', args=[A.pk, fx.kid_a.pk]), 'post',
          effect=lambda: not GroupMembership.objects.get(group=A, swimmer=fx.kid_a).active),
        E('group_stats', A_MANAGE, reverse('group_stats', args=[A.pk])),
    ]

    # ── calendar / sessions ───────────────────────────────────────────────
    ev = reverse('calendar_events_api')
    r += [
        E('calendar_events_api', ALL, ev, data={'start': '2026-01-01', 'end': '2026-01-31'},
          label='calendar_events_api (public; content differs, see behaviour tests)'),
        E('session_modal', AUTH, reverse('session_modal', args=[rs.pk, PAST.isoformat()]),
          label='session_modal GET (anonymous: 403; others: content differs by role)'),
        E('session_modal', A_OPERATE, reverse('session_modal', args=[rs.pk, '2030-01-14']), 'post',
          effect=lambda: SessionInstance.objects.filter(recurring_session=rs, date=date(2030, 1, 14)).exists(),
          label='session_modal POST (start a session: assistant, trainer, admin)'),
        E('session_state_api', AUTH - {'swim_b', 'trainer_b', 'trainer_free'},
          reverse('session_state_api', args=[past.pk]),
          label='session_state_api (finished session: staff and participants only)'),
        E('session_state_api', A_OPERATE, reverse('session_state_api', args=[future.pk]),
          label='session_state_api (unfinished session: staff only)'),
        E('session_attendance_update_api', A_OPERATE, reverse('session_attendance_update_api', args=[past.pk]),
          'post', json_body={'swimmer_id': fx.kid_a.pk, 'status': 'absent'},
          effect=lambda: Attendance.objects.get(session=past, swimmer=fx.kid_a).status == 'absent'),
        E('session_settings_api', A_OPERATE, reverse('session_settings_api', args=[past.pk]), 'post',
          json_body={'is_optional': True},
          effect=lambda: SessionInstance.objects.get(pk=past.pk).is_optional),
        E('session_add_swimmer_api', A_OPERATE, reverse('session_add_swimmer_api', args=[future.pk]), 'post',
          json_body={'swimmer_id': fx.kid_b.pk, 'join_group': False},
          effect=lambda: Attendance.objects.filter(session=future, swimmer=fx.kid_b).exists(),
          label='session_add_swimmer_api (existing person as guest)'),
        E('session_add_swimmer_api', A_MANAGE, reverse('session_add_swimmer_api', args=[future.pk]), 'post',
          json_body={'swimmer_id': fx.kid_b.pk, 'join_group': True},
          effect=lambda: GroupMembership.objects.filter(group=A, swimmer=fx.kid_b, active=True).exists(),
          label='session_add_swimmer_api + join group (membership change: trainers only)'),
        E('session_add_swimmer_api', A_MANAGE, reverse('session_add_swimmer_api', args=[future.pk]), 'post',
          json_body={'first_name': 'Brand', 'last_name': 'Newcomer', 'join_group': True},
          effect=lambda: Swimmer.objects.filter(first_name='Brand').exists(),
          label='session_add_swimmer_api: create a NEW person (trainers only)'),
        E('plan_entry_photo_create', A_MANAGE, reverse('plan_entry_photo_create', args=[past.pk]), 'post',
          files={'photo': 'png'},
          effect=lambda: TrainingPlanEntry.objects.filter(session=past).count() == 2,
          label='plan_entry_photo_create (creating plan entries: trainers only)'),
        E('plan_entry_photo', A_MANAGE, reverse('plan_entry_photo', args=[fx.entry.pk]), 'post',
          files={'photo': 'png'},
          effect=lambda: bool(TrainingPlanEntry.objects.get(pk=fx.entry.pk).photo),
          label='plan_entry_photo (editing plan entries: trainers only)'),
        E('session_results_api', A_OPERATE, reverse('session_results_api', args=[past.pk]), 'post',
          json_body={'stroke': 'free', 'distance': 25, 'entries': [{'swimmer_id': fx.kid_a.pk, 'time': '15,50'}]},
          effect=lambda: PerformanceResult.objects.filter(session=past, distance_m=25).exists()),
        E('result_update_api', A_OPERATE, reverse('result_update_api', args=[fx.res_a.pk]), 'post',
          json_body={'time': '31,00'},
          effect=lambda: PerformanceResult.objects.get(pk=fx.res_a.pk).time_cs == 3100,
          label='result_update_api (result of a session)'),
        E('result_update_api', ADMIN, reverse('result_update_api', args=[fx.res_free.pk]), 'post',
          json_body={'time': '69,00'},
          effect=lambda: PerformanceResult.objects.get(pk=fx.res_free.pk).time_cs == 6900,
          label='result_update_api (result WITHOUT session: admin only)'),
        E('result_delete_api', A_OPERATE, reverse('result_delete_api', args=[fx.res_a.pk]), 'post',
          effect=lambda: not PerformanceResult.objects.filter(pk=fx.res_a.pk).exists(),
          label='result_delete_api (result of a session)'),
        E('result_delete_api', ADMIN, reverse('result_delete_api', args=[fx.res_free.pk]), 'post',
          effect=lambda: not PerformanceResult.objects.filter(pk=fx.res_free.pk).exists(),
          label='result_delete_api (result WITHOUT session: admin only)'),
        E('recurring_session_create', A_MANAGE, reverse('recurring_session_create', args=[A.pk]), 'post',
          data={'day_of_week': 2, 'start_time': '17:00', 'end_time': '18:00', 'valid_from': '01.01.2026',
                'active': 'on', 'location': fx.pool.pk},
          effect=lambda: RecurringSession.objects.filter(group=A).count() == 2),
        E('recurring_session_edit', A_MANAGE, reverse('recurring_session_edit', args=[rs.pk]), 'post',
          data={'day_of_week': 0, 'start_time': '18:00', 'end_time': '19:00', 'valid_from': '01.01.2025',
                'active': 'on', 'location': fx.pool.pk, 'notes': 'edited'},
          effect=lambda: RecurringSession.objects.get(pk=rs.pk).notes == 'edited'),
        E('exception_create', {'trainer_a', 'trainer_b', 'admin'}, reverse('exception_create'),
          label='exception_create (form: trainers of any group, admin)'),
        E('exception_create', A_MANAGE, reverse('exception_create'), 'post',
          data={'date': '12.01.2026', 'reason': 'Pool closed', 'affected_sessions': [rs.pk]},
          effect=lambda: SessionException.objects.filter(reason='Pool closed').exists(),
          label='exception_create for a session of group A (trainers of A only)'),
        E('exception_create', ADMIN, reverse('exception_create'), 'post',
          data={'date': '12.01.2026', 'reason': 'Holiday', 'affects_all': 'on'},
          effect=lambda: SessionException.objects.filter(reason='Holiday', affects_all=True).exists(),
          label='exception_create affecting ALL sessions (admin only)'),
        E('generate_excuse_token', A_OPERATE, reverse('generate_excuse_token'), 'post',
          json_body={'swimmer_id': fx.kid_a.pk, 'session_id': rs.pk, 'date': PAST.isoformat()},
          effect=lambda: ExcuseToken.objects.filter(swimmer=fx.kid_a).exists()),
        E('trainer_report', {'assist_a', 'trainer_a', 'trainer_b', 'admin'}, reverse('trainer_report'),
          label='trainer_report (anybody entered as trainer; admin too)'),
    ]
    return r


def is_denied(resp):
    if resp.status_code == 403:
        return True
    if resp.status_code in (301, 302):
        if '/accounts/login/' in resp['Location']:
            return True
        return any(str(m) in NO_PERMISSION for m in get_messages(resp.wsgi_request))
    return False


class EndpointMatrixTests(PermFixture):
    def _call(self, e, role):
        self.login(role)
        url = e.url
        if url in ('__approve__', '__reject__'):
            req = PersonChangeRequest.objects.get(swimmer=self.people['swim_a'])
            kind = 'approve' if url == '__approve__' else 'reject'
            url = reverse(f'swimmer_proposal_{kind}', args=[self.people['swim_a'].pk, req.pk])
        if e.method == 'get':
            return self.client.get(url, e.data or {})
        if e.json_body is not None:
            return self.post_json(url, e.json_body)
        data = dict(e.data or {})
        if e.files:
            data.update({k: png() for k in e.files})
        return self.client.post(url, data)

    def test_matrix(self):
        failures = []
        for e in rows(self):
            for role in ROLES:
                with transaction.atomic():
                    if e.url in ('__approve__', '__reject__'):
                        PersonChangeRequest.objects.create(
                            swimmer=self.people['swim_a'], proposed_by=self.users['swim_a'],
                            changes={'first_name': 'Proposed'})
                    resp = self._call(e, role)
                    denied = is_denied(resp)
                    should_allow = role in e.allowed
                    if should_allow and (denied or resp.status_code >= 400):
                        failures.append(f'{e.label}: {role} should be ALLOWED but got {resp.status_code} (denied={denied})')
                    if not should_allow and not denied and e.effect is None:
                        failures.append(f'{e.label}: {role} should be DENIED but got {resp.status_code}')
                    if e.effect is not None:
                        did = bool(e.effect())
                        if did != should_allow:
                            failures.append(
                                f'{e.label}: {role} -> effect={did}, expected {should_allow} (status {resp.status_code})')
                    transaction.set_rollback(True)
        self.assertEqual(failures, [], '\n' + '\n'.join(failures))

    def test_every_endpoint_is_classified(self):
        """A new URL without a permission decision must fail the build."""
        names = set()

        def walk(patterns):
            for p in patterns:
                if hasattr(p, 'url_patterns'):
                    if str(p.pattern) == 'admin/':
                        continue                      # Django admin: staff-only by Django itself
                    walk(p.url_patterns)
                elif p.name:
                    names.add(p.name)
        walk(get_resolver().url_patterns)
        classified = {e.name for e in rows(self)} | PUBLIC_ENDPOINTS
        self.assertEqual(
            sorted(names - classified), [],
            'These endpoints have no permission test. Add them to ENDPOINTS in accounts/test_permissions.py '
            '(or to PUBLIC_ENDPOINTS if they are public by design).')
