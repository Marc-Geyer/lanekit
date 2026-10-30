"""Form widgets that always show European formats (dd.mm.yyyy, 24 h HH:MM).

A native <input type="date|time"> needs ISO values in its value attribute and shows
them in the *browser's* locale (often US). Django renders the value in the format
below, so with type="date" a dd.mm.yyyy value is silently ignored and the field stays
empty. These widgets are therefore plain text inputs in the wanted format; the
flatpickr picker is attached in static/js/datepickers.js.
"""
from django import forms

DATE_FORMAT = '%d.%m.%Y'
TIME_FORMAT = '%H:%M'


class EuDateInput(forms.DateInput):
    def __init__(self, attrs=None):
        base = {'data-datepicker': '1', 'placeholder': 'TT.MM.JJJJ',
                'autocomplete': 'off', 'inputmode': 'numeric'}
        base.update(attrs or {})
        super().__init__(attrs=base, format=DATE_FORMAT)


class EuTimeInput(forms.TimeInput):
    def __init__(self, attrs=None):
        base = {'data-timepicker': '1', 'placeholder': 'HH:MM',
                'autocomplete': 'off', 'inputmode': 'numeric'}
        base.update(attrs or {})
        super().__init__(attrs=base, format=TIME_FORMAT)
