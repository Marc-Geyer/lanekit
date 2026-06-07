from django.db import models
from django.contrib.auth.models import User


class Swimmer(models.Model):
    """A person who participates in training sessions.
    May be linked to a User account, or exist as a standalone contact record."""

    user = models.OneToOneField(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='swimmer'
    )
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    emergency_contact_name = models.CharField(max_length=200, blank=True)
    emergency_contact_phone = models.CharField(max_length=30, blank=True)
    notes = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['last_name', 'first_name']

    def __str__(self):
        return self.full_name

    @property
    def full_name(self):
        return f'{self.first_name} {self.last_name}'

    @property
    def initials(self):
        return f'{self.first_name[:1]}{self.last_name[:1]}'.upper()

    def get_groups(self):
        from groups.models import GroupMembership
        return GroupMembership.objects.filter(swimmer=self).select_related('group')
