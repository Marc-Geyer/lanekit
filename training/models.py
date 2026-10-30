import uuid
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.contrib.auth.models import User
from groups.models import Group
from swimmers.models import Swimmer


WEEKDAYS = [
    (0, 'Montag'), (1, 'Dienstag'), (2, 'Mittwoch'),
    (3, 'Donnerstag'), (4, 'Freitag'), (5, 'Samstag'), (6, 'Sonntag'),
]

def _check_lanes_fit(lanes, location):
    """Raise if `lanes` exceeds the lane count of `location` (both optional)."""
    if lanes and location is not None and location.lanes and lanes > location.lanes:
        raise ValidationError({
            'lanes': f'{location.name} has only {location.lanes} lanes '
                     f'(requested: {lanes}).'
        })


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
    lanes = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1)],
        help_text='Number of lanes available. Leave empty for non-pool locations.'
    )

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def clean(self):
        if self.pk and self.lanes and self.recurring_sessions.filter(lanes__gt=self.lanes).exists():
            raise ValidationError({
                'lanes': 'Recurring sessions at this location already use more lanes.'
            })

    def save(self, *args, **kwargs):
        previous = None
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).values_list('lanes', flat=True).first()
        super().save(*args, **kwargs)
        # Lane count added retroactively: sessions that never specified one inherit it.
        if self.lanes is not None and previous is None:
            for rec in self.recurring_sessions.filter(lanes__isnull=True):
                rec.lanes = self.lanes
                rec.save()   # RecurringSession.save() backfills its instances

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
    lanes = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1)],
        help_text='Lanes used by this slot. Copied to every new session; '
                  'individual sessions can be corrected afterwards.'
    )
    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        ordering = ['day_of_week', 'start_time']

    def clean(self):
        _check_lanes_fit(self.lanes, self.location)

    def save(self, *args, **kwargs):
        previous = None
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).values_list('lanes', flat=True).first()
        elif self.lanes is None and self.location is not None:
            self.lanes = self.location.lanes          # new slot: default from the location
        super().save(*args, **kwargs)
        # Lane count added retroactively: existing sessions without one inherit it.
        # A later change (e.g. 6 -> 4) deliberately leaves past sessions untouched.
        if self.lanes is not None and previous is None:
            self.instances.filter(lanes__isnull=True).update(lanes=self.lanes)

    def __str__(self):
        return f'{self.group} – {self.get_day_of_week_display()} {self.start_time:%H:%M}'

    @property
    def duration_minutes(self):
        from datetime import datetime, date
        start = datetime.combine(date.today(), self.start_time)
        end = datetime.combine(date.today(), self.end_time)
        return int((end - start).total_seconds() / 60)


class SessionException(models.Model):
    """A holiday or cancellation that cancels one or more recurring sessions
    on a single date or across an inclusive date range."""
    date = models.DateField(help_text='First (or only) day of the exception.')
    end_date = models.DateField(
        null=True, blank=True,
        help_text='Optional last day of the exception (inclusive). '
                   'Leave empty for a single-day exception.'
    )
    affected_sessions = models.ManyToManyField(
        RecurringSession, related_name='exceptions', blank=True,
        help_text='Leave empty to affect ALL sessions on this date / date range.'
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

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.end_date and self.end_date < self.date:
            raise ValidationError({'end_date': 'End date must be on or after the start date.'})

    @property
    def effective_end_date(self):
        """The last affected date – falls back to `date` for single-day exceptions."""
        return self.end_date or self.date

    @property
    def is_range(self):
        return bool(self.end_date and self.end_date != self.date)

    def covers(self, day):
        """Return True if `day` falls within this exception's date range (inclusive)."""
        return self.date <= day <= self.effective_end_date

    def date_range(self):
        """Yield every date covered by this exception, inclusive."""
        from datetime import timedelta
        current = self.date
        end = self.effective_end_date
        while current <= end:
            yield current
            current += timedelta(days=1)

    def __str__(self):
        if self.is_range:
            return f'{self.date} – {self.end_date} – {self.reason}'
        return f'{self.date} – {self.reason}'


class SessionInstance(models.Model):
    """An actual occurrence of a recurring session (created when a trainer opens it)."""
    recurring_session = models.ForeignKey(
        RecurringSession, on_delete=models.CASCADE, related_name='instances'
    )
    date = models.DateField()
    trainer_notes = models.TextField(blank=True, help_text='General notes for this session.')
    lanes = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1)],
        help_text='Lanes actually used. Defaults to the recurring slot at creation; '
                  'only set manually to correct it.'
    )
    is_optional = models.BooleanField(
        default=False,
        help_text='Optional session (few swimmers expected); excluded from statistics by default.'
    )
    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('recurring_session', 'date')
        ordering = ['-date']

    def clean(self):
        _check_lanes_fit(self.lanes, self.recurring_session.location)

    def save(self, *args, **kwargs):
        if self._state.adding and self.lanes is None:
            self.lanes = self.recurring_session.lanes
        super().save(*args, **kwargs)

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
    checked = models.BooleanField(
        default = False, help_text = 'Ticked off while executing the session; does not affect ordering.'
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
            'checked': self.checked,
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


class PerformanceResult(models.Model):
    """A single timed swim of one swimmer (training time or, later, competition time).

    Times are stored in hundredths of a second so they stay exact and sortable.
    ``is_official`` is False for everything recorded in training; it exists so
    competition results can be added later without a schema change.
    """
    STROKE_FREE = 'free'
    STROKE_BACK = 'back'
    STROKE_BREAST = 'breast'
    STROKE_FLY = 'fly'
    STROKE_MEDLEY = 'medley'
    STROKE_CHOICES = [
        (STROKE_FREE, 'Freistil'),
        (STROKE_BACK, 'Rücken'),
        (STROKE_BREAST, 'Brust'),
        (STROKE_FLY, 'Schmetterling'),
        (STROKE_MEDLEY, 'Lagen'),
    ]
    POOL_CHOICES = [(25, '25 m'), (50, '50 m')]
    MAX_TIME_CS = 3 * 3600 * 100     # 3 h – anything above is certainly a typo
    MAX_DISTANCE_M = 10000

    swimmer = models.ForeignKey(Swimmer, on_delete=models.CASCADE, related_name='results')
    session = models.ForeignKey(
        SessionInstance, null=True, blank=True, on_delete=models.SET_NULL, related_name='results',
        help_text='Training session in which the time was swum (empty for e.g. competitions).'
    )
    date = models.DateField(help_text='Day the performance was swum.')
    location = models.ForeignKey(
        Location, null=True, blank=True, on_delete=models.SET_NULL, related_name='results'
    )
    stroke = models.CharField(max_length=10, choices=STROKE_CHOICES)
    distance_m = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    time_cs = models.PositiveIntegerField(
        validators=[MinValueValidator(1)], help_text='Swim time in hundredths of a second.'
    )
    pool_length = models.PositiveSmallIntegerField(
        null=True, blank=True, choices=POOL_CHOICES,
        help_text='25 or 50 m course. Taken from the location when empty; '
                  'times of different course lengths are not directly comparable.'
    )
    is_official = models.BooleanField(
        default=False, help_text='Official (competition) time. False for all training times.'
    )
    notes = models.CharField(max_length=200, blank=True)
    recorded_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-id']
        indexes = [models.Index(fields=['swimmer', 'date'])]

    def __str__(self):
        return f'{self.swimmer} – {self.distance_m} m {self.stroke}: {self.time_cs / 100:.2f} s ({self.date})'

    @staticmethod
    def pool_length_for(location):
        """Course length implied by a location (None for non-pool / unknown)."""
        if location is None:
            return None
        return {Location.TYPE_25M: 25, Location.TYPE_50M: 50}.get(location.type)

    def clean(self):
        if self.time_cs is not None and self.time_cs > self.MAX_TIME_CS:
            raise ValidationError({'time_cs': 'Time is implausibly long.'})
        if self.distance_m is not None and self.distance_m > self.MAX_DISTANCE_M:
            raise ValidationError({'distance_m': 'Distance is implausibly long.'})

    def save(self, *args, **kwargs):
        if self.pool_length is None:
            self.pool_length = self.pool_length_for(self.location)
        super().save(*args, **kwargs)
