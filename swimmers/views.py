from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.http import JsonResponse
from translations.helpers import tr
from .models import Swimmer
from .forms import SwimmerForm


def swimmer_list_view(request):
    q = request.GET.get('q', '')
    group_id = request.GET.get('group', '')
    active_only = request.GET.get('active', '1') == '1'
    swimmers = Swimmer.objects.prefetch_related('groupmembership_set__group')

    if active_only:
        swimmers = swimmers.filter(active=True)
    if q:
        swimmers = swimmers.filter(
            Q(first_name__icontains=q) | Q(last_name__icontains=q) |
            Q(email__icontains=q) | Q(phone__icontains=q)
        )
    if group_id:
        swimmers = swimmers.filter(groupmembership_set__group_id=group_id)
    if not request.user.is_authenticated:
        swimmers = swimmers.filter(is_trainer=True)

    from groups.models import Group
    groups = Group.objects.filter(active=True).order_by('name')

    context = {
        'swimmers': swimmers,
        'q': q,
        'groups': groups,
        'selected_group': group_id,
        'active_only': active_only,
    }
    return render(request, 'swimmers/list.html', context )


@login_required
def swimmer_detail_view(request, pk):
    swimmer = get_object_or_404(Swimmer, pk=pk)
    can_edit = request.user.profile.is_trainer or (
        hasattr(request.user, 'swimmer') and request.user.swimmer == swimmer
    )
    form = SwimmerForm(request.POST or None, instance=swimmer) if can_edit else None
    if request.method == 'POST' and can_edit and form and form.is_valid():
        form.save()
        messages.success(request, tr(request, 'msg_swimmer_updated'))
        return redirect('swimmer_detail', pk=pk)
    from groups.models import GroupMembership
    memberships = GroupMembership.objects.filter(swimmer=swimmer).select_related('group')
    return render(request, 'swimmers/detail.html', {
        'swimmer': swimmer, 'form': form,
        'memberships': memberships, 'can_edit': can_edit,
    })


@login_required
def swimmer_create_view(request):
    if not request.user.profile.is_trainer:
        messages.error(request, tr(request, 'msg_no_permission'))
        return redirect('swimmer_list')
    form = SwimmerForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        swimmer = form.save()
        messages.success(request, tr(request, 'msg_swimmer_added', name=swimmer.full_name))
        return redirect('swimmer_detail', pk=swimmer.pk)
    return render(request, 'swimmers/form.html', {'form': form})


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


def swimmer_autocomplete(request):
    q = request.GET.get('q', '')
    swimmers = Swimmer.objects.filter(
        Q(first_name__icontains=q) | Q(last_name__icontains=q),
        active=True, user__isnull=True,
    )[:10]
    return JsonResponse({'results': [{'id': s.pk, 'text': s.full_name} for s in swimmers]})
