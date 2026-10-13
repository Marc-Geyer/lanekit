import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core import signing
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q, IntegerField, Value, When, Case
from django.http import Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.views.decorators.http import require_POST

from swimmers.models import Swimmer
from translations.helpers import tr
from .forms import StyledAuthForm, RegisterForm, UserProfileForm
from .models import UserProfile

logger = logging.getLogger(__name__)

# E-mail change links are signed (no DB state needed) and valid for 3 days.
EMAIL_CHANGE_SALT = 'lanekit.accounts.email-change'
EMAIL_CHANGE_MAX_AGE = 60 * 60 * 24 * 3


def login_view(request):
    if request.user.is_authenticated:
        return redirect('calendar')
    form = StyledAuthForm(data=request.POST or None)
    if request.method == 'POST' and form.is_valid():
        login(request, form.get_user())
        # Check if User has trainer status and assign it
        user = User.objects.get(pk=form.get_user().pk)
        check_trainer_status(user)
        return redirect(request.GET.get('next', 'calendar'))
    return render(request, 'accounts/login.html', {'form': form})

def check_trainer_status(user: User):
    # check if user is trainer in some group
    swimmer = Swimmer.objects.filter(user=user)
    if not swimmer.exists():
        return
    if not swimmer.values('is_trainer')[0]:
        return
    # Don't overwrite admin status
    if not user.profile.role == UserProfile.ROLE_ADMIN:
        user.profile.role == UserProfile.ROLE_TRAINER
        user.profile.save()

def logout_view(request):
    logout(request)
    return redirect('calendar')


def register_view(request):
    form = RegisterForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        email = form.cleaned_data['email']

        # Only people the club already knows (and who have no account yet) may register.
        if not Swimmer.objects.filter(email__iexact=email, user__isnull=True).exists():
            messages.error(request, tr(request, 'msg_activ_failed'))
            return redirect('calendar')

        try:
            # User + mail in one transaction: if the mail cannot be sent, the account is
            # rolled back instead of staying behind inactive (which blocked the username).
            with transaction.atomic():
                user = form.save(commit=False)
                user.is_active = False
                user.save()
                send_verification_email(request, user, purpose='activate_account')
        except Exception:
            logger.exception('Could not send activation e-mail to %s', email)
            messages.error(request, tr(request, 'msg_mail_failed'))
            return render(request, 'accounts/register.html', {'form': form})

        return render(request, 'accounts/verification_sent.html')
    return render(request, 'accounts/register.html', {'form': form})


def send_verification_email(request, user, new_email=None, purpose='activate_account'):
    """
    Send a verification mail. Raises on delivery problems (callers handle that).

    purpose='activate_account' -> activation link to user.email
    purpose='email_verify'     -> confirmation link to new_email; the address is only
                                  changed once the link is opened (see verify_email_view)
    """
    if purpose == 'email_verify':
        if not new_email:
            raise ValueError('new_email is required for purpose="email_verify"')
        token = signing.dumps(
            {'u': user.pk, 'o': user.email, 'e': new_email},
            salt=EMAIL_CHANGE_SALT,
        )
        url_path = reverse('verify_email', kwargs={'token': token})
        subject = tr(request, 'email_verify_subject')
        message = tr(request, 'email_verify_body',
                     scheme=request.scheme, host=request.get_host(), url=url_path)
        recipient = new_email

    elif purpose == 'activate_account':
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        url_path = reverse('activate', kwargs={'uidb64': uid, 'token': token})
        subject = tr(request, 'activate_account')
        message = tr(request, 'activation_email',
                     scheme=request.scheme, host=request.get_host(), url=url_path)
        recipient = user.email

    else:
        raise Http404()

    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[recipient],
        fail_silently=False,
    )


def activate_view(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is not None and default_token_generator.check_token(user, token):
        if user.is_active:
            # Link was already used – never touch an active account.
            return redirect('login')

        person = (
            Swimmer.objects
            .filter(email__iexact=user.email, user__isnull=True)
            .annotate(
                score=Case(
                    When(first_name__iexact=user.first_name, then=Value(1)),
                    default=Value(0),
                    output_field=IntegerField(),
                )
            )
            .order_by("-score")
            .first()
        )

        if person is None:
            user.delete()
            messages.error(request, tr(request, 'msg_activ_failed'))
            return redirect('calendar')

        with transaction.atomic():
            user.is_active = True
            user.save()
            person.user = user
            person.save()

        login(request, user)
        check_trainer_status(user)
        messages.success(request, tr(request, 'msg_activ_successfull'))
        return redirect('calendar')
    return render(request, 'accounts/verification_failed.html', {'user': user})


def apply_email_change(user, new_email):
    """Set the account's e-mail and keep the linked person's e-mail in sync."""
    with transaction.atomic():
        user.email = new_email
        user.save(update_fields=['email'])
        # Fetch the person only after user.save(): its post_save signals also write the person.
        person = Swimmer.objects.filter(user=user).first()
        if person is not None:
            person.email = new_email
            person.save(update_fields=['email', 'updated_at'])


def _request_email_change(request, user, new_email):
    """Send the confirmation link to the *new* address. The account keeps its old
    address until the link is opened."""
    try:
        send_verification_email(request, user, new_email=new_email, purpose='email_verify')
    except Exception:
        logger.exception('Could not send e-mail change verification to %s', new_email)
        messages.error(request, tr(request, 'msg_mail_failed'))
        return False
    messages.success(request, tr(request, 'msg_email_verification_sent', email=new_email))
    return True


def verify_email_view(request, token):
    """Target of the link in the e-mail-change mail. No login needed (signed token)."""
    user = None
    try:
        data = signing.loads(token, salt=EMAIL_CHANGE_SALT, max_age=EMAIL_CHANGE_MAX_AGE)
        user = User.objects.get(pk=data['u'])
        old_email, new_email = data['o'], data['e']
    except (signing.BadSignature, KeyError, TypeError, User.DoesNotExist):
        user = None

    valid = (
        user is not None
        and user.is_active
        and (user.email or '') == old_email          # also makes the link single-use
        and not User.objects.filter(email__iexact=new_email).exclude(pk=user.pk).exists()
    )
    target = 'profile' if request.user.is_authenticated else 'login'
    if not valid:
        messages.error(request, tr(request, 'msg_email_link_invalid'))
        return redirect(target)

    apply_email_change(user, new_email)
    messages.success(request, tr(request, 'msg_email_changed'))
    return redirect(target)


@login_required
def profile_view(request):
    profile = request.user.profile
    form = UserProfileForm(
        request.POST or None, request.FILES or None,
        instance=profile, user=request.user,
        can_edit_role=request.user.profile.is_admin,
    )
    if request.method == 'POST' and form.is_valid():
        form.save_user_fields(request.user)      # names only – e-mail needs verification
        form.save()
        messages.success(request, tr(request, 'msg_profile_updated'))
        if form.email_changed():
            _request_email_change(request, request.user, form.cleaned_data['email'])
        return redirect('profile')
    return render(request, 'accounts/profile.html', {'form': form})


@login_required
def user_list_view(request):
    if not request.user.profile.is_admin:
        messages.error(request, tr(request, 'msg_no_permission'))
        return redirect('calendar')
    q = request.GET.get('q', '').split()
    users = User.objects.select_related('profile').order_by('last_name', 'first_name')
    if q:
        for a in q:
            users = users.filter(
                Q(first_name__icontains=a) | Q(last_name__icontains=a) |
                Q(username__icontains=a) | Q(email__icontains=a)
            )

    context = {
        'users': users,
        'q': ' '.join(q)
    }
    return render(request, 'accounts/user_list.html', context)


@login_required
def user_detail_view(request, pk):
    viewer_is_admin = request.user.profile.is_admin
    if not viewer_is_admin and request.user.pk != pk:
        messages.error(request, tr(request, 'msg_no_permission'))
        return redirect('calendar')
    target_user = get_object_or_404(User, pk=pk)
    profile = target_user.profile
    form = UserProfileForm(
        request.POST or None, request.FILES or None,
        instance=profile, user=target_user,
        can_edit_role=viewer_is_admin,
    )
    if request.method == 'POST' and form.is_valid():
        email_changed = form.email_changed()
        new_email = form.cleaned_data['email']
        form.save_user_fields(target_user)
        form.save()
        messages.success(request, tr(request, 'msg_user_updated'))
        if email_changed:
            if viewer_is_admin and request.user.pk != target_user.pk:
                # Admin edits someone else's account: applied directly, person stays in sync.
                apply_email_change(target_user, new_email)
            else:
                _request_email_change(request, target_user, new_email)
        return redirect('user_detail', pk=pk)

    context = {'target_user': target_user, 'form': form}
    if viewer_is_admin:
        context['linked_swimmer'] = Swimmer.objects.filter(user=target_user).first()
        context['unlinked_swimmers'] = (
            Swimmer.objects.filter(user__isnull=True).order_by('last_name', 'first_name')
        )
    return render(request, 'accounts/user_detail.html', context)


@login_required
@require_POST
def user_link_swimmer_view(request, pk):
    """Admin: link an account to an existing, not yet linked person."""
    if not request.user.profile.is_admin:
        messages.error(request, tr(request, 'msg_no_permission'))
        return redirect('calendar')
    target_user = get_object_or_404(User, pk=pk)
    swimmer_id = request.POST.get('swimmer', '')
    swimmer = (
        Swimmer.objects.filter(pk=swimmer_id, user__isnull=True).first()
        if swimmer_id.isdigit() else None
    )
    if swimmer is None or Swimmer.objects.filter(user=target_user).exists():
        messages.error(request, tr(request, 'msg_link_invalid'))
        return redirect('user_detail', pk=pk)

    swimmer.user = target_user
    if target_user.email:
        swimmer.email = target_user.email   # the account's e-mail is the verified one
    swimmer.save()
    messages.success(request, tr(request, 'msg_user_linked',
                                 user=target_user.username, name=swimmer.full_name))
    return redirect('user_detail', pk=pk)


@login_required
@require_POST
def user_unlink_swimmer_view(request, pk):
    """Admin: remove the link between an account and its person (both are kept)."""
    if not request.user.profile.is_admin:
        messages.error(request, tr(request, 'msg_no_permission'))
        return redirect('calendar')
    target_user = get_object_or_404(User, pk=pk)
    for swimmer in Swimmer.objects.filter(user=target_user):
        swimmer.user = None
        swimmer.save(update_fields=['user', 'updated_at'])
    messages.success(request, tr(request, 'msg_user_unlinked'))
    return redirect('user_detail', pk=pk)
