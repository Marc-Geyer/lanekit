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
        fields = ('date', 'reason', 'affects_all', 'affected_sessions')
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'affected_sessions': forms.CheckboxSelectMultiple(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Row(Column('date'), Column('reason')),
            Field('affects_all'),
            Field('affected_sessions'),
            Submit('submit', 'Ausnahme speichern', css_class='btn btn-danger'),
        )


class TrainingPlanEntryForm(forms.ModelForm):
    class Meta:
        model = TrainingPlanEntry
        fields = ('category', 'description', 'distance', 'intensity', 'rest_seconds')
        widgets = {
            'description': forms.Textarea(attrs={'rows': 2}),
        }
