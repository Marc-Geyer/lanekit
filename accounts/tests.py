from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from swimmers.models import Swimmer
from .views import send_verification_email


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class RegistrationTests(TestCase):
    def setUp(self):
        self.swimmer = Swimmer.objects.create(
            first_name='Anna', last_name='Test', email='anna@example.com')

    def _data(self, **kw):
        d = {'first_name': 'Anna', 'last_name': 'Test', 'username': 'anna',
             'email': 'anna@example.com', 'password1': 'Sup3r-secret-pw!',
             'password2': 'Sup3r-secret-pw!'}
        d.update(kw)
        return d

    def test_register_sends_mail_and_activation_links_person(self):
        r = self.client.post(reverse('register'), self._data())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        user = User.objects.get(username='anna')
        self.assertFalse(user.is_active)
        # activation link from the mail body
        link = [w for w in mail.outbox[0].body.split() if '/accounts/activate/' in w][0]
        path = '/' + link.split('/', 3)[3]
        self.client.get(path)
        user.refresh_from_db()
        self.swimmer.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertEqual(self.swimmer.user, user)

    def test_mail_failure_rolls_back_account(self):
        with mock.patch('accounts.views.send_mail', side_effect=OSError('smtp down')):
            r = self.client.post(reverse('register'), self._data())
        self.assertEqual(r.status_code, 200)            # no 500
        self.assertFalse(User.objects.filter(username='anna').exists())

    def test_unknown_email_creates_no_account(self):
        self.client.post(reverse('register'), self._data(email='nobody@example.com'))
        self.assertFalse(User.objects.filter(username='anna').exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_invalid_activation_link_renders_page(self):
        r = self.client.get(reverse('activate', kwargs={'uidb64': 'xx', 'token': 'bad'}))
        self.assertEqual(r.status_code, 200)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class EmailChangeAndLinkTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('anna', 'old@example.com', 'pw', first_name='Anna', last_name='T')
        self.swimmer = Swimmer.objects.create(
            first_name='Anna', last_name='T', email='old@example.com', user=self.user)
        self.admin = User.objects.create_user('boss', 'boss@example.com', 'pw')
        self.admin.profile.role = 'admin'
        self.admin.profile.save()

    def _profile_post(self, email):
        return self.client.post(reverse('profile'), {
            'first_name': 'Anna', 'last_name': 'T', 'email': email,
            'role': 'swimmer', 'phone': '', 'bio': ''})

    def test_own_email_change_needs_verification_and_syncs_person(self):
        self.client.force_login(self.user)
        self._profile_post('new@example.com')
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'old@example.com')      # not yet changed
        self.assertEqual(mail.outbox[-1].to, ['new@example.com'])
        link = [w for w in mail.outbox[-1].body.split() if '/verify-email/' in w][0]
        self.client.get('/' + link.split('/', 3)[3])
        self.user.refresh_from_db(); self.swimmer.refresh_from_db()
        self.assertEqual(self.user.email, 'new@example.com')
        self.assertEqual(self.swimmer.email, 'new@example.com')
        # link is single-use
        self.client.get('/' + link.split('/', 3)[3])
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'new@example.com')

    def test_duplicate_email_rejected(self):
        self.client.force_login(self.user)
        self._profile_post('boss@example.com')
        self.assertEqual(len(mail.outbox), 0)

    def test_user_cannot_promote_self(self):
        self.client.force_login(self.user)
        self.client.post(reverse('profile'), {
            'first_name': 'Anna', 'last_name': 'T', 'email': 'old@example.com',
            'role': 'admin', 'phone': '', 'bio': ''})
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.role, 'swimmer')

    def test_admin_changes_email_directly(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('user_detail', args=[self.user.pk]), {
            'first_name': 'Anna', 'last_name': 'T', 'email': 'admin-set@example.com',
            'role': 'swimmer', 'phone': '', 'bio': ''})
        self.user.refresh_from_db(); self.swimmer.refresh_from_db()
        self.assertEqual(self.user.email, 'admin-set@example.com')
        self.assertEqual(self.swimmer.email, 'admin-set@example.com')

    def test_admin_link_and_unlink(self):
        free = Swimmer.objects.create(first_name='Ben', last_name='X', email='ben@example.com')
        ben = User.objects.create_user('ben', 'ben-account@example.com', 'pw')
        self.client.force_login(self.admin)
        self.client.post(reverse('user_link_swimmer', args=[ben.pk]), {'swimmer': free.pk})
        free.refresh_from_db()
        self.assertEqual(free.user, ben)
        self.assertEqual(free.email, 'ben-account@example.com')
        self.client.post(reverse('user_unlink_swimmer', args=[ben.pk]))
        free.refresh_from_db()
        self.assertIsNone(free.user)

    def test_non_admin_cannot_link(self):
        free = Swimmer.objects.create(first_name='Ben', last_name='X')
        self.client.force_login(self.user)
        self.client.post(reverse('user_link_swimmer', args=[self.user.pk]), {'swimmer': free.pk})
        free.refresh_from_db()
        self.assertIsNone(free.user)
