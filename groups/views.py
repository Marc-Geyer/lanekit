from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from translations.helpers import tr
from .models import Group, GroupMembership
from .forms import GroupForm, MembershipForm


def group_list_view(request):
    groups = Group.objects.filter(active=True).prefetch_related('memberships__swimmer')
    return render(request, 'groups/list.html', {'groups': groups})


@login_required
def group_detail_view(request, pk):
    group = get_object_or_404(Group, pk=pk)
    is_trainer = GroupMembership.objects.filter(
        group=group, swimmer__user=request.user,
        role=GroupMembership.ROLE_TRAINER,
    ).exists() or request.user.profile.is_admin
    memberships = group.get_members()
    from training.models import RecurringSession
    sessions = RecurringSession.objects.filter(group=group, active=True).order_by('day_of_week', 'start_time')
    return render(request, 'groups/detail.html', {
        'group': group, 'memberships': memberships, 'sessions': sessions,
        'is_trainer': is_trainer,
        'group_form': GroupForm(instance=group) if is_trainer else None,
        'member_form': MembershipForm() if is_trainer else None,
    })


@login_required
def group_edit_view(request, pk):
    group = get_object_or_404(Group, pk=pk)
    if not request.user.profile.is_trainer:
        messages.error(request, tr(request, 'msg_no_permission'))
        return redirect('group_detail', pk=pk)
    form = GroupForm(request.POST or None, instance=group)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, tr(request, 'msg_group_updated'))
        return redirect('group_detail', pk=pk)
    return render(request, 'groups/form.html', {'form': form, 'group': group})


@login_required
def group_create_view(request):
    if not request.user.profile.is_admin:
        messages.error(request, tr(request, 'msg_no_permission'))
        return redirect('group_list')
    form = GroupForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        group = form.save()
        messages.success(request, tr(request, 'msg_group_created', name=group.name))
        return redirect('group_detail', pk=group.pk)
    return render(request, 'groups/form.html', {'form': form})


@login_required
def membership_add_view(request, group_pk):
    group = get_object_or_404(Group, pk=group_pk)
    is_trainer = GroupMembership.objects.filter(
        group=group, swimmer__user=request.user, role=GroupMembership.ROLE_TRAINER
    ).exists() or request.user.profile.is_admin
    if not is_trainer:
        messages.error(request, tr(request, 'msg_no_permission'))
        return redirect('group_detail', pk=group_pk)
    if request.method == 'POST':
        form = MembershipForm(request.POST)
        if form.is_valid():
            m, created = GroupMembership.objects.get_or_create(
                group=group, swimmer=form.cleaned_data['swimmer'],
                defaults={'role': form.cleaned_data['role']},
            )
            if not created:
                m.role = form.cleaned_data['role']
                m.active = True
                m.save()
            messages.success(request, tr(request, 'msg_member_added', name=m.swimmer.full_name))
    return redirect('group_detail', pk=group_pk)


@login_required
def membership_remove_view(request, group_pk, swimmer_pk):
    group = get_object_or_404(Group, pk=group_pk)
    is_trainer = GroupMembership.objects.filter(
        group=group, swimmer__user=request.user, role=GroupMembership.ROLE_TRAINER
    ).exists() or request.user.profile.is_admin
    if not is_trainer:
        messages.error(request, tr(request, 'msg_no_permission'))
        return redirect('group_detail', pk=group_pk)
    if request.method == 'POST':
        GroupMembership.objects.filter(group=group, swimmer_id=swimmer_pk).update(active=False)
        messages.success(request, tr(request, 'msg_member_removed'))
    return redirect('group_detail', pk=group_pk)
