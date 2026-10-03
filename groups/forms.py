from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Submit, Row, Column, Field
from swimmers.forms import SwimmerForm
from .models import Group, GroupMembership


class GroupForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ('name', 'description', 'color', 'active')
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'color': forms.TextInput(attrs={'type': 'color'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Row(Column('name'), Column('color')),
            Field('description'),
            Field('active'),
            Submit('submit', 'Speichern', css_class='btn btn-primary'),
        )


class GroupMemberCreateForm(SwimmerForm):
    """Creates a new Swimmer that is linked to a fixed group (set by the view).
    Only the role within that group can be chosen."""

    role = forms.ChoiceField(
        choices=GroupMembership.ROLE_CHOICES,
        initial=GroupMembership.ROLE_SWIMMER,
        label='Rolle',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper.layout = Layout(
            Row(Column('first_name'), Column('last_name')),
            Row(Column('email'), Column('phone')),
            Field('date_of_birth'),
            Row(Column('emergency_contact_name'), Column('emergency_contact_phone')),
            Field('notes'),
            Field('role'),
            Submit('submit', 'Speichern', css_class='btn btn-primary mt-2'),
        )
