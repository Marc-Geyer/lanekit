from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import User
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Submit, Row, Column, Field
from .models import UserProfile

# Form errors cannot use tr(request, ...); keep the text German like the other form labels.
EMAIL_IN_USE_MSG = 'Diese E-Mail-Adresse wird bereits von einem anderen Konto verwendet.'


class StyledAuthForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Field('username', css_class='form-control'),
            Field('password', css_class='form-control'),
            Submit('submit', 'Anmelden', css_class='btn btn-primary w-100 mt-3'),
        )


class RegisterForm(UserCreationForm):
    first_name = forms.CharField(max_length=50, required=True)
    last_name = forms.CharField(max_length=50, required=True)
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'password1', 'password2')

    def clean_email(self):
        email = self.cleaned_data['email'].strip()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(EMAIL_IN_USE_MSG, code='email_in_use')
        return email

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Row(Column('first_name'), Column('last_name')),
            Field('username'),
            Field('email'),
            Field('password1'),
            Field('password2'),
            Submit('submit', 'Registrieren', css_class='btn btn-primary w-100 mt-3'),
        )


class UserProfileForm(forms.ModelForm):
    first_name = forms.CharField(max_length=50)
    last_name = forms.CharField(max_length=50)
    email = forms.EmailField()

    class Meta:
        model = UserProfile
        fields = ('role', 'phone', 'bio', 'avatar')
        widgets = {'bio': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        # Only admins may change the role – otherwise any user could promote themselves.
        can_edit_role = kwargs.pop('can_edit_role', False)
        # Name and phone sync to the person record; whoever may not edit that record directly
        # (swimmers, assistants) changes it through a proposal instead.
        lock_person_fields = kwargs.pop('lock_person_fields', False)
        super().__init__(*args, **kwargs)
        self._user = user
        if not can_edit_role:
            self.fields['role'].disabled = True   # disabled fields ignore POSTed values
        if lock_person_fields:
            for name in ('first_name', 'last_name', 'phone'):
                self.fields[name].disabled = True
        if user:
            self.fields['first_name'].initial = user.first_name
            self.fields['last_name'].initial = user.last_name
            self.fields['email'].initial = user.email
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Row(Column('first_name'), Column('last_name')),
            Field('email'),
            Row(Column('role'), Column('phone')),
            Field('bio'),
            Field('avatar'),
            Submit('submit', 'Speichern', css_class='btn btn-primary'),
        )

    def clean_email(self):
        email = self.cleaned_data['email'].strip()
        others = User.objects.filter(email__iexact=email)
        if self._user is not None:
            others = others.exclude(pk=self._user.pk)
        if others.exists():
            raise forms.ValidationError(EMAIL_IN_USE_MSG, code='email_in_use')
        return email

    def email_changed(self):
        """True if the submitted e-mail differs from the account's current one."""
        return (
            self._user is not None
            and self.cleaned_data['email'].lower() != (self._user.email or '').lower()
        )

    def save_user_fields(self, user):
        """Save the name fields. The e-mail is deliberately NOT written here: changes go
        through verification (own account) or apply_email_change() (admin), which also
        keeps the linked person's e-mail in sync."""
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        user.save()
