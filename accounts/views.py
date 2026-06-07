from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.db.models import Q
from translations.helpers import tr
from .forms import StyledAuthForm, RegisterForm, UserProfileForm
from .models import UserProfile


def login_view(request):
    if request.user.is_authenticated:
        return redirect('calendar')
    form = StyledAuthForm(data=request.POST or None)
    if request.method == 'POST' and form.is_valid():
        login(request, form.get_user())
        return redirect(request.GET.get('next', 'calendar'))
    return render(request, 'accounts/login.html', {'form': form})


def logout_view(request):
    logout(request)
    return redirect('calendar')


def register_view(request):
    form = RegisterForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        login(request, user)
        return redirect('calendar')
    return render(request, 'accounts/register.html', {'form': form})


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
    q = request.GET.get('q', '')
    users = User.objects.select_related('profile').order_by('last_name', 'first_name')
    if q:
        users = users.filter(
            Q(first_name__icontains=q) | Q(last_name__icontains=q) |
            Q(username__icontains=q) | Q(email__icontains=q)
        )
    return render(request, 'accounts/user_list.html', {'users': users, 'q': q})


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
