from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

from swimmers.models import Swimmer


class UserProfile(models.Model):
    ROLE_ADMIN = 'admin'
    ROLE_TRAINER = 'trainer'
    ROLE_SWIMMER = 'swimmer'
    ROLE_CHOICES = [
        (ROLE_ADMIN, 'Administrator'),
        (ROLE_TRAINER, 'Trainer'),
        (ROLE_SWIMMER, 'Swimmer'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_SWIMMER)
    avatar = models.ImageField(upload_to='avatars/', null=True, blank=True)
    bio = models.TextField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.user.get_full_name() or self.user.username} ({self.get_role_display()})'

    @property
    def is_admin(self):
        return self.role == self.ROLE_ADMIN or self.user.is_superuser

    @property
    def is_trainer(self):
        return self.role in (self.ROLE_ADMIN, self.ROLE_TRAINER) or self.user.is_superuser

    @property
    def display_name(self):
        return self.user.get_full_name() or self.user.username

    @property
    def linked_swimmer(self):
        """Return linked Swimmer record if exists."""
        try:
            return self.user.swimmer
        except Exception:
            return None


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    if hasattr(instance, 'profile'):
        instance.profile.save()


@receiver(post_save, sender=UserProfile)
def update_user_profile(sender, instance, **kwargs):
    if instance.user is not None:
        person = Swimmer.objects.filter(user=instance.user).first()
        if person is None:
            return
        person.first_name = instance.user.first_name
        person.last_name = instance.user.last_name
        # TODO verified email change
        person.phone = instance.phone
        person.save()
