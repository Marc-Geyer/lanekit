from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Submit, Row, Column, Field, HTML
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


class SwimmerCreateForm(SwimmerForm):
    """Extends SwimmerForm with optional group assignment fields.
    The group/group_role fields are not model fields; they are handled
    explicitly in swimmer_create_view after the Swimmer is saved."""

    group = forms.ModelChoiceField(
        queryset=None,          # set in __init__ to avoid import-time query
        required=False,
        label='Gruppe',
        empty_label='— keine Gruppe —',
    )
    group_role = forms.ChoiceField(
        choices=[],             # set in __init__
        required=False,
        label='Rolle',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        from groups.models import Group, GroupMembership
        self.fields['group'].queryset = Group.objects.filter(active=True).order_by('name')
        self.fields['group_role'].choices = GroupMembership.ROLE_CHOICES
        self.fields['group_role'].initial = GroupMembership.ROLE_SWIMMER

        self.helper.layout = Layout(
            Row(Column('first_name'), Column('last_name')),
            Row(Column('email'), Column('phone')),
            Field('date_of_birth'),
            Row(Column('emergency_contact_name'), Column('emergency_contact_phone')),
            Field('notes'),
            Field('active'),
            HTML(
                '<hr class="my-4">'
                '<p class="fw-semibold mb-3" style="font-family:\'Syne\',sans-serif">'
                '<i class="bi bi-people-fill text-primary me-2"></i>'
                'Gruppe zuweisen <span class="fw-normal text-muted">(optional)</span>'
                '</p>'
            ),
            Row(Column('group'), Column('group_role')),
            Submit('submit', 'Speichern', css_class='btn btn-primary mt-2'),
        )