from datetime import date, time

from django.test import SimpleTestCase

from swimmers.forms import SwimmerForm
from swimmers.models import Swimmer
from training.forms import RecurringSessionForm, SessionExceptionForm
from training.models import RecurringSession, SessionException


class EuropeanFormatTests(SimpleTestCase):
    def test_saved_values_are_rendered(self):
        html = str(SwimmerForm(instance=Swimmer(date_of_birth=date(2010, 3, 7)))['date_of_birth'])
        self.assertIn('value="07.03.2010"', html)

        rs = RecurringSession(start_time=time(19, 0), end_time=time(20, 45),
                              valid_from=date(2026, 1, 1), valid_until=date(2026, 12, 31))
        form = RecurringSessionForm(instance=rs)
        self.assertIn('value="19:00"', str(form['start_time']))
        self.assertIn('value="20:45"', str(form['end_time']))
        self.assertIn('value="01.01.2026"', str(form['valid_from']))
        self.assertIn('value="31.12.2026"', str(form['valid_until']))

        form = SessionExceptionForm(instance=SessionException(date=date(2026, 10, 3)))
        self.assertIn('value="03.10.2026"', str(form['date']))

    def test_no_native_date_widgets(self):
        for form in (SwimmerForm(), RecurringSessionForm(), SessionExceptionForm()):
            for name, field in form.fields.items():
                if 'date' in name or 'time' in name or name.startswith('valid_'):
                    self.assertEqual(field.widget.input_type, 'text', name)

    def test_european_input_is_parsed(self):
        form = SwimmerForm(data={'first_name': 'A', 'last_name': 'B',
                                 'date_of_birth': '07.03.2010', 'active': 'on'})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['date_of_birth'], date(2010, 3, 7))

        form = RecurringSessionForm(data={
            'day_of_week': 2, 'start_time': '19:00', 'end_time': '20:45',
            'valid_from': '01.01.2026', 'location': '', 'active': 'on'})
        form.is_valid()
        self.assertEqual(form.cleaned_data['start_time'], time(19, 0))
        self.assertEqual(form.cleaned_data['valid_from'], date(2026, 1, 1))
