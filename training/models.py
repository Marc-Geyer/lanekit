import uuid
from django.db import models
from django.contrib.auth.models import User
from groups.models import Group
from swimmers.models import Swimmer


WEEKDAYS = [
    (0, 'Montag'), (1, 'Dienstag'), (2, 'Mittwoch'),
    (3, 'Donnerstag'), (4, 'Freitag'), (5, 'Samstag'), (6, 'Sonntag'),
]

class Location(models.Model):
    TYPE_50M = '50m_Pool'
    TYPE_25M = '25m_Pool'
    TYPE_ATHLETIC = 'athletic'
    TYPE_OTHER = 'other'

    TYPE_CHOICES = [
        (TYPE_50M, '50m Schwimmbecken'),
        (TYPE_25M, '25m Schwimmbecken'),
        (TYPE_ATHLETIC, 'Sport Halle'),
        (TYPE_OTHER, 'other'),
    ]
    name = models.CharField()
    type = models.CharField(choices=TYPE_CHOICES, max_length=10)
    city = models.CharField(max_length=200)
    postal_code = models.CharField(max_length=5, blank=True)
    street_address = models.TextField()

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def address(self):
        return f"{self.street_address}, {self.postal_code} {self.city}"

class RecurringSession(models.Model):
    """A weekly recurring training slot for a group."""
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name='recurring_sessions')
    day_of_week = models.IntegerField(choices=WEEKDAYS)
    start_time = models.TimeField()
    end_time = models.TimeField()
    location = models.ForeignKey(Location, null=True, on_delete=models.SET_NULL, related_name='recurring_sessions')
    valid_from = models.DateField()
    valid_until = models.DateField(null=True, blank=True)
    active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        ordering = ['day_of_week', 'start_time']

    def __str__(self):
        return f'{self.group} – {self.get_day_of_week_display()} {self.start_time:%H:%M}'

    @property
    def duration_minutes(self):
        from datetime import datetime, date
        start = datetime.combine(date.today(), self.start_time)
        end = datetime.combine(date.today(), self.end_time)
        return int((end - start).total_seconds() / 60)


class SessionException(models.Model):
    """A holiday or one-off cancellation that cancels one or more recurring sessions."""
    date = models.DateField()
    affected_sessions = models.ManyToManyField(
        RecurringSession, related_name='exceptions', blank=True,
        help_text='Leave empty to affect ALL sessions on this date.'
    )
    reason = models.CharField(max_length=200)
    affects_all = models.BooleanField(
        default=False,
        help_text='If true, cancels every recurring session on this date regardless of selection.'
    )
    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date']

    def __str__(self):
        return f'{self.date} – {self.reason}'


class SessionInstance(models.Model):
    """An actual occurrence of a recurring session (created when a trainer opens it)."""
    recurring_session = models.ForeignKey(
        RecurringSession, on_delete=models.CASCADE, related_name='instances'
    )
    date = models.DateField()
    trainer_notes = models.TextField(blank=True, help_text='General notes for this session.')
    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('recurring_session', 'date')
        ordering = ['-date']

    def __str__(self):
        return f'{self.recurring_session} on {self.date}'

    @property
    def group(self):
        return self.recurring_session.group


class TrainingPlanEntry(models.Model):
    """A single exercise / block in the training plan for a session instance."""
    CATEGORY_WARMUP = 'warmup'
    CATEGORY_MAIN = 'main'
    CATEGORY_COOL = 'cooldown'
    CATEGORY_CHOICES = [
        (CATEGORY_WARMUP, 'Aufwärmen'),
        (CATEGORY_MAIN, 'Hauptteil'),
        (CATEGORY_COOL, 'Abkühlen'),
    ]

    session = models.ForeignKey(SessionInstance, on_delete=models.CASCADE, related_name='plan_entries')
    order = models.PositiveSmallIntegerField(default=0)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default=CATEGORY_MAIN)
    description = models.TextField()
    distance = models.CharField(max_length=50, blank=True, help_text='e.g. 4×50m')
    intensity = models.CharField(max_length=50, blank=True, help_text='e.g. GA I, Sprint')
    rest_seconds = models.PositiveSmallIntegerField(null=True, blank=True, help_text='Rest in seconds')
    photo = models.ImageField(
        upload_to='training_plans/%Y/%m/', blank=True, null=True,
        help_text='Photo of a hand-written plan, e.g. taken poolside.'
    )

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f'[{self.get_category_display()}] {self.description[:40]}'

    def to_dict(self):
        return {
            'id': self.pk,
            'order': self.order,
            'category': self.category,
            'description': self.description,
            'distance': self.distance,
            'intensity': self.intensity,
            'rest_seconds': self.rest_seconds,
            'photo_url': self.photo.url if self.photo else None,
        }


class ExcuseToken(models.Model):
    """A one-time token that allows a swimmer to self-excuse from a specific session date."""
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    swimmer = models.ForeignKey(Swimmer, on_delete=models.CASCADE, related_name='excuse_tokens')
    recurring_session = models.ForeignKey(RecurringSession, on_delete=models.CASCADE)
    date = models.DateField()
    reason = models.TextField(blank=True)
    used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('swimmer', 'recurring_session', 'date')

    def __str__(self):
        return f'Excuse: {self.swimmer} – {self.date} ({"used" if self.used else "pending"})'

    def get_excuse_url(self):
        from django.urls import reverse
        return reverse('use_excuse_token', args=[str(self.token)])


class Attendance(models.Model):
    """Tracks whether a swimmer attended a specific session instance."""
    STATUS_PRESENT = 'present'
    STATUS_ABSENT = 'absent'
    STATUS_EXCUSED = 'excused'
    STATUS_UNKNOWN = 'unknown'
    STATUS_CHOICES = [
        (STATUS_PRESENT, 'Anwesend'),
        (STATUS_ABSENT, 'Abwesend'),
        (STATUS_EXCUSED, 'Entschuldigt'),
        (STATUS_UNKNOWN, 'Unbekannt'),
    ]

    session = models.ForeignKey(SessionInstance, on_delete=models.CASCADE, related_name='attendances')
    swimmer = models.ForeignKey(Swimmer, on_delete=models.CASCADE, related_name='attendances')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_UNKNOWN)
    excuse_token = models.OneToOneField(
        ExcuseToken, null=True, blank=True, on_delete=models.SET_NULL
    )
    marked_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    marked_at = models.DateTimeField(auto_now=True)
    notes = models.CharField(max_length=200, blank=True)

    class Meta:
        unique_together = ('session', 'swimmer')
        ordering = ['swimmer__last_name', 'swimmer__first_name']

    def __str__(self):
        return f'{self.swimmer} – {self.session.date}: {self.get_status_display()}'

    def to_dict(self):
        return {
            'swimmer_id': self.swimmer_id,
            'swimmer_name': self.swimmer.full_name,
            'swimmer_initials': self.swimmer.initials,
            'status': self.status,
            'notes': self.notes,
            'marked_by': self.marked_by.get_full_name() if self.marked_by else None,
        }
