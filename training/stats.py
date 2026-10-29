"""Attendance statistics for trainers.

All functions are read-only and use a handful of aggregate queries, no
per-row lookups.

Definitions
-----------
* *rated* sessions of a person = present + absent + excused (``unknown`` is
  reported separately and never counted as a miss).
* attendance quota = present / rated
* excused share    = excused / (absent + excused)
* Trainers of the group are left out of group statistics, like in the
  trainer report.
* Optional sessions (``SessionInstance.is_optional``) are excluded unless the
  caller asks to include them.
"""
import calendar
from datetime import date, timedelta

from django.db.models import Count

from groups.models import GroupMembership
from swimmers.models import Swimmer
from .models import Attendance, SessionInstance

PRESENT = Attendance.STATUS_PRESENT
ABSENT = Attendance.STATUS_ABSENT
EXCUSED = Attendance.STATUS_EXCUSED
UNKNOWN = Attendance.STATUS_UNKNOWN

RANGE_KEYS = ('prev_month', '30d', 'prev_quarter', 'this_quarter', 'custom')
DEFAULT_RANGE = '30d'


# ── Date range ───────────────────────────────────────────────────────────────

def _parse_date(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def resolve_range(params, today=None):
    """Turn GET parameters into ``(key, start, end)``.

    ``range`` is one of RANGE_KEYS; ``custom`` reads ``from`` / ``to``
    (ISO dates). The end is clamped to today so future-dated sessions do not
    show up as "unknown". Invalid input falls back to the default range.
    """
    today = today or date.today()
    key = params.get('range', DEFAULT_RANGE)
    if key not in RANGE_KEYS:
        key = DEFAULT_RANGE

    if key == 'prev_month':
        last_of_prev = today.replace(day=1) - timedelta(days=1)
        start, end = last_of_prev.replace(day=1), last_of_prev
    elif key in ('prev_quarter', 'this_quarter'):
        q = (today.month - 1) // 3 + 1
        year = today.year
        if key == 'prev_quarter':
            q, year = (q - 1, year) if q > 1 else (4, year - 1)
        first_month = 3 * (q - 1) + 1
        last_month = first_month + 2
        start = date(year, first_month, 1)
        end = date(year, last_month, calendar.monthrange(year, last_month)[1])
    elif key == 'custom':
        start, end = _parse_date(params.get('from')), _parse_date(params.get('to'))
        if start is None or end is None or start > end:
            key = DEFAULT_RANGE
            start, end = today - timedelta(days=29), today
    else:
        start, end = today - timedelta(days=29), today

    return key, start, min(end, today)


def filter_context(params, today=None):
    """Parse the shared statistics filter (range, optional sessions, per lane).

    Returns the dict the filter partial and both views work with.
    """
    key, start, end = resolve_range(params, today)
    return {
        'range': key, 'start': start, 'end': end,
        'include_optional': params.get('optional') == '1',
        'per_lane': params.get('lanes') == '1',
        'range_keys': RANGE_KEYS,
    }


# ── Helpers ──────────────────────────────────────────────────────────────────

def _pct(part, whole):
    """Percentage rounded to one decimal, or None when there is nothing to divide by."""
    return round(100 * part / whole, 1) if whole else None


def _counts(rows):
    """{status: n} -> dict with all four statuses plus the derived quotas."""
    present = rows.get(PRESENT, 0)
    absent = rows.get(ABSENT, 0)
    excused = rows.get(EXCUSED, 0)
    unknown = rows.get(UNKNOWN, 0)
    rated = present + absent + excused
    return {
        'present': present, 'absent': absent, 'excused': excused, 'unknown': unknown,
        'rated': rated,
        'quota': _pct(present, rated),
        'excused_share': _pct(excused, absent + excused),
    }


def _instances(group_ids, start, end, include_optional):
    qs = SessionInstance.objects.filter(
        date__range=(start, end), recurring_session__group_id__in=group_ids,
    )
    optional_hidden = 0
    if not include_optional:
        optional_hidden = qs.filter(is_optional=True).count()
        qs = qs.filter(is_optional=False)
    return qs, optional_hidden


# ── Person ───────────────────────────────────────────────────────────────────

def person_stats(swimmer, group_ids, start, end, include_optional=False):
    """Attendance of one person in the given groups' sessions.

    ``group_ids`` is the set of groups the *viewer* may see; sessions of other
    groups are never included.
    """
    instances, optional_hidden = _instances(group_ids, start, end, include_optional)
    attendances = (
        Attendance.objects
        .filter(swimmer=swimmer, session__in=instances)
        .select_related('session__recurring_session__group')
        .order_by('session__date', 'session__recurring_session__start_time')
    )

    rows, status_counts = [], {}
    for att in attendances:
        status_counts[att.status] = status_counts.get(att.status, 0) + 1
        rec = att.session.recurring_session
        rows.append({
            'date': att.session.date, 'start': rec.start_time, 'group': rec.group,
            'status': att.status, 'notes': att.notes,
            'is_optional': att.session.is_optional,
        })

    # Sessions missed in a row, counted back from the most recent rated one.
    # "unknown" rows are skipped: they say nothing either way.
    streak = 0
    for row in reversed(rows):
        if row['status'] == UNKNOWN:
            continue
        if row['status'] == PRESENT:
            break
        streak += 1

    return {
        **_counts(status_counts),
        'rows': rows,
        'miss_streak': streak,
        'optional_hidden': optional_hidden,
    }


# ── Group ────────────────────────────────────────────────────────────────────

def group_stats(group, start, end, include_optional=False, per_lane=False):
    """Per-session table, summary and per-person ranking for one group."""
    instances, optional_hidden = _instances([group.pk], start, end, include_optional)
    instances = list(
        instances.select_related('recurring_session__location')
        .order_by('date', 'recurring_session__start_time')
    )

    trainer_ids = set(
        GroupMembership.objects
        .filter(group=group, role=GroupMembership.ROLE_TRAINER)
        .values_list('swimmer_id', flat=True)
    )
    attendances = (
        Attendance.objects
        .filter(session__in=instances)
        .exclude(swimmer_id__in=trainer_ids)
    )

    by_session = {}
    for sid, status, n in attendances.values_list('session_id', 'status').annotate(n=Count('id')):
        by_session.setdefault(sid, {})[status] = n

    rows, total = [], {}
    lane_values, without_lanes = [], 0
    for inst in instances:
        c = _counts(by_session.get(inst.pk, {}))
        for status in (PRESENT, ABSENT, EXCUSED, UNKNOWN):
            total[status] = total.get(status, 0) + c[status]
        per_lane_value = None
        if per_lane:
            if inst.lanes:
                per_lane_value = round(c['present'] / inst.lanes, 1)
                lane_values.append(per_lane_value)
            else:
                without_lanes += 1
        rows.append({
            'date': inst.date, 'start': inst.recurring_session.start_time,
            'location': inst.recurring_session.location,
            'lanes': inst.lanes, 'per_lane': per_lane_value,
            'is_optional': inst.is_optional, **c,
        })

    # Per-person ranking: lowest attendance first. Only people with at least
    # one rated session appear.
    by_swimmer = {}
    for swid, status, n in attendances.values_list('swimmer_id', 'status').annotate(n=Count('id')):
        by_swimmer.setdefault(swid, {})[status] = n
    swimmers = Swimmer.objects.in_bulk(by_swimmer.keys())
    people = []
    for swid, counts in by_swimmer.items():
        c = _counts(counts)
        if c['rated']:
            people.append({'swimmer': swimmers[swid], **c})
    people.sort(key=lambda p: (p['quota'], -p['absent'], p['swimmer'].last_name))

    summary = _counts(total)
    n_sessions = len(rows)
    summary.update({
        'sessions': n_sessions,
        'avg_present': round(total.get(PRESENT, 0) / n_sessions, 1) if n_sessions else None,
        'avg_per_lane': round(sum(lane_values) / len(lane_values), 1) if lane_values else None,
        'sessions_without_lanes': without_lanes,
        'optional_hidden': optional_hidden,
    })
    return {'rows': rows, 'summary': summary, 'people': people}
