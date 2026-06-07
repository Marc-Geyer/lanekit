from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Submit, Row, Column, Field
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


class MembershipForm(forms.ModelForm):
    class Meta:
        model = GroupMembership
        fields = ('swimmer', 'role')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from swimmers.models import Swimmer
        self.fields['swimmer'].queryset = Swimmer.objects.filter(active=True)
