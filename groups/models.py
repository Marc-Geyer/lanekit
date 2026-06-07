from django.db import models
from swimmers.models import Swimmer


class Group(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    color = models.CharField(max_length=7, default='#0d6efd',
                             help_text='Hex colour for the calendar (e.g. #0d6efd)')
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def get_trainers(self):
        return GroupMembership.objects.filter(
            group=self, role=GroupMembership.ROLE_TRAINER, active=True
        ).select_related('swimmer')

    def get_members(self):
        return GroupMembership.objects.filter(
            group=self, active=True
        ).select_related('swimmer').order_by('role', 'swimmer__last_name')


class GroupMembership(models.Model):
    ROLE_SWIMMER = 'swimmer'
    ROLE_TRAINER = 'trainer'
    ROLE_CHOICES = [
        (ROLE_SWIMMER, 'Schwimmer'),
        (ROLE_TRAINER, 'Trainer'),
    ]

    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name='memberships')
    swimmer = models.ForeignKey(Swimmer, on_delete=models.CASCADE, related_name='groupmembership_set')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_SWIMMER)
    active = models.BooleanField(default=True)
    joined_date = models.DateField(auto_now_add=True)

    class Meta:
        unique_together = ('group', 'swimmer')
        ordering = ['role', 'swimmer__last_name']

    def __str__(self):
        return f'{self.swimmer} → {self.group} ({self.get_role_display()})'

    def is_trainer(self):
        return self.role == self.ROLE_TRAINER
