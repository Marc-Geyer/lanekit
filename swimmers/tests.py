from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from swimmers.models import Swimmer
from groups.models import Group, GroupMembership

class SwimmersViewsTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser(username='admin', password='password')
        self.trainer = User.objects.create_user(username='trainer', password='password')
        self.trainer.profile.role = 'trainer'
        self.trainer.profile.save()
        
        self.swimmer_user = User.objects.create_user(username='swimmer', password='password')
        self.swimmer = Swimmer.objects.create(user=self.swimmer_user, first_name="Test", last_name="Swimmer", active=True)
        self.group = Group.objects.create(name="Test Group", active=True)

    def test_swimmer_list_view(self):
        self.client.login(username='trainer', password='password')
        response = self.client.get(reverse('swimmer_list'))
        self.assertEqual(response.status_code, 200)

    def test_swimmer_detail_view_edit(self):
        self.client.login(username='trainer', password='password')
        response = self.client.get(reverse('swimmer_detail', kwargs={'pk': self.swimmer.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['can_edit'])

    def test_swimmer_create_view(self):
        self.client.login(username='trainer', password='password')
        response = self.client.post(reverse('swimmer_create'), {
            'first_name': 'New',
            'last_name': 'Swimmer',
            'email': 'new@test.com'
        })
        self.assertRedirects(response, reverse('swimmer_detail', kwargs={'pk': Swimmer.objects.get(first_name='New').pk}))

    def test_swimmer_delete_view_admin_only(self):
        self.client.login(username='trainer', password='password')
        response = self.client.get(reverse('swimmer_delete', kwargs={'pk': self.swimmer.pk}))
        self.assertEqual(response.status_code, 302)

    def test_swimmer_autocomplete(self):
        response = self.client.get(reverse('swimmer_autocomplete'), {'q': 'Test'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('results', response.json())
