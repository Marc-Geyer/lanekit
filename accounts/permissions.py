"""Central access-control rules for LaneKit.

EVERY access decision in views, consumers and templates goes through this
module.  Never test ``profile.role`` / ``GroupMembership.role`` directly in a
view – add (or reuse) a ``can_*`` function here instead, and register new
endpoints in ``accounts/test_permissions.py`` (a guard test fails otherwise).

Access levels (low → high)
--------------------------
ANONYMOUS  not logged in. Calendar with group names only.
SWIMMER    logged in, no trainer role anywhere. Own profile + statistics,
           finished sessions they took part in. Cannot edit anything directly;
           may *propose* changes to their own person record.
ASSISTANT  (Hilfstrainer) profile says "swimmer" but the person is entered as
           trainer in at least one group. Only in THOSE groups: may operate
           the session modal (attendance, notes, swim times, add people to the
           session) but only tick off – never create/edit/delete – plan entries.
           Sees name + age of the group's members, nothing more.
TRAINER    profile says "trainer". Sees name + age of everybody and, for EVERY group,
           who belongs to it and which recurring sessions it has (read-only roster;
           group pills in the people list). Full access (read + write) to persons,
           sessions, statistics and memberships of the groups they are trainer of
           only: other groups give no deeper insight (no session modal, attendance,
           notes, plan, contact data, statistics). Swim times may only be entered
           for people in their own sessions. Non-members: basic info + swim-time
           statistics only.
ADMIN      everything.

Two kinds of level exist:

* the *global* level (:func:`level`) – used for navigation and list views;
* the *group* level (:func:`group_level`) – what the user may do inside one
  concrete group.  A profile-TRAINER is only TRAINER in groups where they are
  entered as trainer; everywhere else they are SWIMMER.
"""
from datetime import datetime
from enum import IntEnum

from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone


class Level(IntEnum):
    ANONYMOUS = 0
    SWIMMER = 1
    ASSISTANT = 2
    TRAINER = 3
    ADMIN = 4


class PersonAccess(IntEnum):
    NONE = 0     # may not open the record at all
    BASIC = 1    # name, age and swim-time statistics
    FULL = 2     # everything that is not trainer-internal (contact data, groups, attendance)


class SessionView(IntEnum):
    NONE = 0
    PARTICIPANT = 1   # finished session the user took part in: read-only, own data only
    STAFF = 2         # ASSISTANT or higher in the session's group


# ── Basics ───────────────────────────────────────────────────────────────────

def is_authenticated(user):
    return bool(user is not None and user.is_authenticated)


def is_admin(user):
    return is_authenticated(user) and bool(user.is_superuser or user.profile.role == 'admin')


def is_profile_trainer(user):
    """Profile status "trainer" (admins are handled separately via :func:`is_admin`)."""
    return is_authenticated(user) and user.profile.role == 'trainer'


def own_swimmer(user):
    """The person record linked to this account, or None."""
    if not is_authenticated(user):
        return None
    try:
        return user.swimmer
    except ObjectDoesNotExist:
        return None


def trainer_membership_group_ids(user):
    """Groups in which the user's person is an active trainer (regardless of profile status)."""
    own = own_swimmer(user)
    if own is None:
        return set()
    from groups.models import GroupMembership
    return set(
        GroupMembership.objects.filter(
            swimmer=own, role=GroupMembership.ROLE_TRAINER, active=True,
        ).values_list('group_id', flat=True)
    )


def level(user):
    """Global level – for navigation and list views, not for per-group decisions."""
    if not is_authenticated(user):
        return Level.ANONYMOUS
    if is_admin(user):
        return Level.ADMIN
    if is_profile_trainer(user):
        return Level.TRAINER
    if trainer_membership_group_ids(user):
        return Level.ASSISTANT
    return Level.SWIMMER


def group_level(user, group_id):
    """What the user may do inside ``group_id``."""
    if not is_authenticated(user):
        return Level.ANONYMOUS
    if is_admin(user):
        return Level.ADMIN
    if group_id in trainer_membership_group_ids(user):
        return Level.TRAINER if is_profile_trainer(user) else Level.ASSISTANT
    return Level.SWIMMER


def groups_at_least(user, minimum):
    """IDs of all groups in which the user has at least ``minimum`` group level."""
    if not is_authenticated(user):
        return set()
    if is_admin(user):
        from groups.models import Group
        return set(Group.objects.values_list('pk', flat=True))
    ids = trainer_membership_group_ids(user)
    own_level = Level.TRAINER if is_profile_trainer(user) else Level.ASSISTANT
    return ids if own_level >= minimum else set()


def active_member_group_ids(swimmer):
    from groups.models import GroupMembership
    return set(
        GroupMembership.objects.filter(swimmer=swimmer, active=True).values_list('group_id', flat=True)
    )


# ── Groups ───────────────────────────────────────────────────────────────────

def can_create_group(user):
    """Create / delete groups: admin only."""
    return is_admin(user)


def roster_group_ids(user):
    """Groups whose composition (who is a member, which recurring sessions) the user may see:
    every group for trainers and admins, the own groups for assistants, none otherwise.
    Read-only insight – everything deeper needs :func:`group_level`."""
    if not is_authenticated(user):
        return set()
    if level(user) >= Level.TRAINER:
        from groups.models import Group
        return set(Group.objects.values_list('pk', flat=True))
    return groups_at_least(user, Level.ASSISTANT)


def can_view_group(user, group_id):
    """Group detail page (members, recurring sessions, read-only unless you manage the group):
    trainers/admins for every group, assistants for the groups they assist."""
    if not is_authenticated(user):
        return False
    return level(user) >= Level.TRAINER or group_level(user, group_id) >= Level.ASSISTANT


def can_manage_group(user, group_id):
    """Edit the group, its recurring sessions and exceptions, see its statistics,
    add/remove members, hand out the trainer role, create people into it."""
    return group_level(user, group_id) >= Level.TRAINER


def can_view_group_stats(user, group_id):
    return can_manage_group(user, group_id)


def can_view_group_member_details(user, group_id):
    """Contact data and notes of a group's members (name + age are always visible to staff)."""
    return can_manage_group(user, group_id)


# ── Calendar / sessions ──────────────────────────────────────────────────────

def can_view_calendar_details(user):
    """Location, cancellation reasons and the session modal. Anonymous: group names only."""
    return is_authenticated(user)


def can_operate_session(user, group_id):
    """Everything in the session modal except structuring the plan:
    start the session, attendance, notes, lanes, swim times, add people, excuse links."""
    return group_level(user, group_id) >= Level.ASSISTANT


def can_check_plan_entries(user, group_id):
    return group_level(user, group_id) >= Level.ASSISTANT


def can_edit_plan(user, group_id):
    """Create / edit / delete / reorder plan entries and their photos."""
    return group_level(user, group_id) >= Level.TRAINER


def can_create_exception(user):
    """Exception form is available to everybody who may create one for at least one group."""
    return is_admin(user) or bool(groups_at_least(user, Level.TRAINER))


def exception_group_ids(user):
    """Groups for which the user may create exceptions."""
    return groups_at_least(user, Level.TRAINER)


def can_create_global_exception(user):
    """An exception that affects ALL sessions: admin only."""
    return is_admin(user)


def trainer_report_group_ids(user):
    """Groups the user is (or was) entered as trainer in – deliberately NOT limited to active
    memberships, so a trainer who left mid-quarter can still report the sessions they led."""
    own = own_swimmer(user)
    if own is None:
        return set()
    from groups.models import GroupMembership
    return set(
        GroupMembership.objects.filter(swimmer=own, role=GroupMembership.ROLE_TRAINER)
        .values_list('group_id', flat=True)
    )


def can_view_trainer_report(user):
    """Quarterly time-reporting overview: anyone entered as trainer in a group
    (assistants included; the report only ever lists the user's own sessions)."""
    return bool(trainer_report_group_ids(user))


def session_end_datetime(instance):
    rs = instance.recurring_session
    naive = datetime.combine(instance.date, rs.end_time)
    return timezone.make_aware(naive) if timezone.is_naive(naive) else naive


def session_is_finished(instance, now=None):
    return (now or timezone.now()) >= session_end_datetime(instance)


def session_view(user, instance, now=None):
    """How may ``user`` look at this session instance?"""
    if not is_authenticated(user):
        return SessionView.NONE
    if can_operate_session(user, instance.recurring_session.group_id):
        return SessionView.STAFF
    own = own_swimmer(user)
    if own is None or not session_is_finished(instance, now):
        return SessionView.NONE
    took_part = instance.attendances.filter(swimmer=own).exists()
    is_member = instance.recurring_session.group_id in active_member_group_ids(own)
    return SessionView.PARTICIPANT if (took_part or is_member) else SessionView.NONE


def swimmer_on_session(instance, swimmer_id):
    """May attendance / times / excuse links be recorded for this person on this session?
    Only active members of the session's group and people already on its attendance list
    (guests added via the session). Nobody else, however trainer-ish the caller is."""
    from groups.models import GroupMembership
    if GroupMembership.objects.filter(
        group_id=instance.recurring_session.group_id, swimmer_id=swimmer_id, active=True,
    ).exists():
        return True
    return instance.attendances.filter(swimmer_id=swimmer_id).exists()


# ── Swim times ───────────────────────────────────────────────────────────────

def can_manage_result(user, result):
    """Correct / delete one recorded time.

    Times that belong to a session: whoever operates that session.
    Times without a session (competitions, imports): admin only."""
    if result.session_id:
        return can_operate_session(user, result.session.recurring_session.group_id)
    return is_admin(user)


def can_record_results(user, instance):
    """Enter times for the people on a session's attendance list (checked per swimmer in the view)."""
    return can_operate_session(user, instance.recurring_session.group_id)


# ── Persons ──────────────────────────────────────────────────────────────────

def can_view_person_list(user):
    return level(user) >= Level.ASSISTANT


def visible_people(user, queryset):
    """Restrict a Swimmer queryset to the people the user may see in the list (name + age)."""
    lvl = level(user)
    if lvl >= Level.TRAINER:
        return queryset
    if lvl == Level.ASSISTANT:
        from groups.models import GroupMembership
        return queryset.filter(pk__in=GroupMembership.objects.filter(
            group_id__in=groups_at_least(user, Level.ASSISTANT), active=True,
        ).values('swimmer_id'))
    return queryset.none()


def person_access(user, swimmer):
    if not is_authenticated(user):
        return PersonAccess.NONE
    if is_admin(user):
        return PersonAccess.FULL
    own = own_swimmer(user)
    if own is not None and own.pk == swimmer.pk:
        return PersonAccess.FULL
    member_of = active_member_group_ids(swimmer)
    if groups_at_least(user, Level.TRAINER) & member_of:
        return PersonAccess.FULL
    if is_profile_trainer(user):
        return PersonAccess.BASIC            # any person, but only the basics
    if groups_at_least(user, Level.ASSISTANT) & member_of:
        return PersonAccess.BASIC
    return PersonAccess.NONE


def can_view_person(user, swimmer):
    return person_access(user, swimmer) >= PersonAccess.BASIC


def can_view_person_details(user, swimmer):
    """Contact data, emergency contact, group memberships."""
    return person_access(user, swimmer) >= PersonAccess.FULL


def can_view_person_performance(user, swimmer):
    return person_access(user, swimmer) >= PersonAccess.BASIC


def can_view_person_attendance_stats(user, swimmer):
    return person_access(user, swimmer) >= PersonAccess.FULL


def attendance_stats_group_ids(user, swimmer):
    """Which groups' sessions may enter this person's attendance statistics for this viewer."""
    own = own_swimmer(user)
    if is_admin(user) or (own is not None and own.pk == swimmer.pk):
        from groups.models import Group
        return set(Group.objects.values_list('pk', flat=True))
    return groups_at_least(user, Level.TRAINER) & active_member_group_ids(swimmer)


def can_edit_person(user, swimmer):
    """Direct editing: admin, or trainer of a group the person is an active member of.
    Swimmers and assistants never edit directly (swimmers propose, see below)."""
    if not is_authenticated(user):
        return False
    if is_admin(user):
        return True
    return bool(groups_at_least(user, Level.TRAINER) & active_member_group_ids(swimmer))


def can_view_person_notes(user, swimmer):
    """Trainer notes on a person are trainer-internal."""
    return can_edit_person(user, swimmer)


def can_propose_person_change(user, swimmer):
    """Swimmers propose changes to their OWN record when they cannot edit it directly."""
    own = own_swimmer(user)
    return own is not None and own.pk == swimmer.pk and not can_edit_person(user, swimmer)


def can_review_person_change(user, swimmer):
    """Accept / reject a proposal: admin, or trainer of a group of the person (never the proposer's own)."""
    return can_edit_person(user, swimmer)


def can_review_proposals(user):
    """Is there anything this user could ever decide on? (Notification bell + overview page.)"""
    return is_admin(user) or bool(groups_at_least(user, Level.TRAINER))


def reviewable_change_requests(user):
    """Open change proposals the user may accept or reject – exactly those for which
    :func:`can_review_person_change` is true: everything for admins, otherwise proposals of people
    who are active members of a group the user is TRAINER of."""
    from groups.models import GroupMembership
    from swimmers.models import PersonChangeRequest
    pending = PersonChangeRequest.objects.filter(
        status=PersonChangeRequest.STATUS_PENDING).select_related('swimmer', 'proposed_by')
    if is_admin(user):
        return pending
    group_ids = groups_at_least(user, Level.TRAINER)
    if not group_ids:
        return pending.none()
    members = GroupMembership.objects.filter(group_id__in=group_ids, active=True).values('swimmer_id')
    return pending.filter(swimmer_id__in=members)


def can_create_person(user, group_id=None):
    """Create a person. Admin: anywhere. Trainer: only into one of their own groups."""
    if is_admin(user):
        return True
    return group_id is not None and group_id in groups_at_least(user, Level.TRAINER)


def creatable_group_ids(user):
    return groups_at_least(user, Level.TRAINER)


def can_add_person_to_group(user, swimmer, group_id):
    """Add (or re-activate, or change the role of) a membership. Needs manage rights in the
    target group and the right to see the person at all."""
    return can_manage_group(user, group_id) and can_view_person(user, swimmer)


def can_remove_person_from_group(user, group_id):
    return can_manage_group(user, group_id)


def can_assign_group_trainer(user, group_id):
    """Hand out the trainer role inside a group – trainers of THAT group only."""
    return can_manage_group(user, group_id)


def can_add_person_to_session(user, group_id):
    """Put an existing person on a session's attendance list (guests included)."""
    return can_operate_session(user, group_id)


def can_create_person_in_session(user, group_id):
    """Create a brand-new person from within a session. Creating people is a trainer right
    (the person joins the group), never an assistant right."""
    return can_create_person(user, group_id)


# ── Accounts ─────────────────────────────────────────────────────────────────

def can_manage_accounts(user):
    """User list, roles, linking accounts to people: admin only."""
    return is_admin(user)


def can_lock_person_fields(user):
    """True when name/phone on the account form must be read-only because they sync to a
    person record the user may not edit directly."""
    own = own_swimmer(user)
    return own is not None and not can_edit_person(user, own)
