"""Change proposals: swimmers suggest edits to their own person record, trainers/admins decide."""
from datetime import date

from django.utils import timezone

# Everything a swimmer may propose. Deliberately NOT included: e-mail (has its own verified
# flow), `active`, and trainer `notes`.
PROPOSABLE_FIELDS = (
    'first_name', 'last_name', 'phone', 'date_of_birth',
    'emergency_contact_name', 'emergency_contact_phone',
)


def serialise(value):
    return value.isoformat() if isinstance(value, date) else (value or '')


def apply_changes(swimmer, changes):
    """Write proposed values onto the person (only whitelisted fields) and keep the linked
    account in sync, otherwise the next profile save would overwrite them again."""
    for field, value in changes.items():
        if field not in PROPOSABLE_FIELDS:
            continue
        if field == 'date_of_birth':
            value = date.fromisoformat(value) if value else None
        setattr(swimmer, field, value)
    swimmer.save()
    sync_linked_account(swimmer)


def sync_linked_account(swimmer):
    """Person → account (name, phone). The reverse direction already exists as a signal."""
    user = swimmer.user
    if user is None:
        return
    user.first_name = swimmer.first_name
    user.last_name = swimmer.last_name
    user.save()
    if hasattr(user, 'profile'):
        user.profile.phone = swimmer.phone
        user.profile.save()


def review(change_request, reviewer, approve):
    from .models import PersonChangeRequest
    if change_request.status != PersonChangeRequest.STATUS_PENDING:
        return False
    if approve:
        apply_changes(change_request.swimmer, change_request.changes)
    change_request.status = (
        PersonChangeRequest.STATUS_APPROVED if approve else PersonChangeRequest.STATUS_REJECTED
    )
    change_request.reviewed_by = reviewer
    change_request.reviewed_at = timezone.now()
    change_request.save()
    return True
