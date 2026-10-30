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
    from django.db.models import Exists, OuterRef
    from groups.models import Group, GroupMembership

    params = request.GET
    q = params.get('q', '').strip()
    group_id = params.get('group', '')           # '' = all, 'none' = without group, else pk
    # status: active (default) | inactive | all. A plain "active" checkbox cannot express
    # "show inactive", because an unchecked box sends nothing and falls back to the default.
    status = params.get('status', 'active')
    if status not in ('active', 'inactive', 'all'):
        status = 'active'
    role = params.get('role', '')                # '' | trainer | swimmer
    if role not in (GroupMembership.ROLE_TRAINER, GroupMembership.ROLE_SWIMMER):
        role = ''
    account = params.get('account', '')          # '' | with | without
    if account not in ('with', 'without'):
        account = ''
    sort = params.get('sort', 'name')
    if sort not in ('name', 'first', 'newest', 'age'):
        sort = 'name'
    born_from = _to_year(params.get('born_from'))
    born_to = _to_year(params.get('born_to'))

    is_trainer_view = request.user.profile.is_trainer
    swimmers = Swimmer.objects.all()

    if status == 'active':
        swimmers = swimmers.filter(active=True)
    elif status == 'inactive':
        swimmers = swimmers.filter(active=False)

    # Free text: every word must match somewhere (name, e-mail, phone, group name).
    for word in q.split():
        swimmers = swimmers.filter(
            Q(first_name__icontains=word) | Q(last_name__icontains=word) |
            Q(email__icontains=word) | Q(phone__icontains=word) |
            Q(groupmembership_set__group__name__icontains=word)
        )

    memberships = GroupMembership.objects.filter(swimmer_id=OuterRef('pk'), active=True)
    if group_id == 'none':
        swimmers = swimmers.filter(~Exists(memberships))
    elif group_id.isdigit():
        memberships = memberships.filter(group_id=int(group_id))
        if role:
            memberships = memberships.filter(role=role)
        swimmers = swimmers.filter(Exists(memberships))
    elif role:
        swimmers = swimmers.filter(Exists(memberships.filter(role=role)))

    if born_from:
        swimmers = swimmers.filter(date_of_birth__year__gte=born_from)
    if born_to:
        swimmers = swimmers.filter(date_of_birth__year__lte=born_to)

    if is_trainer_view and account:
        swimmers = swimmers.filter(user__isnull=(account == 'without'))

    if not is_trainer_view:
        # Plain users see all trainers, plus every member of the groups they train themselves.
        visible = Q(is_trainer=True)
        group_ids = trained_group_ids(request.user)
        if group_ids:
            visible |= Q(pk__in=GroupMembership.objects.filter(
                group_id__in=group_ids, active=True,
            ).values('swimmer_id'))
        swimmers = swimmers.filter(visible)

    from django.db.models import F
    order = {
        'name': ('last_name', 'first_name'),
        'first': ('first_name', 'last_name'),
        'newest': ('-created_at', 'last_name'),
        # youngest first, persons without a birthday last
        'age': (F('date_of_birth').desc(nulls_last=True), 'last_name'),
    }[sort]
    swimmers = swimmers.distinct().order_by(*order)

    groups = Group.objects.filter(active=True).order_by('name')
    # Everything beyond search/group/status lives in a collapsible panel – open it when used.
    extra_active = bool(role or account or born_from or born_to or sort != 'name')

    context = {
        'swimmers': swimmers,
        'q': q,
        'groups': groups,
        'selected_group': group_id,
        'status': status,
        'role': role,
        'account': account,
        'sort': sort,
        'born_from': born_from or '',
        'born_to': born_to or '',
        'extra_active': extra_active,
        'filters_active': bool(q or group_id or status != 'active' or extra_active),
    }
    return render(request, 'swimmers/list.html', context)


def _to_year(value):
    """Birth-year filter input: a plausible 4-digit year or None."""
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    return year if 1900 <= year <= 2100 else None


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
    # Attendance statistics: profile trainers and admins only (club-level decisions).
    stats_ctx = {}
    if request.user.profile.is_trainer:
        from training import stats
        f = stats.filter_context(request.GET)
        stats_ctx = {
            'f': f,
            'show_lanes_toggle': False,
            'stats': stats.person_stats(
                swimmer, set(Group.objects.values_list('pk', flat=True)),
                f['start'], f['end'], include_optional=f['include_optional'],
            ),
        }
    # Swim times: visible to whoever may edit the person (profile trainers, the person
    # themself, trainers of the person's groups) – not to every logged-in member.
    perf_ctx = {}
    if can_edit:
        from training import performance
        perf_ctx = {'perf_data': performance.swimmer_results(swimmer)}
    return render(request, 'swimmers/detail.html', {
        **stats_ctx, **perf_ctx,
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
