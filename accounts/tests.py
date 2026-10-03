from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from unittest.mock import patch

class AccountsViewsTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='testuser', password='password', email='test@test.com')

    def test_login_view(self):
        response = self.client.post(reverse('login'), {'username': 'testuser', 'password': 'password'})
        self.assertRedirects(response, '/calendar/')

    def test_logout_view(self):
        self.client.login(username='testuser', password='password')
        response = self.client.get(reverse('logout'))
        self.assertRedirects(response, '/calendar/')
        self.assertFalse(self.client.session.get('_auth_user_id'))

    @patch('django.core.mail.send_mail')
    def test_register_view(self, mock_send_mail):
        # Note: registration requires an existing Swimmer with the same email per view logic
        from swimmers.models import Swimmer
        Swimmer.objects.create(first_name="Reg", last_name="User", email="test@test.com", active=True)
        
        response = self.client.post(reverse('register'), {
            'username': 'newuser',
            'password': 'password123',
            'email': 'test@test.com'
        })
        self.assertEqual(response.status_code, 200) # Template rendered
        mock_send_mail.assert_called()

    def test_profile_view(self):
        self.client.login(username='testuser', password='password')
        response = self.client.get(reverse('profile'))
        self.assertEqual(response.status_code, 200)

    def test_user_list_view_admin_only(self):
        admin = User.objects.create_superuser(username='admin', password='password')
        self.client.login(username='testuser', password='password')
        response = self.client.get(reverse('user_list'))
        self.assertEqual(response.status_code, 302)
        
        self.client.login(username='admin', password='password')
        response = self.client.get(reverse('user_list'))
        self.assertEqual(response.status_code, 200)
