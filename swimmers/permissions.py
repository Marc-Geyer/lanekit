"""Permission helpers for person (Swimmer) records."""


def trained_group_ids(user):
    """IDs of all groups in which this user is an active trainer."""
    own = getattr(user, 'swimmer', None)
    if own is None:
        return set()
    from groups.models import GroupMembership
    return set(
        GroupMembership.objects.filter(
            swimmer=own, role=GroupMembership.ROLE_TRAINER, active=True,
        ).values_list('group_id', flat=True)
    )


def can_manage_group_membership(user, group_id):
    """Admins/trainers by profile may manage any group, group trainers only their own."""
    if not user.is_authenticated:
        return False
    return user.profile.is_trainer or group_id in trained_group_ids(user)


def can_edit_swimmer(user, swimmer):
    """Profile trainers, the person themself, and trainers of any group the person is an active member of."""
    if not user.is_authenticated:
        return False
    if user.profile.is_trainer:
        return True
    own = getattr(user, 'swimmer', None)
    if own is not None and own.pk == swimmer.pk:
        return True
    group_ids = trained_group_ids(user)
    if not group_ids:
        return False
    from groups.models import GroupMembership
    return GroupMembership.objects.filter(
        swimmer=swimmer, active=True, group_id__in=group_ids,
    ).exists()
