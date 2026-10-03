"""
European date / time handling for all forms.

Why not <input type="date">?
  Browsers only accept ISO values (yyyy-mm-dd) in the `value` attribute and
  display them in the *browser's* locale.  Django renders the value in the
  active locale (dd.mm.yyyy), which the browser silently discards – so
  existing data showed up as an empty field.  Text inputs with an explicit
  format render exactly what is stored, in the format we choose.
"""
from django import forms

DATE_FORMAT = '%d.%m.%Y'
TIME_FORMAT = '%H:%M'
DATETIME_FORMAT = '%d.%m.%Y %H:%M'

DATE_INPUT_FORMATS = [DATE_FORMAT, '%d.%m.%y', '%Y-%m-%d']
TIME_INPUT_FORMATS = [TIME_FORMAT, '%H:%M:%S', '%H.%M']
DATETIME_INPUT_FORMATS = [
    DATETIME_FORMAT, '%d.%m.%Y %H:%M:%S', '%d.%m.%y %H:%M',
    DATE_FORMAT, '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M',
]


class EuropeanDateInput(forms.DateInput):
    def __init__(self, attrs=None):
        defaults = {
            'placeholder': 'TT.MM.JJJJ', 'inputmode': 'numeric',
            'autocomplete': 'off', 'maxlength': '10', 'data-eu-input': 'date',
        }
        super().__init__({**defaults, **(attrs or {})}, format=DATE_FORMAT)


class EuropeanTimeInput(forms.TimeInput):
    def __init__(self, attrs=None):
        defaults = {
            'placeholder': 'HH:MM', 'inputmode': 'numeric',
            'autocomplete': 'off', 'maxlength': '5', 'data-eu-input': 'time',
        }
        super().__init__({**defaults, **(attrs or {})}, format=TIME_FORMAT)


class EuropeanDateTimeInput(forms.DateTimeInput):
    def __init__(self, attrs=None):
        defaults = {
            'placeholder': 'TT.MM.JJJJ HH:MM', 'inputmode': 'numeric',
            'autocomplete': 'off', 'maxlength': '16',
            'data-eu-input': 'datetime',
        }
        super().__init__({**defaults, **(attrs or {})}, format=DATETIME_FORMAT)


class EuropeanFormatsMixin:
    """Put first in a form's bases.  Every DateField / TimeField / DateTimeField
    gets a text widget in European format plus matching input_formats, so
    initial and saved values are always displayed and parsed consistently."""

    _WIDGETS = (
        (forms.DateTimeField, EuropeanDateTimeInput, DATETIME_INPUT_FORMATS),
        (forms.DateField, EuropeanDateInput, DATE_INPUT_FORMATS),
        (forms.TimeField, EuropeanTimeInput, TIME_INPUT_FORMATS),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            for field_cls, widget_cls, formats in self._WIDGETS:
                if isinstance(field, field_cls):
                    field.input_formats = formats
                    if not isinstance(field.widget, widget_cls):
                        attrs = {k: v for k, v in field.widget.attrs.items()
                                 if k != 'type'}
                        field.widget = widget_cls(attrs)
                        field.widget.is_required = field.required
                    break
