from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Submit, Row, Column, Field
from .models import RecurringSession, SessionException, TrainingPlanEntry


class RecurringSessionForm(forms.ModelForm):
    class Meta:
        model = RecurringSession
        fields = ('day_of_week', 'start_time', 'end_time', 'location',
                  'valid_from', 'valid_until', 'notes', 'active')
        widgets = {
            'start_time': forms.TimeInput(attrs={'type': 'time'}),
            'end_time': forms.TimeInput(attrs={'type': 'time'}),
            'valid_from': forms.DateInput(attrs={'type': 'date'}),
            'valid_until': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Row(Column('day_of_week'), Column('location')),
            Row(Column('start_time'), Column('end_time')),
            Row(Column('valid_from'), Column('valid_until')),
            Field('notes'),
            Field('active'),
            Submit('submit', 'Speichern', css_class='btn btn-primary'),
        )


class SessionExceptionForm(forms.ModelForm):
    class Meta:
        model = SessionException
        fields = ('date', 'end_date', 'reason', 'affects_all', 'affected_sessions')
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
            'affected_sessions': forms.CheckboxSelectMultiple(),
        }

    def __init__(self, *args, request=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['end_date'].required = False
        self._request = request
        if request is not None:
            from translations.helpers import tr
            self.fields['date'].label = tr(request, 'exception_date_label')
            self.fields['date'].help_text = ''
            self.fields['end_date'].label = tr(request, 'exception_end_date_label')
            self.fields['end_date'].help_text = tr(request, 'exception_end_date_hint')
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Row(Column('date'), Column('end_date'), Column('reason')),
            Field('affects_all'),
            Field('affected_sessions'),
            Submit('submit', 'Ausnahme speichern', css_class='btn btn-danger'),
        )

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get('date')
        end = cleaned_data.get('end_date')
        if start and end and end < start:
            if self._request is not None:
                from translations.helpers import tr
                error = tr(self._request, 'exception_end_date_error')
            else:
                error = 'End date must be on or after the start date.'
            self.add_error('end_date', error)
        return cleaned_data


class TrainingPlanEntryForm(forms.ModelForm):
    class Meta:
        model = TrainingPlanEntry
        fields = ('category', 'description', 'distance', 'intensity', 'rest_seconds')
        widgets = {
            'description': forms.Textarea(attrs={'rows': 2}),
        }
