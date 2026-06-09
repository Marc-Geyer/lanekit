from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.http import Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.db.models import Q, IntegerField, Value, When, Case
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from twisted.words.xish.xpath import matches

from swimmers.models import Swimmer
from swimmingclub import settings
from translations.helpers import tr
from .forms import StyledAuthForm, RegisterForm, UserProfileForm
from .models import UserProfile


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
        user = form.save(commit=False)
        user.is_active = False
        user.save()

        mail = user.email

        if not Swimmer.objects.filter(email=mail).exists():
            messages.success(request, tr(request, 'msg_activ_faild'))
            return redirect('calendar')

        send_verification_email(request, user, purpose='activate_account')
        return render(request, 'accounts/verification_sent.html')
    return render(request, 'accounts/register.html', {'form': form})


def send_verification_email(request, user, new_email=None, purpose='activate_account'):
    """
        Generate token and send verification email.
        """
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)

    if purpose == 'email_verify':
        subject = 'Verify your email account'
        message = ''
        pass

    elif purpose == 'activate_account':
        url_path = reverse('activate', kwargs={'uidb64': uid, 'token': token})
        subject = tr(request, 'activate_account')
        message = tr(request,
                     'activate_email',
                     scheme=request.scheme,
                     host= request.get_host(),
                     url=url_path)

    else:
        raise Http404()

    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[new_email if purpose == 'email_verify' and new_email is not None else user.email],
        fail_silently=False,
    )

def activate_view(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is not None and default_token_generator.check_token(user, token):
        user.is_active = True
        user.save()

        person = (
            Swimmer.objects
            .filter(email=user.email)
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

        if person:
            person.user = user
            person.save()

            login(request, user)

            check_trainer_status(user)
            messages.success(request, tr(request, 'msg_activ_successfull'))
        else:
            user.delete()
            messages.success(request, tr(request, 'msg_activ_faild'))

        return redirect('calendar')
    return render(request, 'accounts/varification_failed.html', {'user': user})


@login_required
def profile_view(request):
    profile = request.user.profile
    form = UserProfileForm(
        request.POST or None, request.FILES or None,
        instance=profile, user=request.user,
    )
    if request.method == 'POST' and form.is_valid():
        form.save_user_fields(request.user)
        form.save()
        messages.success(request, tr(request, 'msg_profile_updated'))
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
    if not request.user.profile.is_admin and request.user.pk != pk:
        messages.error(request, tr(request, 'msg_no_permission'))
        return redirect('calendar')
    target_user = get_object_or_404(User, pk=pk)
    profile = target_user.profile
    form = UserProfileForm(
        request.POST or None, request.FILES or None,
        instance=profile, user=target_user,
    )
    if request.method == 'POST' and form.is_valid():
        form.save_user_fields(target_user)
        form.save()
        messages.success(request, tr(request, 'msg_user_updated'))
    return render(request, 'accounts/user_detail.html', {
        'target_user': target_user, 'form': form
    })
