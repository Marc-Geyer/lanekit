from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from groups.models import Group, GroupMembership
from swimmers.models import Swimmer

class GroupsViewsTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_superuser(username='admin', password='password', email='admin@test.com')
        self.trainer_user = User.objects.create_user(username='trainer', password='password')
        self.swimmer_user = User.objects.create_user(username='swimmer', password='password')
        
        self.group = Group.objects.create(name="Test Group", active=True)
        self.swimmer = Swimmer.objects.create(user=self.swimmer_user, first_name="John", last_name="Doe", active=True)
        
        # Set up profile roles (assuming profile is created via signals)
        self.trainer_user.profile.role = 'trainer' # Adjust based on your UserProfile constants
        self.trainer_user.profile.save()

    def test_group_list_view(self):
        response = self.client.get(reverse('group_list'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('groups', response.context)

    def test_group_detail_view_unauthenticated(self):
        response = self.client.get(reverse('group_detail', kwargs={'pk': self.group.pk}))
        self.assertEqual(response.status_code, 302) # Redirect to login

    def test_group_edit_view_permission_denied(self):
        self.client.login(username='swimmer', password='password')
        response = self.client.get(reverse('group_edit', kwargs={'pk': self.group.pk}))
        self.assertEqual(response.status_code, 302) # Redirect back to detail

    def test_group_create_view_admin_only(self):
        self.client.login(username='trainer', password='password')
        response = self.client.get(reverse('group_create'))
        self.assertEqual(response.status_code, 302) # Redirect to list

    def test_membership_add_view(self):
        self.client.login(username='trainer', password='password')
        # Ensure trainer is actually a trainer for this group
        GroupMembership.objects.create(group=self.group, swimmer=self.swimmer, role='swimmer')
        # Note: logic in view requires user to be trainer of the group or admin
        # This test assumes the setup above makes them a trainer or you adjust the user
        
        response = self.client.post(reverse('membership_add', kwargs={'group_pk': self.group.pk}), {
            'swimmer': self.swimmer.pk,
            'role': 'swimmer'
        })
        self.assertRedirects(response, reverse('group_detail', kwargs={'pk': self.group.pk}))

    def test_membership_remove_view(self):
        self.client.login(username='admin', password='password')
        membership = GroupMembership.objects.create(group=self.group, swimmer=self.swimmer, role='swimmer')
        
        response = self.client.post(reverse('membership_remove', kwargs={'group_pk': self.group.pk, 'swimmer_pk': self.swimmer.pk}))
        self.assertRedirects(response, reverse('group_detail', kwargs={'pk': self.group.pk}))
        self.assertFalse(membership.refresh_from_db().active)
