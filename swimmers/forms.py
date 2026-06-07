from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Submit, Row, Column, Field
from .models import Swimmer


class SwimmerForm(forms.ModelForm):
    class Meta:
        model = Swimmer
        fields = (
            'first_name', 'last_name', 'email', 'phone',
            'date_of_birth', 'emergency_contact_name',
            'emergency_contact_phone', 'notes', 'active',
        )
        widgets = {
            'date_of_birth': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Row(Column('first_name'), Column('last_name')),
            Row(Column('email'), Column('phone')),
            Field('date_of_birth'),
            Row(Column('emergency_contact_name'), Column('emergency_contact_phone')),
            Field('notes'),
            Field('active'),
            Submit('submit', 'Speichern', css_class='btn btn-primary'),
        )
