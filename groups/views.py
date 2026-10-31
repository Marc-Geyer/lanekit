from django.db.models import Count, Q
from django.utils import timezone
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from translations.helpers import tr
from accounts import permissions as perm
from .models import Group, GroupMembership
from .forms import GroupForm, GroupMemberCreateForm


def group_list_view(request):
    today = timezone.localdate()
    groups = Group.objects.filter(active=True).prefetch_related('memberships__swimmer').annotate(
        active_member_count=Count(
            'memberships',
            filter=Q(memberships__active=True, memberships__swimmer__active=True),
            distinct=True,
        ),
        # Public (it can be derived from the calendar anyway): only sessions that are switched on and
        # have not run out yet. Past, expired recurring sessions do not count.
        current_session_count=Count(
            'recurring_sessions',
            filter=Q(recurring_sessions__active=True) & (
                Q(recurring_sessions__valid_until__isnull=True) | Q(recurring_sessions__valid_until__gte=today)
            ),
            distinct=True,
        ),
    )

    # Everybody sees group names and the number of current sessions. Members, the member count and the
    # detail page are limited to the groups whose roster the viewer may see (all groups for trainers,
    # the own groups for assistants).
    return render(request, 'groups/list.html', {
        'groups': groups,
        'roster_group_ids': perm.roster_group_ids(request.user),
    })


@login_required
def group_detail_view(request, pk):
    group = get_object_or_404(Group, pk=pk)
    if not perm.can_view_group(request.user, group.pk):
        messages.error(request, tr(request, 'msg_no_permission'))
        return redirect('group_list')
    is_trainer = perm.can_manage_group(request.user, group.pk)
    memberships = group.get_members()
    from training.models import RecurringSession
    sessions = RecurringSession.objects.filter(group=group, active=True).order_by('day_of_week', 'start_time')
    return render(request, 'groups/detail.html', {
        'group': group, 'memberships': memberships, 'sessions': sessions,
        'is_trainer': is_trainer,
        'can_view_stats': perm.can_view_group_stats(request.user, group.pk),
        'group_form': GroupForm(instance=group) if is_trainer else None,
    })


@login_required
def group_edit_view(request, pk):
    group = get_object_or_404(Group, pk=pk)
    if not perm.can_manage_group(request.user, group.pk):
        messages.error(request, tr(request, 'msg_no_permission'))
        return redirect('group_list')
    form = GroupForm(request.POST or None, instance=group)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, tr(request, 'msg_group_updated'))
        return redirect('group_detail', pk=pk)
    return render(request, 'groups/form.html', {'form': form, 'group': group})


@login_required
def group_create_view(request):
    if not perm.can_create_group(request.user):
        messages.error(request, tr(request, 'msg_no_permission'))
        return redirect('group_list')
    form = GroupForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        group = form.save()
        messages.success(request, tr(request, 'msg_group_created', name=group.name))
        return redirect('group_detail', pk=group.pk)
    return render(request, 'groups/form.html', {'form': form})


@login_required
def membership_remove_view(request, group_pk, swimmer_pk):
    group = get_object_or_404(Group, pk=group_pk)
    if not perm.can_remove_person_from_group(request.user, group.pk):
        messages.error(request, tr(request, 'msg_no_permission'))
        return redirect('group_list')
    if request.method == 'POST':
        GroupMembership.objects.filter(group=group, swimmer_id=swimmer_pk).update(active=False)
        messages.success(request, tr(request, 'msg_member_removed'))
    return redirect('group_detail', pk=group_pk)


@login_required
def group_member_create_view(request, group_pk):
    """Create a new person and link them to this group in one step."""
    group = get_object_or_404(Group, pk=group_pk)
    if not perm.can_create_person(request.user, group.pk):
        messages.error(request, tr(request, 'msg_no_permission'))
        return redirect('group_list')
    form = GroupMemberCreateForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        swimmer = form.save()
        GroupMembership.objects.create(
            group=group, swimmer=swimmer, role=form.cleaned_data['role'],
        )
        messages.success(request, tr(request, 'msg_member_added', name=swimmer.full_name))
        return redirect('group_detail', pk=group_pk)
    return render(request, 'groups/member_form.html', {'form': form, 'group': group})
