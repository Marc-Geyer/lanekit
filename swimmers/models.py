from django.db import models
from django.contrib.auth.models import User



class SwimmerManager(models.Manager):
    def get_queryset(self):
        from groups.models import GroupMembership
        return super().get_queryset().annotate(
            is_trainer=models.Exists(
                GroupMembership.objects.filter(
                    swimmer_id=models.OuterRef("id"),
                    role=GroupMembership.ROLE_TRAINER,
                )
            )
        )

class Swimmer(models.Model):
    """A person who participates in training sessions.
    May be linked to a User account, or exist as a standalone contact record."""

    objects = SwimmerManager()

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


    @property
    def age(self):
        """Age in full years, or None when no birthday is known."""
        if not self.date_of_birth:
            return None
        from datetime import date
        today = date.today()
        dob = self.date_of_birth
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


class PersonChangeRequest(models.Model):
    """A swimmer's proposal to change their own person record.

    Swimmers never edit their record directly; a trainer of one of the person's groups
    (or an admin) accepts or rejects the proposal.  ``changes`` maps field name → proposed
    value (dates as ISO strings); only fields that actually differ are stored.
    """

    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_REJECTED, 'Rejected'),
    ]

    swimmer = models.ForeignKey(Swimmer, on_delete=models.CASCADE, related_name='change_requests')
    proposed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    changes = models.JSONField(default=dict)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.swimmer} – {self.status}'
