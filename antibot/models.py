from django.db import models
from django.utils import timezone


class BlockedIP(models.Model):
    """An IP address temporarily blocked after tripping a honeypot trap.

    Rows are created by antibot.views.honeypot_trap_view and read by
    antibot.middleware.HoneypotBlockMiddleware on every request. Expired rows
    are left in place as a hit log (and simply stop matching queries) rather
    than deleted, so an admin can see repeat offenders over time; prune old
    rows manually or with a periodic task if the table grows large.
    """
    ip_address = models.GenericIPAddressField(db_index=True)
    reason = models.CharField(max_length=200, default='honeypot')
    hit_path = models.CharField(max_length=500, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    blocked_until = models.DateTimeField(db_index=True)
    hit_count = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.ip_address} blocked until {self.blocked_until}'

    @property
    def is_active(self):
        return self.blocked_until > timezone.now()
