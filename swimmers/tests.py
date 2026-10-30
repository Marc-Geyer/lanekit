from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from groups.models import Group, GroupMembership
from .forms import SwimmerForm
from .models import Swimmer


class SwimmerListFilterTests(TestCase):
    def setUp(self):
        u = User.objects.create_user('admin1', password='x')
        u.profile.role = 'admin'
        u.profile.save()
        self.client.force_login(u)
        self.g1 = Group.objects.create(name='Masters')
        self.g2 = Group.objects.create(name='Kids')
        self.anna = Swimmer.objects.create(first_name='Anna', last_name='Alt', date_of_birth=date(1990, 5, 1))
        self.ben = Swimmer.objects.create(first_name='Ben', last_name='Jung', date_of_birth=date(2012, 3, 3))
        self.cara = Swimmer.objects.create(first_name='Cara', last_name='Inaktiv', active=False)
        self.dora = Swimmer.objects.create(first_name='Dora', last_name='Solo', user=u)
        GroupMembership.objects.create(group=self.g1, swimmer=self.anna, role='trainer')
        GroupMembership.objects.create(group=self.g2, swimmer=self.ben)
        GroupMembership.objects.create(group=self.g2, swimmer=self.cara)

    def names(self, **params):
        r = self.client.get(reverse('swimmer_list'), params)
        self.assertEqual(r.status_code, 200)
        return [s.first_name for s in r.context['swimmers']]

    def test_default_hides_inactive(self):
        self.assertNotIn('Cara', self.names())

    def test_inactive_search_is_not_reset(self):
        # Regression: an unchecked "active only" box sent nothing and the view fell back to active.
        self.assertEqual(self.names(status='inactive'), ['Cara'])
        self.assertIn('Cara', self.names(status='all'))

    def test_text_search_matches_group_name_partially(self):
        self.assertEqual(self.names(q='mast'), ['Anna'])

    def test_multiple_words_must_all_match(self):
        self.assertEqual(self.names(q='ben jung'), ['Ben'])
        self.assertEqual(self.names(q='ben alt'), [])

    def test_group_none_role_and_birth_year(self):
        self.assertEqual(self.names(group='none'), ['Dora'])
        self.assertEqual(self.names(role='trainer'), ['Anna'])
        self.assertEqual(self.names(group=self.g1.pk, role='swimmer'), [])
        self.assertEqual(self.names(born_from='2000'), ['Ben'])
        self.assertEqual(self.names(born_to='1999'), ['Anna'])

    def test_account_filter_and_sort(self):
        self.assertEqual(self.names(account='with'), ['Dora'])
        self.assertNotIn('Dora', self.names(account='without'))
        self.assertEqual(self.names(sort='age')[0], 'Ben')       # youngest first
        self.assertEqual(self.names(sort='first')[:2], ['Anna', 'Ben'])

    def test_garbage_params_do_not_crash(self):
        self.assertTrue(self.names(status='x', role='y', sort='z', born_from='abc', account='?', group='1;drop'))


class DateWidgetTests(TestCase):
    def test_saved_date_is_rendered_european(self):
        s = Swimmer.objects.create(first_name='A', last_name='B', date_of_birth=date(2011, 2, 9))
        html = str(SwimmerForm(instance=s)['date_of_birth'])
        self.assertIn('value="09.02.2011"', html)
        self.assertNotIn('type="date"', html)

    def test_european_input_is_accepted(self):
        f = SwimmerForm(data={'first_name': 'A', 'last_name': 'B', 'date_of_birth': '09.02.2011', 'active': 'on'})
        self.assertTrue(f.is_valid(), f.errors)
        self.assertEqual(f.cleaned_data['date_of_birth'], date(2011, 2, 9))
