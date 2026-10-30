from datetime import date, time

from django.test import TestCase

from groups.models import Group
from .forms import RecurringSessionForm, SessionExceptionForm
from .models import RecurringSession, SessionException


class EuropeanFormatTests(TestCase):
    def test_edit_form_shows_saved_values_european(self):
        rs = RecurringSession.objects.create(
            group=Group.objects.create(name='G'), day_of_week=0, start_time=time(18, 30),
            end_time=time(20, 0), valid_from=date(2026, 1, 5), valid_until=date(2026, 12, 31))
        form = RecurringSessionForm(instance=rs)
        self.assertIn('value="05.01.2026"', str(form['valid_from']))
        self.assertIn('value="31.12.2026"', str(form['valid_until']))
        self.assertIn('value="18:30"', str(form['start_time']))
        self.assertIn('value="20:00"', str(form['end_time']))
        for f in ('valid_from', 'start_time'):
            self.assertNotIn('type="date"', str(form[f]))
            self.assertNotIn('type="time"', str(form[f]))

    def test_exception_form_shows_saved_date(self):
        ex = SessionException.objects.create(date=date(2026, 12, 24), reason='x', affects_all=True)
        self.assertIn('value="24.12.2026"', str(SessionExceptionForm(instance=ex)['date']))
