import json
from datetime import date, timedelta
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.generic import TemplateView
from django.http import JsonResponse
from django.contrib import messages
from django.db.models import Q, OuterRef, Subquery
from translations.helpers import tr

from .models import (
    RecurringSession, SessionException, SessionInstance, Attendance, ExcuseToken,
    TrainingPlanEntry,
)
from groups.models import Group, GroupMembership
from swimmers.models import Swimmer


def _is_session_trainer(request, recurring_session):
    """Return True if the current user may manage this recurring session's group."""
    if not request.user.is_authenticated:
        return False
    return (
        request.user.profile.is_admin or
        GroupMembership.objects.filter(
            group=recurring_session.group,
            swimmer__user=request.user,
            role=GroupMembership.ROLE_TRAINER,
            active=True,
        ).exists()
    )


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
        date__lte=end_date,
    ).filter(
        Q(end_date__gte=start_date) |
        Q(end_date__isnull=True, date__gte=start_date)
    ).prefetch_related('affected_sessions')
    exception_map = {}  # {date: {session_id or 'all': exc}}
    for exc in exceptions_qs:
        overlap_start = max(exc.date, start_date)
        overlap_end = min(exc.effective_end_date, end_date)
        d = overlap_start
        while d <= overlap_end:
            if d not in exception_map:
                exception_map[d] = {}
            if exc.affects_all:
                exception_map[d]['all'] = exc
            else:
                for s in exc.affected_sessions.all():
                    exception_map[d][s.id] = exc
            d += timedelta(days=1)

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
                        'location': str(session.location),
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
                        'location': str(session.location),
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
                        'location': str(session.location),
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
        is_trainer = _is_session_trainer(request, recurring)

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
            active=True,
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
        role_subquery = (
            GroupMembership.objects
            .filter(
                swimmer=OuterRef('swimmer'),
                group=recurring.group,
                active=True,
            )
            .values('role')[:1]
        )
        attendances = list(
            instance.attendances
            .select_related('swimmer', 'excuse_token')
            .annotate(group_role=Subquery(role_subquery))
            .order_by(
                '-group_role',
                'swimmer__last_name',
                'swimmer__first_name',
            )
            .distinct()
        )

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


# ── Session state polling / offline fallback ─────────────────────────────────
# These mirror the WebSocket consumer's `init` payload and `update_attendance`
# action. They exist so the session modal keeps working (read state every few
# seconds, queue and replay attendance changes) when the WebSocket connection
# drops — e.g. while a phone screen is locked.

@login_required
def session_state_api(request, instance_id):
    """Return the same state payload the WebSocket sends on connect."""
    instance = get_object_or_404(
        SessionInstance.objects.select_related('recurring_session__group'), pk=instance_id
    )
    recurring = instance.recurring_session
    is_trainer = _is_session_trainer(request, recurring)

    entries = [e.to_dict() for e in instance.plan_entries.all()]
    attendances = [
        a.to_dict()
        for a in instance.attendances.select_related('swimmer', 'marked_by').distinct()
    ]
    return JsonResponse({
        'session_id': instance.pk,
        'trainer_notes': instance.trainer_notes,
        'plan_entries': entries,
        'attendances': attendances,
        'is_trainer': is_trainer,
    })


@login_required
def session_attendance_update_api(request, instance_id):
    """REST fallback for `update_attendance` when the WebSocket is unavailable."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)

    instance = get_object_or_404(
        SessionInstance.objects.select_related('recurring_session__group'), pk=instance_id
    )
    if not _is_session_trainer(request, instance.recurring_session):
        return JsonResponse({'error': 'forbidden'}, status=403)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, TypeError):
        return JsonResponse({'error': 'invalid json'}, status=400)

    swimmer = get_object_or_404(Swimmer, pk=data.get('swimmer_id'))
    att, _ = Attendance.objects.get_or_create(session=instance, swimmer=swimmer)
    att.status = data.get('status', att.status)
    att.notes = data.get('notes', att.notes)
    att.marked_by = request.user
    att.save()
    return JsonResponse(att.to_dict())


# ── Training plan entry photo ─────────────────────────────────────────────────

@login_required
def plan_entry_photo_view(request, entry_id):
    """Upload (POST, multipart) or remove (DELETE) the photo for a plan entry."""
    entry = get_object_or_404(
        TrainingPlanEntry.objects.select_related('session__recurring_session__group'),
        pk=entry_id,
    )
    recurring = entry.session.recurring_session
    if not _is_session_trainer(request, recurring):
        return JsonResponse({'error': 'forbidden'}, status=403)

    if request.method == 'POST':
        photo = request.FILES.get('photo')
        if not photo:
            return JsonResponse({'error': 'no file provided'}, status=400)
        if entry.photo:
            entry.photo.delete(save=False)
        entry.photo = photo
        entry.save(update_fields=['photo'])
        return JsonResponse(entry.to_dict())

    if request.method == 'DELETE':
        if entry.photo:
            entry.photo.delete(save=False)
            entry.photo = None
            entry.save(update_fields=['photo'])
        return JsonResponse(entry.to_dict())

    return JsonResponse({'error': 'method not allowed'}, status=405)

@login_required
def plan_entry_photo_create_view(request, instance_id):
    """Create a brand-new plan entry directly from a photo (POST, multipart).

    For digitizing an existing paper plan poolside: a trainer photographs a
    handwritten set and it becomes its own entry immediately, with no
    shorthand to type. Mirrors the ordering logic in
    consumers.db_add_plan_entry so entries created this way slot in at the
    end of the list just like a normal quick-add.
    """
    instance = get_object_or_404(
        SessionInstance.objects.select_related('recurring_session__group'),
        pk=instance_id,
    )
    recurring = instance.recurring_session
    if not _is_session_trainer(request, recurring):
        return JsonResponse({'error': 'forbidden'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'error': 'method not allowed'}, status=405)

    photo = request.FILES.get('photo')
    if not photo:
        return JsonResponse({'error': 'no file provided'}, status=400)

    last = TrainingPlanEntry.objects.filter(session=instance).order_by('order').last()
    entry = TrainingPlanEntry.objects.create(
        session=instance,
        order=(last.order + 1) if last else 0,
        category=request.POST.get('category', 'main'),
        photo=photo,
    )
    return JsonResponse(entry.to_dict())

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
    form = SessionExceptionForm(request.POST or None, request=request)
    if request.method == 'POST' and form.is_valid():
        exc = form.save(commit=False)
        exc.created_by = request.user
        exc.save()
        form.save_m2m()
        if exc.is_range:
            date_str = f'{exc.date:%d.%m.%Y} – {exc.end_date:%d.%m.%Y}'
        else:
            date_str = f'{exc.date:%d.%m.%Y}'
        messages.success(request, tr(request, 'msg_exception_saved', date=date_str))
        return redirect('calendar')
    return render(request, 'training/exception_form.html', {'form': form})

# ── Trainer quarterly report ─────────────────────────────────────────────────

def _format_hours(minutes):
    """0.75 / 1 / 1.5 – dot decimal and no trailing zeros, as the external portal expects."""
    return f'{minutes / 60:.2f}'.rstrip('0').rstrip('.')


def _quarter_bounds(year, quarter):
    import calendar
    first_month = 3 * (quarter - 1) + 1
    last_month = first_month + 2
    return (
        date(year, first_month, 1),
        date(year, last_month, calendar.monthrange(year, last_month)[1]),
    )


@login_required
def trainer_report_view(request):
    """Quarterly overview of all sessions the current user attended as a trainer.

    A session counts when the user's own Attendance row is marked *present* and
    they hold the trainer role in the session's group. The swimmer count is the
    number of present attendees who are not trainers of that group.
    """
    swimmer = Swimmer.objects.filter(user=request.user).first()
    trainer_group_ids = set()
    if swimmer:
        # Deliberately not filtered by `active`: a trainer who left a group
        # mid-quarter must still be able to report the sessions they led.
        trainer_group_ids = set(
            GroupMembership.objects
            .filter(swimmer=swimmer, role=GroupMembership.ROLE_TRAINER)
            .values_list('group_id', flat=True)
        )
    if not trainer_group_ids:
        messages.error(request, tr(request, 'msg_no_permission'))
        return redirect('calendar')

    # ── Quarter selection (?year=2026&q=3, default: current quarter) ─────────
    today = date.today()
    try:
        year = int(request.GET.get('year', today.year))
        quarter = int(request.GET.get('q', (today.month - 1) // 3 + 1))
        if not (1 <= quarter <= 4 and 2000 <= year <= 2100):
            raise ValueError
    except ValueError:
        year, quarter = today.year, (today.month - 1) // 3 + 1
    start, end = _quarter_bounds(year, quarter)

    prev_year, prev_q = (year, quarter - 1) if quarter > 1 else (year - 1, 4)
    next_year, next_q = (year, quarter + 1) if quarter < 4 else (year + 1, 1)

    # ── Sessions the trainer was present in ──────────────────────────────────
    base_qs = (
        SessionInstance.objects
        .filter(
            date__range=(start, end),
            recurring_session__group_id__in=trainer_group_ids,
        )
        .select_related('recurring_session__group', 'recurring_session__location')
    )
    instances = list(
        # swimmer + status in ONE filter() call so both apply to the same
        # attendance row (chained filters on a multi-valued relation would not)
        base_qs.filter(attendances__swimmer=swimmer,
                       attendances__status=Attendance.STATUS_PRESENT)
        .distinct()
        .order_by('date', 'recurring_session__start_time')
    )

    # Present attendees per instance, minus the trainers of that group
    trainers_by_group = {}
    for group_id, swimmer_id in GroupMembership.objects.filter(
        group_id__in=trainer_group_ids, role=GroupMembership.ROLE_TRAINER,
    ).values_list('group_id', 'swimmer_id'):
        trainers_by_group.setdefault(group_id, set()).add(swimmer_id)

    present_by_instance = {}
    for instance_id, swimmer_id in Attendance.objects.filter(
        session__in=instances, status=Attendance.STATUS_PRESENT,
    ).values_list('session_id', 'swimmer_id'):
        present_by_instance.setdefault(instance_id, set()).add(swimmer_id)

    rows = []
    total_minutes = 0
    for inst in instances:
        rec = inst.recurring_session
        minutes = rec.duration_minutes
        total_minutes += minutes
        present = present_by_instance.get(inst.pk, set())
        rows.append({
            'date': inst.date,
            'start': rec.start_time,
            'end': rec.end_time,
            'hours': _format_hours(minutes),
            'group': rec.group,
            'location': rec.location,
            'swimmer_count': len(present - trainers_by_group.get(rec.group_id, set())),
        })

    # Sessions where the trainer's own attendance was never marked – these do
    # not appear above, so surface them as a hint instead of silently dropping.
    unmarked = list(
        base_qs.filter(attendances__swimmer=swimmer,
                       attendances__status=Attendance.STATUS_UNKNOWN)
        .distinct()
        .order_by('date', 'recurring_session__start_time')
    )

    return render(request, 'training/trainer_report.html', {
        'rows': rows,
        'total_hours': _format_hours(total_minutes),
        'total_swimmers': sum(r['swimmer_count'] for r in rows),
        'unmarked': unmarked,
        'year': year,
        'quarter': quarter,
        'start': start,
        'end': end,
        'prev': {'year': prev_year, 'q': prev_q},
        'next': {'year': next_year, 'q': next_q},
    })
