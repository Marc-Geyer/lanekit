import json
from datetime import date, timedelta
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.generic import TemplateView
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.db.models import Q
from django.utils import timezone
from translations.helpers import tr

from .models import (
    RecurringSession, SessionException, SessionInstance,
    TrainingPlanEntry, Attendance, ExcuseToken
)
from groups.models import Group, GroupMembership
from swimmers.models import Swimmer


# ── Calendar main view ───────────────────────────────────────────────────────

class CalendarView(TemplateView):
    template_name = 'training/calendar.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['groups'] = Group.objects.filter(active=True)
        return ctx


# ── Calendar events API (FullCalendar feed) ──────────────────────────────────

def calendar_events_api(request):
    """Return JSON array of FullCalendar events for a date range."""
    try:
        start_date = date.fromisoformat(request.GET.get('start', str(date.today()))[:10])
        end_date = date.fromisoformat(request.GET.get('end', str(date.today() + timedelta(days=30)))[:10])
    except ValueError:
        return JsonResponse({'error': 'invalid dates'}, status=400)

    my_sessions = request.GET.get('my_sessions') == '1' and request.user.is_authenticated

    # Fetch recurring sessions
    sessions_qs = RecurringSession.objects.filter(
        active=True,
        valid_from__lte=end_date,
    ).filter(
        Q(valid_until__isnull=True) | Q(valid_until__gte=start_date)
    ).select_related('group')

    if my_sessions:
        swimmer = getattr(request.user, 'swimmer', None)
        if swimmer:
            sessions_qs = sessions_qs.filter(
                group__memberships__swimmer=swimmer,
                group__memberships__active=True,
            ).distinct()
        else:
            sessions_qs = sessions_qs.none()

    # Build exception lookup: date -> {session_id -> exception}
    exceptions_qs = SessionException.objects.filter(
        date__gte=start_date, date__lte=end_date
    ).prefetch_related('affected_sessions')
    exception_map = {}  # {date: {session_id or 'all': exc}}
    for exc in exceptions_qs:
        d = exc.date
        if d not in exception_map:
            exception_map[d] = {}
        if exc.affects_all:
            exception_map[d]['all'] = exc
        else:
            for s in exc.affected_sessions.all():
                exception_map[d][s.id] = exc

    # Build instance lookup: (session_id, date) -> instance
    instances_qs = SessionInstance.objects.filter(
        date__gte=start_date, date__lte=end_date,
        recurring_session__in=sessions_qs,
    ).select_related('recurring_session__group')
    instance_map = {}
    for inst in instances_qs:
        instance_map[(inst.recurring_session_id, inst.date)] = inst

    # Iterate dates
    events = []
    current = start_date
    while current <= end_date:
        weekday = current.weekday()
        for session in sessions_qs:
            if session.day_of_week != weekday:
                continue
            if current < session.valid_from:
                continue
            if session.valid_until and current > session.valid_until:
                continue

            # Check exception
            exc_day = exception_map.get(current, {})
            exc = exc_day.get('all') or exc_day.get(session.id)
            if exc:
                events.append({
                    'id': f'exc_{session.id}_{current}',
                    'title': f'Abgesagt – {exc.reason}',
                    'start': f'{current}T{session.start_time}',
                    'end': f'{current}T{session.end_time}',
                    'backgroundColor': '#dc3545',
                    'borderColor': '#b02a37',
                    'textColor': '#fff',
                    'classNames': ['session-exception'],
                    'extendedProps': {
                        'type': 'exception',
                        'group': session.group.name,
                        'reason': exc.reason,
                        'location': session.location,
                    },
                })
                continue

            # Check instance
            inst = instance_map.get((session.id, current))
            if inst:
                events.append({
                    'id': f'inst_{inst.id}',
                    'title': session.group.name,
                    'start': f'{current}T{session.start_time}',
                    'end': f'{current}T{session.end_time}',
                    'backgroundColor': session.group.color,
                    'borderColor': session.group.color,
                    'textColor': '#fff',
                    'classNames': ['session-instance'],
                    'extendedProps': {
                        'type': 'instance',
                        'instance_id': inst.id,
                        'session_id': session.id,
                        'date': str(current),
                        'group': session.group.name,
                        'location': session.location,
                    },
                })
            else:
                events.append({
                    'id': f'plan_{session.id}_{current}',
                    'title': session.group.name,
                    'start': f'{current}T{session.start_time}',
                    'end': f'{current}T{session.end_time}',
                    'backgroundColor': session.group.color + 'bb',  # slightly transparent
                    'borderColor': session.group.color,
                    'textColor': '#fff',
                    'classNames': ['session-planned'],
                    'extendedProps': {
                        'type': 'planned',
                        'session_id': session.id,
                        'date': str(current),
                        'group': session.group.name,
                        'location': session.location,
                    },
                })
        current += timedelta(days=1)

    return JsonResponse(events, safe=False)


# ── Session modal content (AJAX) ─────────────────────────────────────────────

def session_modal_view(request, session_id, session_date):
    """Return HTML for the session modal. Creates instance if trainer requests it."""
    try:
        session_date_obj = date.fromisoformat(session_date)
    except ValueError:
        return JsonResponse({'error': 'invalid date'}, status=400)

    recurring = get_object_or_404(RecurringSession, pk=session_id)
    instance = SessionInstance.objects.filter(
        recurring_session=recurring, date=session_date_obj
    ).first()

    is_trainer = False
    if request.user.is_authenticated:
        is_trainer = (
            request.user.profile.is_admin or
            GroupMembership.objects.filter(
                group=recurring.group,
                swimmer__user=request.user,
                role=GroupMembership.ROLE_TRAINER,
                active=True,
            ).exists()
        )

    # Auto-create instance when trainer opens the modal
    created = False
    if not instance and is_trainer and request.method == 'POST':
        instance = SessionInstance.objects.create(
            recurring_session=recurring,
            date=session_date_obj,
            created_by=request.user,
        )
        # Pre-populate attendance for all group members
        members = Swimmer.objects.filter(
            groupmembership_set__group=recurring.group,
            groupmembership_set__active=True,
        )
        Attendance.objects.bulk_create(
            [Attendance(session=instance, swimmer=m) for m in members],
            ignore_conflicts=True,
        )
        created = True

    plan_entries = []
    attendances = []
    if instance:
        plan_entries = list(instance.plan_entries.all())
        attendances = list(instance.attendances.select_related('swimmer', 'excuse_token'))

    # Render to string so we can bundle the HTML with metadata in a single
    # JSON response. calendar.js reads instance_id and is_trainer directly
    # from the JSON — this avoids the innerHTML <script> execution problem
    # where injected script tags are silently ignored by the browser.
    from django.template.loader import render_to_string
    html = render_to_string('training/session_modal_content.html', {
        'recurring': recurring,
        'instance': instance,
        'session_date': session_date_obj,
        'plan_entries': plan_entries,
        'attendances': attendances,
        'is_trainer': is_trainer,
        'created': created,
    }, request=request)

    return JsonResponse({
        'html': html,
        'instance_id': instance.pk if instance else None,
        'is_trainer': is_trainer,
    })


# ── Excuse token ─────────────────────────────────────────────────────────────

def use_excuse_token_view(request, token):
    """Allow a swimmer to self-excuse using their token URL."""
    excuse = get_object_or_404(ExcuseToken, token=token)
    if excuse.used:
        messages.warning(request, tr(request, 'excuse_used_title'))
        return render(request, 'training/excuse_used.html', {'excuse': excuse})

    if request.method == 'POST':
        from django.utils import timezone
        excuse.used = True
        excuse.used_at = timezone.now()
        excuse.save()

        # Update or create attendance record
        instance = SessionInstance.objects.filter(
            recurring_session=excuse.recurring_session,
            date=excuse.date,
        ).first()
        if instance:
            att, _ = Attendance.objects.get_or_create(
                session=instance, swimmer=excuse.swimmer
            )
            att.status = Attendance.STATUS_EXCUSED
            att.excuse_token = excuse
            att.save()

        messages.success(request, tr(request, 'excuse_confirmed_title'))
        return render(request, 'training/excuse_confirmed.html', {'excuse': excuse})

    return render(request, 'training/excuse_confirm.html', {'excuse': excuse})


@login_required
def generate_excuse_token_view(request):
    """Trainer generates an excuse token link for a swimmer."""
    if not request.user.profile.is_trainer:
        return JsonResponse({'error': 'forbidden'}, status=403)
    if request.method == 'POST':
        data = json.loads(request.body)
        swimmer = get_object_or_404(Swimmer, pk=data['swimmer_id'])
        recurring = get_object_or_404(RecurringSession, pk=data['session_id'])
        try:
            session_date = date.fromisoformat(data['date'])
        except (KeyError, ValueError):
            return JsonResponse({'error': 'invalid date'}, status=400)
        token, _ = ExcuseToken.objects.get_or_create(
            swimmer=swimmer,
            recurring_session=recurring,
            date=session_date,
            defaults={'reason': data.get('reason', '')},
        )
        url = request.build_absolute_uri(token.get_excuse_url())
        return JsonResponse({'token': str(token.token), 'url': url})
    return JsonResponse({'error': 'POST only'}, status=405)


# ── Recurring session management ─────────────────────────────────────────────

@login_required
def recurring_session_create(request, group_pk):
    group = get_object_or_404(Group, pk=group_pk)
    is_trainer = request.user.profile.is_admin or GroupMembership.objects.filter(
        group=group, swimmer__user=request.user, role=GroupMembership.ROLE_TRAINER
    ).exists()
    if not is_trainer:
        messages.error(request, tr(request, 'msg_no_permission'))
        return redirect('group_detail', pk=group_pk)
    from .forms import RecurringSessionForm
    form = RecurringSessionForm(request.POST or None, initial={'group': group})
    if request.method == 'POST' and form.is_valid():
        session = form.save(commit=False)
        session.group = group
        session.created_by = request.user
        session.save()
        messages.success(request, tr(request, 'msg_session_created'))
        return redirect('group_detail', pk=group_pk)
    return render(request, 'training/recurring_session_form.html', {
        'form': form, 'group': group
    })


@login_required
def recurring_session_edit(request, pk):
    session = get_object_or_404(RecurringSession, pk=pk)
    is_trainer = request.user.profile.is_admin or GroupMembership.objects.filter(
        group=session.group, swimmer__user=request.user, role=GroupMembership.ROLE_TRAINER
    ).exists()
    if not is_trainer:
        messages.error(request, tr(request, 'msg_no_permission'))
        return redirect('group_detail', pk=session.group_id)
    from .forms import RecurringSessionForm
    form = RecurringSessionForm(request.POST or None, instance=session)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, tr(request, 'msg_session_updated'))
        return redirect('group_detail', pk=session.group_id)
    return render(request, 'training/recurring_session_form.html', {
        'form': form, 'group': session.group, 'session': session
    })


# ── Session exception ─────────────────────────────────────────────────────────

@login_required
def exception_create(request):
    if not request.user.profile.is_trainer:
        messages.error(request, tr(request, 'msg_no_permission'))
        return redirect('calendar')
    from .forms import SessionExceptionForm
    form = SessionExceptionForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        exc = form.save(commit=False)
        exc.created_by = request.user
        exc.save()
        form.save_m2m()
        messages.success(request, tr(request, 'msg_exception_saved', date=str(exc.date)))
        return redirect('calendar')
    return render(request, 'training/exception_form.html', {'form': form})