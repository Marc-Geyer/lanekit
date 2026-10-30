import json
from datetime import date, time

from django.test import TestCase
from django.urls import reverse

from groups.models import Group, GroupMembership
from swimmers.models import Swimmer
from . import performance
from .models import Attendance, Location, PerformanceResult, RecurringSession, SessionInstance
from .test_stats import mkuser


class ParseTimeTests(TestCase):
    def test_valid_formats(self):
        p = performance.parse_time
        self.assertEqual(p('32,45'), 3245)
        self.assertEqual(p('32.45'), 3245)
        self.assertEqual(p('1:05,32'), 6532)
        self.assertEqual(p('1:05.3'), 6530)      # one decimal digit = tenths
        self.assertEqual(p('65,32'), 6532)
        self.assertEqual(p(' 2:00 '), 12000)
        self.assertEqual(p('32'), 3200)

    def test_invalid_formats(self):
        p = performance.parse_time
        for bad in ('', 'abc', '1:65,00', '0', '0,00', '1:05,321', '-5', '5:', None, 32, '99:99:99', '4:00:00'):
            self.assertIsNone(p(bad), bad)

    def test_format_roundtrip(self):
        for cs in (3245, 6532, 12000, 100, 359999):
            self.assertEqual(performance.parse_time(performance.format_time(cs)), cs)
        self.assertEqual(performance.format_time(3245), '32,45')
        self.assertEqual(performance.format_time(6532), '1:05,32')


class ResultBase(TestCase):
    def setUp(self):
        self.g = Group.objects.create(name='A')
        self.coach_u, self.coach = mkuser('coach')
        GroupMembership.objects.create(group=self.g, swimmer=self.coach, role='trainer')
        self.other_u, self.other_coach = mkuser('other')
        self.g2 = Group.objects.create(name='B')
        GroupMembership.objects.create(group=self.g2, swimmer=self.other_coach, role='trainer')
        self.mia = Swimmer.objects.create(first_name='Mia', last_name='Eins')
        self.max = Swimmer.objects.create(first_name='Max', last_name='Zwei')
        for s in (self.mia, self.max):
            GroupMembership.objects.create(group=self.g, swimmer=s)
        self.pool = Location.objects.create(name='Pool', type='25m_Pool', city='L', street_address='x', lanes=6)
        self.rs = RecurringSession.objects.create(
            group=self.g, day_of_week=0, start_time=time(18), end_time=time(19),
            valid_from=date(2026, 1, 1), location=self.pool)
        self.inst = SessionInstance.objects.create(recurring_session=self.rs, date=date(2026, 10, 26))
        for s in (self.mia, self.max):
            Attendance.objects.create(session=self.inst, swimmer=s, status='present')
        self.url = reverse('session_results_api', args=[self.inst.pk])

    def post(self, payload, user=None):
        self.client.force_login(user or self.coach_u)
        return self.client.post(self.url, json.dumps(payload), content_type='application/json')


class SessionResultsApiTests(ResultBase):
    def test_batch_create_sets_session_context(self):
        r = self.post({'stroke': 'free', 'distance': 50, 'entries': [
            {'swimmer_id': self.mia.pk, 'time': '32,45'},
            {'swimmer_id': self.max.pk, 'time': '1:05,3'},
        ]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['saved'], 2)
        res = PerformanceResult.objects.get(swimmer=self.mia)
        self.assertEqual((res.time_cs, res.date, res.location, res.pool_length), (3245, date(2026, 10, 26), self.pool, 25))
        self.assertEqual(res.session, self.inst)
        self.assertFalse(res.is_official)               # training times are always unofficial
        self.assertEqual(res.recorded_by, self.coach_u)

    def test_invalid_time_saves_nothing(self):
        r = self.post({'stroke': 'free', 'distance': 50, 'entries': [
            {'swimmer_id': self.mia.pk, 'time': '32,45'},
            {'swimmer_id': self.max.pk, 'time': 'oops'},
        ]})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()['errors'], {str(self.max.pk): 'invalid_time'})
        self.assertEqual(PerformanceResult.objects.count(), 0)

    def test_rejects_swimmer_outside_session_and_bad_input(self):
        outsider = Swimmer.objects.create(first_name='Out', last_name='Side')
        self.assertEqual(self.post({'stroke': 'free', 'distance': 50, 'entries': [
            {'swimmer_id': outsider.pk, 'time': '30,00'}]}).status_code, 400)
        self.assertEqual(self.post({'stroke': 'nope', 'distance': 50, 'entries': [
            {'swimmer_id': self.mia.pk, 'time': '30,00'}]}).status_code, 400)
        for dist in (0, -5, 'x', True, 10001, None):
            self.assertEqual(self.post({'stroke': 'free', 'distance': dist, 'entries': [
                {'swimmer_id': self.mia.pk, 'time': '30,00'}]}).status_code, 400, dist)
        self.assertEqual(self.post({'stroke': 'free', 'distance': 50, 'entries': []}).status_code, 400)
        self.assertEqual(self.post([1, 2]).status_code, 400)
        self.assertEqual(PerformanceResult.objects.count(), 0)

    def test_permissions(self):
        payload = {'stroke': 'free', 'distance': 50, 'entries': [{'swimmer_id': self.mia.pk, 'time': '30,00'}]}
        self.assertEqual(self.post(payload, user=self.other_u).status_code, 403)   # trainer of another group
        self.client.logout()
        self.assertEqual(self.client.post(self.url, json.dumps(payload), content_type='application/json').status_code, 302)
        self.assertEqual(PerformanceResult.objects.count(), 0)

    def test_get_lists_grouped_results(self):
        self.post({'stroke': 'back', 'distance': 100, 'entries': [{'swimmer_id': self.mia.pk, 'time': '1:20,10'}]})
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertIn('1:20,10', r.json()['html'])

    def test_modal_contains_results_section_for_trainer_only(self):
        modal = reverse('session_modal', args=[self.rs.pk, '2026-10-26'])
        self.client.force_login(self.coach_u)
        self.assertIn('resultsBody', self.client.get(modal).json()['html'])
        self.client.force_login(self.other_u)
        self.assertNotIn('resultsBody', self.client.get(modal).json()['html'])


class ResultEditTests(ResultBase):
    def setUp(self):
        super().setUp()
        self.res = PerformanceResult.objects.create(
            swimmer=self.mia, session=self.inst, date=self.inst.date, stroke='free', distance_m=50, time_cs=3000)

    def post_to(self, name, payload, user):
        self.client.force_login(user)
        return self.client.post(reverse(name, args=[self.res.pk]), json.dumps(payload), content_type='application/json')

    def test_update_and_delete(self):
        r = self.post_to('result_update_api', {'time': '29,80'}, self.coach_u)
        self.assertEqual(r.json()['time'], '29,80')
        self.res.refresh_from_db()
        self.assertEqual(self.res.time_cs, 2980)
        self.assertEqual(self.post_to('result_update_api', {'time': 'x'}, self.coach_u).status_code, 400)
        self.assertEqual(self.post_to('result_delete_api', {}, self.coach_u).status_code, 200)
        self.assertFalse(PerformanceResult.objects.exists())

    def test_foreign_trainer_cannot_change(self):
        self.assertEqual(self.post_to('result_update_api', {'time': '20,00'}, self.other_u).status_code, 403)
        self.assertEqual(self.post_to('result_delete_api', {}, self.other_u).status_code, 403)
        self.assertEqual(PerformanceResult.objects.count(), 1)


class SwimmerChartAccessTests(ResultBase):
    def setUp(self):
        super().setUp()
        PerformanceResult.objects.create(
            swimmer=self.mia, session=self.inst, date=self.inst.date, stroke='free', distance_m=50, time_cs=3000)
        self.detail = reverse('swimmer_detail', args=[self.mia.pk])

    def test_group_trainer_sees_chart_data(self):
        self.client.force_login(self.coach_u)
        html = self.client.get(self.detail).content.decode()
        self.assertIn('id="perfData"', html)
        self.assertIn('"time_cs": 3000', html)

    def test_unrelated_user_does_not(self):
        plain_u, _ = mkuser('plain')
        for u in (plain_u, self.other_u):
            self.client.force_login(u)
            self.assertNotIn('perfData', self.client.get(self.detail).content.decode())

    def test_swimmer_sees_own_but_not_others(self):
        own_u, own = mkuser('own')
        GroupMembership.objects.create(group=self.g, swimmer=own)
        self.client.force_login(own_u)
        self.assertIn('perfData', self.client.get(reverse('swimmer_detail', args=[own.pk])).content.decode())
        self.assertNotIn('perfData', self.client.get(self.detail).content.decode())


class ModelTests(TestCase):
    def test_pool_length_derived_from_location(self):
        s = Swimmer.objects.create(first_name='A', last_name='B')
        p50 = Location.objects.create(name='L', type='50m_Pool', city='x', street_address='y')
        hall = Location.objects.create(name='H', type='athletic', city='x', street_address='y')
        a = PerformanceResult.objects.create(swimmer=s, date=date(2026, 1, 1), stroke='fly', distance_m=100, time_cs=6000, location=p50)
        b = PerformanceResult.objects.create(swimmer=s, date=date(2026, 1, 1), stroke='fly', distance_m=100, time_cs=6000, location=hall)
        c = PerformanceResult.objects.create(swimmer=s, date=date(2026, 1, 1), stroke='fly', distance_m=100, time_cs=6000, location=p50, pool_length=25)
        self.assertEqual((a.pool_length, b.pool_length, c.pool_length), (50, None, 25))


# ── Websocket sync ───────────────────────────────────────────────────────────

from unittest import mock

from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase

from .consumers import SessionConsumer


class ResultBroadcastTests(ResultBase):
    def test_every_change_is_broadcast(self):
        with mock.patch('training.views._broadcast_results_changed') as bc:
            self.post({'stroke': 'free', 'distance': 50, 'entries': [{'swimmer_id': self.mia.pk, 'time': '30,00'}]})
            res = PerformanceResult.objects.get()
            self.client.post(reverse('result_update_api', args=[res.pk]),
                             json.dumps({'time': '29,00'}), content_type='application/json')
            self.client.post(reverse('result_delete_api', args=[res.pk]), '{}', content_type='application/json')
        self.assertEqual([c.args[0] for c in bc.call_args_list], [self.inst.pk] * 3)

    def test_failed_save_does_not_broadcast(self):
        with mock.patch('training.views._broadcast_results_changed') as bc:
            self.post({'stroke': 'free', 'distance': 50, 'entries': [{'swimmer_id': self.mia.pk, 'time': 'x'}]})
            self.post({'stroke': 'free', 'distance': 50, 'entries': [{'swimmer_id': self.mia.pk, 'time': '30,00'}]},
                      user=self.other_u)
        bc.assert_not_called()

    def test_broadcast_failure_never_breaks_the_save(self):
        with mock.patch('training.views.async_to_sync', side_effect=RuntimeError('redis down')):
            r = self.post({'stroke': 'free', 'distance': 50, 'entries': [{'swimmer_id': self.mia.pk, 'time': '30,00'}]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(PerformanceResult.objects.count(), 1)


class ResultWebsocketTests(TransactionTestCase):
    """The consumer forwards the view's broadcast to every connected trainer."""

    def test_connected_client_receives_results_changed(self):
        import asyncio
        coach_u, coach = mkuser('wscoach')
        g = Group.objects.create(name='W')
        GroupMembership.objects.create(group=g, swimmer=coach, role='trainer')
        rs = RecurringSession.objects.create(
            group=g, day_of_week=0, start_time=time(18), end_time=time(19), valid_from=date(2026, 1, 1))
        inst = SessionInstance.objects.create(recurring_session=rs, date=date(2026, 10, 26))

        async def scenario():
            comm = WebsocketCommunicator(SessionConsumer.as_asgi(), f'/ws/session/{inst.pk}/')
            comm.scope['user'] = coach_u
            comm.scope['url_route'] = {'kwargs': {'session_id': str(inst.pk)}}
            connected, _ = await comm.connect()
            self.assertTrue(connected)
            self.assertEqual((await comm.receive_json_from())['type'], 'init')
            from .views import _broadcast_results_changed
            await sync_to_async(_broadcast_results_changed)(inst.pk)
            msg = await comm.receive_json_from(timeout=3)
            self.assertEqual(msg, {'type': 'results_changed', 'data': {'session_id': inst.pk}})
            await comm.disconnect()

        asyncio.run(scenario())


# ── Group overview tab ───────────────────────────────────────────────────────

class GroupTimesTabTests(ResultBase):
    def setUp(self):
        super().setUp()
        self.admin_u, _ = mkuser('boss', role='trainer')      # profile trainer
        self.pool50 = Location.objects.create(name='Big', type='50m_Pool', city='x', street_address='y')
        self.day = date(2026, 10, 20)

        def res(swimmer, cs, day, loc=None, stroke='free', dist=50):
            return PerformanceResult.objects.create(
                swimmer=swimmer, date=day, stroke=stroke, distance_m=dist, time_cs=cs, location=loc or self.pool)
        res(self.mia, 3300, date(2026, 10, 10))
        res(self.mia, 3100, date(2026, 10, 20))
        res(self.max, 3000, date(2026, 10, 20))
        res(self.max, 2900, date(2026, 10, 21), loc=self.pool50)       # other pool length
        res(self.coach, 2000, date(2026, 10, 20))                      # trainer: excluded
        res(self.mia, 7000, date(2026, 10, 20), stroke='back', dist=100)
        self.url = reverse('group_stats', args=[self.g.pk])
        self.q = {'tab': 'times', 'range': 'custom', 'from': '2026-10-01', 'to': '2026-10-28'}

    def get(self, **extra):
        self.client.force_login(self.admin_u)
        return self.client.get(self.url, {**self.q, **extra})

    def blocks(self, **extra):
        return self.get(**extra).context['blocks']

    def test_permissions(self):
        self.client.force_login(self.coach_u)                           # group trainer only
        self.assertEqual(self.client.get(self.url, self.q).status_code, 302)

    def test_ranking_split_by_pool(self):
        bl = self.blocks()
        keys = [(b['stroke'], b['distance'], b['pool']) for b in bl]
        self.assertEqual(keys, [('free', 50, 25), ('free', 50, 50), ('back', 100, 25)])
        free25 = bl[0]['rows']
        self.assertEqual([r['swimmer'] for r in free25], [self.max, self.mia])          # trainer excluded, fastest first
        mia = free25[1]
        self.assertEqual((mia['best'], mia['latest'], mia['count'], mia['change']), ('31,00', '31,00', 2, '-2,00'))
        self.assertEqual(free25[0]['change'], None)                                    # one time: no development
        self.assertEqual(len(bl[1]['rows']), 1)                                         # the 50 m swim of Max

    def test_merge_pools_option(self):
        bl = self.blocks(pools='merge')
        free = bl[0]
        self.assertEqual((free['stroke'], free['pool']), ('free', None))
        self.assertTrue(free['mixed_pools'])
        self.assertEqual(free['rows'][0]['best'], '29,00')                             # Max' 50 m time now counts
        self.assertEqual(free['rows'][0]['count'], 2)

    def test_stroke_distance_and_range_filter(self):
        self.assertEqual([b['stroke'] for b in self.blocks(stroke='back')], ['back'])
        self.assertEqual([b['distance'] for b in self.blocks(distance='100')], [100])
        self.assertEqual(self.blocks(stroke='bogus', distance='abc')[0]['stroke'], 'free')    # invalid → ignored
        ctx = self.get(**{'from': '2026-10-15'}).context
        self.assertEqual(ctx['total_results'], 4)                                       # the 10 Oct time drops out

    def test_attendance_tab_still_default(self):
        self.client.force_login(self.admin_u)
        ctx = self.client.get(self.url).context
        self.assertEqual(ctx['tab'], 'attendance')
        self.assertIn('summary', ctx)
        html = self.client.get(self.url).content.decode()
        self.assertIn('tab=times', html)

    def test_tab_links_keep_range(self):
        html = self.get().content.decode()
        self.assertIn('range=custom', html.split('tab=attendance')[0].split('href="?')[-1])
