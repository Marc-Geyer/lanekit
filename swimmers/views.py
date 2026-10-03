from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from translations.helpers import tr
from .models import Swimmer
from .forms import SwimmerForm, SwimmerCreateForm
from .permissions import can_edit_swimmer, can_manage_group_membership, trained_group_ids

@login_required
def swimmer_list_view(request):
    q = request.GET.get('q', '').split(' ')
    group_id = request.GET.get('group', '')
    active_only = request.GET.get('active', '1') == '1'
    swimmers = Swimmer.objects.all()

    if active_only:
        swimmers = swimmers.filter(active=True)
    if q:
        for a in q:
            swimmers = swimmers.filter(
                Q(first_name__icontains=a) | Q(last_name__icontains=a) |
                Q(email__icontains=a) | Q(phone__icontains=a) |
                Q(groupmembership_set__group__name=a)
            )
    if group_id:
        swimmers = swimmers.filter(groupmembership_set__group_id=group_id)
    if not request.user.profile.is_trainer:
        # Plain users see all trainers, plus every member of the groups they train themselves.
        from groups.models import GroupMembership
        visible = Q(is_trainer=True)
        group_ids = trained_group_ids(request.user)
        if group_ids:
            visible |= Q(pk__in=GroupMembership.objects.filter(
                group_id__in=group_ids, active=True,
            ).values('swimmer_id'))
        swimmers = swimmers.filter(visible)

    from groups.models import Group
    groups = Group.objects.filter(active=True).order_by('name')

    swimmers = swimmers.distinct()

    context = {
        'swimmers': swimmers,
        'q': ' '.join(q),
        'groups': groups,
        'selected_group': group_id,
        'active_only': active_only,
    }
    return render(request, 'swimmers/list.html', context)


@login_required
def swimmer_detail_view(request, pk):
    swimmer = get_object_or_404(Swimmer, pk=pk)
    can_edit = can_edit_swimmer(request.user, swimmer)
    form = SwimmerForm(request.POST or None, instance=swimmer) if can_edit else None
    if request.method == 'POST' and can_edit and form and form.is_valid():
        form.save()
        messages.success(request, tr(request, 'msg_swimmer_updated'))
        return redirect('swimmer_detail', pk=pk)
    from groups.models import GroupMembership, Group
    memberships = GroupMembership.objects.filter(swimmer=swimmer).select_related('group')
    # Groups this swimmer is not yet actively a member of — used by the add-membership form
    active_group_ids = memberships.filter(active=True).values_list('group_id', flat=True)
    available_groups = Group.objects.filter(active=True).exclude(pk__in=active_group_ids).order_by('name')
    # Profile trainers manage every group; group trainers only the groups they train themselves.
    if request.user.profile.is_trainer:
        manageable_group_ids = set(Group.objects.values_list('pk', flat=True))
    else:
        manageable_group_ids = trained_group_ids(request.user)
        available_groups = available_groups.filter(pk__in=manageable_group_ids)
    return render(request, 'swimmers/detail.html', {
        'swimmer': swimmer, 'form': form,
        'memberships': memberships, 'can_edit': can_edit,
        'available_groups': available_groups,
        'manageable_group_ids': manageable_group_ids,
        'role_swimmer': GroupMembership.ROLE_SWIMMER,
        'role_trainer': GroupMembership.ROLE_TRAINER,
    })


@login_required
def swimmer_create_view(request):
    if not request.user.profile.is_trainer:
        messages.error(request, tr(request, 'msg_no_permission'))
        return redirect('swimmer_list')
    form = SwimmerCreateForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        swimmer = form.save()

        # Optional group assignment — same get_or_create pattern as membership_add_view
        group = form.cleaned_data.get('group')
        if group:
            from groups.models import GroupMembership
            role = form.cleaned_data.get('group_role') or GroupMembership.ROLE_SWIMMER
            membership, created = GroupMembership.objects.get_or_create(
                group=group,
                swimmer=swimmer,
                defaults={'role': role},
            )
            if not created:
                membership.role = role
                membership.active = True
                membership.save()

        messages.success(request, tr(request, 'msg_swimmer_added', name=swimmer.full_name))
        return redirect('swimmer_detail', pk=swimmer.pk)
    return render(request, 'swimmers/form.html', {'form': form})


@login_required
def swimmer_membership_add_view(request, pk):
    """Add a group membership from the swimmer detail page.
    Mirrors membership_add_view in groups/ but redirects back to swimmer_detail."""
    swimmer = get_object_or_404(Swimmer, pk=pk)
    if request.method == 'POST':
        from groups.models import Group, GroupMembership
        group_id = request.POST.get('group')
        role = request.POST.get('role', GroupMembership.ROLE_SWIMMER)
        if role not in dict(GroupMembership.ROLE_CHOICES):
            role = GroupMembership.ROLE_SWIMMER
        group = get_object_or_404(Group, pk=group_id)
        if not can_manage_group_membership(request.user, group.pk):
            messages.error(request, tr(request, 'msg_no_permission'))
            return redirect('swimmer_detail', pk=pk)
        membership, created = GroupMembership.objects.get_or_create(
            group=group,
            swimmer=swimmer,
            defaults={'role': role},
        )
        if not created:
            membership.role = role
            membership.active = True
            membership.save()
        messages.success(request, tr(request, 'msg_member_added', name=swimmer.full_name))
    return redirect('swimmer_detail', pk=pk)


@login_required
def swimmer_membership_remove_view(request, pk, group_pk):
    """Remove a group membership from the swimmer detail page.
    Mirrors membership_remove_view in groups/ but redirects back to swimmer_detail."""
    if not can_manage_group_membership(request.user, group_pk):
        messages.error(request, tr(request, 'msg_no_permission'))
        return redirect('swimmer_detail', pk=pk)
    if request.method == 'POST':
        from groups.models import GroupMembership
        GroupMembership.objects.filter(group_id=group_pk, swimmer_id=pk).update(active=False)
        messages.success(request, tr(request, 'msg_member_removed'))
    return redirect('swimmer_detail', pk=pk)


@login_required
def swimmer_delete_view(request, pk):
    if not request.user.profile.is_admin:
        messages.error(request, tr(request, 'msg_no_permission'))
        return redirect('swimmer_list')
    swimmer = get_object_or_404(Swimmer, pk=pk)
    if request.method == 'POST':
        swimmer.active = False
        swimmer.save()
        messages.success(request, tr(request, 'msg_swimmer_deactivated', name=swimmer.full_name))
        return redirect('swimmer_list')
    return render(request, 'swimmers/confirm_delete.html', {'swimmer': swimmer})
