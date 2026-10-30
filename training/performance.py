"""Swim-time helpers: parsing, formatting and the per-swimmer data feed.

Times are integers in hundredths of a second ("centiseconds", ``cs``).
"""
import re

from groups.models import GroupMembership
from .models import PerformanceResult

_TIME_RE = re.compile(r'^(?:(\d{1,3}):)?(\d{1,3})(?:[.,](\d{1,2}))?$')


def parse_time(text):
    """Parse ``1:05,32`` / ``1:05.32`` / ``65,32`` / ``32,1`` into centiseconds.

    * one decimal digit means tenths (``32,1`` = 32.10 s)
    * with minutes the seconds part must be < 60
    * returns ``None`` for anything invalid, zero or implausibly long
    """
    if not isinstance(text, str):
        return None
    m = _TIME_RE.match(text.strip())
    if not m:
        return None
    minutes, seconds, frac = m.groups()
    seconds = int(seconds)
    if minutes is not None and seconds >= 60:
        return None
    frac_cs = int(frac.ljust(2, '0')) if frac else 0
    total = (int(minutes) * 60 if minutes else 0) * 100 + seconds * 100 + frac_cs
    if total <= 0 or total > PerformanceResult.MAX_TIME_CS:
        return None
    return total


def format_time(cs):
    """Format centiseconds as ``m:ss,hh`` (or ``ss,hh`` below one minute)."""
    minutes, rest = divmod(int(cs), 6000)
    seconds, hundredths = divmod(rest, 100)
    if minutes:
        return f'{minutes}:{seconds:02d},{hundredths:02d}'
    return f'{seconds},{hundredths:02d}'


def result_to_dict(r):
    """JSON-safe representation used by the swimmer chart and the session list."""
    return {
        'id': r.pk,
        'date': r.date.isoformat(),
        'stroke': r.stroke,
        'distance': r.distance_m,
        'time_cs': r.time_cs,
        'time': format_time(r.time_cs),
        'pool': r.pool_length,
        'official': r.is_official,
        'location': r.location.name if r.location_id else '',
        'notes': r.notes,
    }


def swimmer_results(swimmer):
    """All results of one swimmer, oldest first, as a list of dicts (one query)."""
    qs = swimmer.results.select_related('location').order_by('date', 'id')
    return [result_to_dict(r) for r in qs]


STROKE_ORDER = [c for c, _ in PerformanceResult.STROKE_CHOICES]


def format_delta(cs):
    """Signed difference, e.g. ``-0,85`` (faster) / ``+1:02,10`` (slower)."""
    if cs == 0:
        return '±0'
    return ('+' if cs > 0 else '-') + format_time(abs(cs))


def times_filter(params):
    """Group-times filter from GET parameters (invalid values fall back to 'all')."""
    stroke = params.get('stroke')
    if stroke not in STROKE_ORDER:
        stroke = ''
    try:
        distance = int(params.get('distance', ''))
        if not 1 <= distance <= PerformanceResult.MAX_DISTANCE_M:
            distance = None
    except (TypeError, ValueError):
        distance = None
    return {
        'stroke': stroke, 'distance': distance,
        'split_pools': params.get('pools') != 'merge',   # default: keep 25 m / 50 m apart
    }


def group_results(group, start, end, stroke='', distance=None, split_pools=True):
    """Per-discipline ranking of the group's active swimmers (trainers left out).

    One block per (stroke, distance[, pool length]) with one row per swimmer:
    best time, latest time, number of times and the development
    (latest minus first time within the range; negative = faster).
    Two queries: option lists and the filtered results.
    """
    member_ids = list(
        GroupMembership.objects
        .filter(group=group, active=True, role=GroupMembership.ROLE_SWIMMER, swimmer__active=True)
        .values_list('swimmer_id', flat=True)
    )
    base = PerformanceResult.objects.filter(swimmer_id__in=member_ids, date__range=(start, end))
    options = list(base.values_list('stroke', 'distance_m').distinct())
    qs = base
    if stroke:
        qs = qs.filter(stroke=stroke)
    if distance:
        qs = qs.filter(distance_m=distance)

    blocks = {}
    for r in qs.select_related('swimmer').order_by('date', 'id'):
        key = (r.stroke, r.distance_m, r.pool_length if split_pools else None)
        block = blocks.setdefault(key, {
            'stroke': r.stroke, 'distance': r.distance_m,
            'pool': key[2], 'pools_seen': set(), 'by_swimmer': {},
        })
        block['pools_seen'].add(r.pool_length)
        block['by_swimmer'].setdefault(r.swimmer_id, []).append(r)

    out, total_results, swimmers = [], 0, set()
    for key in sorted(blocks, key=lambda k: (STROKE_ORDER.index(k[0]), k[1], k[2] or 0)):
        b = blocks[key]
        rows = []
        for swimmer_results_list in b['by_swimmer'].values():
            best = min(swimmer_results_list, key=lambda x: (x.time_cs, x.date))
            latest = swimmer_results_list[-1]
            first = swimmer_results_list[0]
            n = len(swimmer_results_list)
            rows.append({
                'swimmer': best.swimmer, 'count': n,
                'best': format_time(best.time_cs), 'best_cs': best.time_cs, 'best_date': best.date,
                'latest': format_time(latest.time_cs), 'latest_date': latest.date,
                'change_cs': latest.time_cs - first.time_cs if n > 1 else None,
                'change': format_delta(latest.time_cs - first.time_cs) if n > 1 else None,
            })
            total_results += n
            swimmers.add(best.swimmer_id)
        rows.sort(key=lambda x: (x['best_cs'], x['swimmer'].last_name))
        out.append({
            'stroke': b['stroke'], 'distance': b['distance'], 'pool': b['pool'],
            'mixed_pools': len(b['pools_seen']) > 1, 'rows': rows,
        })

    return {
        'blocks': out, 'total_results': total_results, 'total_swimmers': len(swimmers),
        'stroke_options': [c for c in STROKE_ORDER if any(o[0] == c for o in options)],
        'distance_options': sorted({o[1] for o in options}),
    }
