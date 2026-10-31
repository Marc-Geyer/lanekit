from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from translations.helpers import tr
from accounts import permissions as perm
from .models import Swimmer, PersonChangeRequest
from .forms import SwimmerForm, SwimmerCreateForm, SwimmerProposalForm
from . import changes

@login_required
def swimmer_list_view(request):
    from django.db.models import Exists, OuterRef
    from groups.models import Group, GroupMembership

    if not perm.can_view_person_list(request.user):
        own = perm.own_swimmer(request.user)
        messages.error(request, tr(request, 'msg_no_permission'))
        return redirect('swimmer_detail', pk=own.pk) if own else redirect('calendar')

    is_admin = perm.is_admin(request.user)
    staff_group_ids = perm.roster_group_ids(request.user)   # groups whose pills/members the viewer may see
    trainer_group_ids = perm.groups_at_least(request.user, perm.Level.TRAINER)

    params = request.GET
    q = params.get('q', '').strip()
    group_id = params.get('group', '')           # '' = all, 'none' = without group, else pk
    if group_id.isdigit() and int(group_id) not in staff_group_ids:
        group_id = ''                            # never reveal membership of groups the viewer may not see
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

    swimmers = perm.visible_people(request.user, Swimmer.objects.all())

    if status == 'active':
        swimmers = swimmers.filter(active=True)
    elif status == 'inactive':
        swimmers = swimmers.filter(active=False)

    # Free text: every word must match somewhere. Names always; e-mail, phone and group names
    # only where the viewer may see them anyway (admin: everywhere, trainer: own groups' members).
    for word in q.split():
        match = Q(first_name__icontains=word) | Q(last_name__icontains=word)
        if is_admin:
            match |= (
                Q(email__icontains=word) | Q(phone__icontains=word) |
                Q(groupmembership_set__group__name__icontains=word)
            )
        elif trainer_group_ids:
            own_members = GroupMembership.objects.filter(
                group_id__in=trainer_group_ids, active=True,
            ).values('swimmer_id')
            match |= (Q(email__icontains=word) | Q(phone__icontains=word)) & Q(pk__in=own_members)
            match |= Q(
                groupmembership_set__group__name__icontains=word,
                groupmembership_set__group_id__in=staff_group_ids,
            )
        swimmers = swimmers.filter(match)

    memberships = GroupMembership.objects.filter(swimmer_id=OuterRef('pk'), active=True)
    if group_id == 'none':
        swimmers = swimmers.filter(~Exists(memberships))
    elif group_id.isdigit():
        memberships = memberships.filter(group_id=int(group_id))
        if role:
            memberships = memberships.filter(role=role)
        swimmers = swimmers.filter(Exists(memberships))
    elif role:
        scoped = memberships if is_admin else memberships.filter(group_id__in=staff_group_ids)
        swimmers = swimmers.filter(Exists(scoped.filter(role=role)))

    if born_from:
        swimmers = swimmers.filter(date_of_birth__year__gte=born_from)
    if born_to:
        swimmers = swimmers.filter(date_of_birth__year__lte=born_to)

    if is_admin and account:
        swimmers = swimmers.filter(user__isnull=(account == 'without'))
    else:
        account = ''

    from django.db.models import F
    order = {
        'name': ('last_name', 'first_name'),
        'first': ('first_name', 'last_name'),
        'newest': ('-created_at', 'last_name'),
        # youngest first, persons without a birthday last
        'age': (F('date_of_birth').desc(nulls_last=True), 'last_name'),
    }[sort]
    swimmers = swimmers.distinct().order_by(*order)

    swimmers = list(swimmers)
    # Per card: name + age for everybody on the list; e-mail only where the viewer has full access;
    # group badges only for groups the viewer is staff of.
    visible_memberships = {}
    for m in GroupMembership.objects.filter(
        swimmer__in=swimmers, active=True, group_id__in=staff_group_ids,
    ).select_related('group'):
        visible_memberships.setdefault(m.swimmer_id, []).append(m)
    for sw in swimmers:
        sw.vis_memberships = visible_memberships.get(sw.pk, [])
        sw.show_contact = is_admin or any(m.group_id in trainer_group_ids for m in sw.vis_memberships)

    groups = Group.objects.filter(active=True, pk__in=staff_group_ids).order_by('name')
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
        'can_create_person': perm.is_admin(request.user) or bool(trainer_group_ids),
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
    from groups.models import GroupMembership, Group
    swimmer = get_object_or_404(Swimmer, pk=pk)
    access = perm.person_access(request.user, swimmer)
    if access < perm.PersonAccess.BASIC:
        messages.error(request, tr(request, 'msg_no_permission'))
        return redirect('swimmer_list' if perm.can_view_person_list(request.user) else 'calendar')

    full = access >= perm.PersonAccess.FULL
    can_edit = perm.can_edit_person(request.user, swimmer)
    can_propose = perm.can_propose_person_change(request.user, swimmer)
    form = SwimmerForm(request.POST or None, instance=swimmer) if can_edit else None
    if request.method == 'POST' and can_edit and form and form.is_valid():
        form.save()
        changes.sync_linked_account(swimmer)
        messages.success(request, tr(request, 'msg_swimmer_updated'))
        return redirect('swimmer_detail', pk=pk)

    staff_group_ids = perm.roster_group_ids(request.user)   # groups whose pills/members the viewer may see
    trainer_group_ids = perm.groups_at_least(request.user, perm.Level.TRAINER)

    memberships = GroupMembership.objects.none()
    if full:
        memberships = GroupMembership.objects.filter(swimmer=swimmer).select_related('group')
        if not perm.is_admin(request.user) and perm.own_swimmer(request.user) != swimmer:
            # A trainer sees the groups they are staff of, not the person's other groups.
            memberships = memberships.filter(group_id__in=staff_group_ids)

    # Groups this person could be added to: only groups the viewer manages.
    active_group_ids = GroupMembership.objects.filter(swimmer=swimmer, active=True).values_list('group_id', flat=True)
    available_groups = Group.objects.filter(
        active=True, pk__in=trainer_group_ids,
    ).exclude(pk__in=active_group_ids).order_by('name')

    # Attendance statistics: only for full access, and only over the sessions the viewer may know about.
    stats_ctx = {}
    if perm.can_view_person_attendance_stats(request.user, swimmer):
        from training import stats
        f = stats.filter_context(request.GET)
        stats_ctx = {
            'f': f,
            'show_lanes_toggle': False,
            'stats': stats.person_stats(
                swimmer, perm.attendance_stats_group_ids(request.user, swimmer),
                f['start'], f['end'], include_optional=f['include_optional'],
            ),
        }
    # Swim-time statistics: basic access is enough (this is what lets any trainer judge performance).
    perf_ctx = {}
    if perm.can_view_person_performance(request.user, swimmer):
        from training import performance
        perf_ctx = {'perf_data': performance.swimmer_results(swimmer)}

    proposal_form = None
    if can_propose:
        proposal_form = SwimmerProposalForm(instance=Swimmer.objects.get(pk=swimmer.pk))
    pending = PersonChangeRequest.objects.none()
    if can_propose or perm.can_review_person_change(request.user, swimmer):
        pending = swimmer.change_requests.filter(status=PersonChangeRequest.STATUS_PENDING)

    return render(request, 'swimmers/detail.html', {
        **stats_ctx, **perf_ctx,
        'swimmer': swimmer, 'form': form,
        'access_full': full,
        'can_edit': can_edit,
        'can_view_notes': perm.can_view_person_notes(request.user, swimmer),
        'can_propose': can_propose,
        'proposal_form': proposal_form,
        'can_review': perm.can_review_person_change(request.user, swimmer),
        'pending_requests': pending,
        'memberships': memberships, 'staff_group_ids': staff_group_ids,
        'available_groups': available_groups,
        'manageable_group_ids': trainer_group_ids,
        'role_swimmer': GroupMembership.ROLE_SWIMMER,
        'role_trainer': GroupMembership.ROLE_TRAINER,
    })


@login_required
def swimmer_propose_change_view(request, pk):
    """A swimmer proposes changes to their own record; nothing is written until a trainer accepts."""
    swimmer = get_object_or_404(Swimmer, pk=pk)
    if request.method != 'POST' or not perm.can_propose_person_change(request.user, swimmer):
        messages.error(request, tr(request, 'msg_no_permission'))
        return redirect('swimmer_detail', pk=pk) if perm.can_view_person(request.user, swimmer) else redirect('calendar')
    form = SwimmerProposalForm(request.POST, instance=Swimmer.objects.get(pk=pk))
    if not form.is_valid():
        messages.error(request, tr(request, 'msg_proposal_invalid'))
        return redirect('swimmer_detail', pk=pk)
    proposed = {f: changes.serialise(form.cleaned_data[f]) for f in form.changed_data}
    if not proposed:
        messages.info(request, tr(request, 'msg_proposal_nothing'))
        return redirect('swimmer_detail', pk=pk)
    # A new proposal replaces the still-open older one.
    swimmer.change_requests.filter(status=PersonChangeRequest.STATUS_PENDING).delete()
    PersonChangeRequest.objects.create(swimmer=swimmer, proposed_by=request.user, changes=proposed)
    messages.success(request, tr(request, 'msg_proposal_sent'))
    return redirect('swimmer_detail', pk=pk)


def _review_view(request, pk, req_pk, approve):
    swimmer = get_object_or_404(Swimmer, pk=pk)
    if request.method != 'POST' or not perm.can_review_person_change(request.user, swimmer):
        messages.error(request, tr(request, 'msg_no_permission'))
        return redirect('swimmer_detail', pk=pk) if perm.can_view_person(request.user, swimmer) else redirect('calendar')
    change_request = get_object_or_404(PersonChangeRequest, pk=req_pk, swimmer=swimmer)
    changes.review(change_request, request.user, approve)
    messages.success(request, tr(request, 'msg_proposal_approved' if approve else 'msg_proposal_rejected'))
    return redirect('swimmer_detail', pk=pk)


@login_required
def swimmer_proposal_approve_view(request, pk, req_pk):
    return _review_view(request, pk, req_pk, True)


@login_required
def swimmer_proposal_reject_view(request, pk, req_pk):
    return _review_view(request, pk, req_pk, False)


@login_required
def swimmer_create_view(request):
    """Admin: create anywhere. Trainer: only into one of their own groups (group is mandatory)."""
    is_admin = perm.is_admin(request.user)
    allowed = None if is_admin else perm.creatable_group_ids(request.user)
    if not is_admin and not allowed:
        messages.error(request, tr(request, 'msg_no_permission'))
        return redirect('swimmer_list' if perm.can_view_person_list(request.user) else 'calendar')
    form = SwimmerCreateForm(request.POST or None, allowed_group_ids=allowed)
    if request.method == 'POST' and form.is_valid():
        group = form.cleaned_data.get('group')
        if not perm.can_create_person(request.user, group.pk if group else None) and not is_admin:
            messages.error(request, tr(request, 'msg_no_permission'))
            return redirect('swimmer_list')
        swimmer = form.save()

        # Optional group assignment (mandatory for trainers)
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
    """Add / re-activate / change the role of a group membership from the swimmer detail page."""
    swimmer = get_object_or_404(Swimmer, pk=pk)
    if request.method == 'POST':
        from groups.models import Group, GroupMembership
        group_id = request.POST.get('group')
        role = request.POST.get('role', GroupMembership.ROLE_SWIMMER)
        if role not in dict(GroupMembership.ROLE_CHOICES):
            role = GroupMembership.ROLE_SWIMMER
        group = get_object_or_404(Group, pk=group_id)
        if not perm.can_add_person_to_group(request.user, swimmer, group.pk):
            messages.error(request, tr(request, 'msg_no_permission'))
            return redirect('swimmer_detail', pk=pk) if perm.can_view_person(request.user, swimmer) else redirect('calendar')
        if role == GroupMembership.ROLE_TRAINER and not perm.can_assign_group_trainer(request.user, group.pk):
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
    """Remove a group membership from the swimmer detail page."""
    swimmer = get_object_or_404(Swimmer, pk=pk)
    if not perm.can_remove_person_from_group(request.user, group_pk):
        messages.error(request, tr(request, 'msg_no_permission'))
        return redirect('swimmer_detail', pk=pk) if perm.can_view_person(request.user, swimmer) else redirect('calendar')
    if request.method == 'POST':
        from groups.models import GroupMembership
        GroupMembership.objects.filter(group_id=group_pk, swimmer_id=pk).update(active=False)
        messages.success(request, tr(request, 'msg_member_removed'))
    return redirect('swimmer_detail', pk=pk)


@login_required
def swimmer_delete_view(request, pk):
    if not perm.is_admin(request.user):
        messages.error(request, tr(request, 'msg_no_permission'))
        return redirect('swimmer_list')
    swimmer = get_object_or_404(Swimmer, pk=pk)
    if request.method == 'POST':
        swimmer.active = False
        swimmer.save()
        messages.success(request, tr(request, 'msg_swimmer_deactivated', name=swimmer.full_name))
        return redirect('swimmer_list')
    return render(request, 'swimmers/confirm_delete.html', {'swimmer': swimmer})
