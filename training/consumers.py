import json
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone


# Numeric levels from accounts.permissions.Level (kept literal: that module imports Django models).
ASSISTANT, TRAINER = 2, 3
PLAN_STRUCTURE_ACTIONS = {
    'add_plan_entry', 'delete_plan_entry', 'reorder_plan', 'photo_updated', 'photo_entry_created',
}


class SessionConsumer(AsyncJsonWebsocketConsumer):
    """WebSocket consumer for live attendance and training plan collaboration."""

    async def connect(self):
        self.session_id = self.scope['url_route']['kwargs']['session_id']
        self.room_group = f'session_{self.session_id}'
        user = self.scope['user']

        if not user.is_authenticated:
            await self.close()
            return

        # Only staff of this session's group (assistant, trainer, admin) may listen at all.
        # Swimmers read finished sessions through the regular HTTP views, never live.
        level = await self.get_level()
        if level < ASSISTANT:
            await self.close(code=4403)
            return
        self.is_trainer = True
        self.can_edit_plan = level >= TRAINER

        await self.channel_layer.group_add(self.room_group, self.channel_name)
        await self.accept()

        # Send current state on connect
        state = await self.get_session_state(self.session_id)
        await self.send_json({
            'type': 'init', 'data': state, 'trainer': self.is_trainer,
            'can_edit_plan': self.can_edit_plan,
        })

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.room_group, self.channel_name)

    async def receive_json(self, content):
        # Permissions are re-evaluated for EVERY message: the connection outlives role changes
        # (membership removed, trainer role withdrawn) and must not keep old rights.
        level = await self.get_level()
        if level < ASSISTANT:
            await self.send_json({'type': 'error', 'message': 'Keine Berechtigung'})
            await self.close(code=4403)
            return
        self.can_edit_plan = level >= TRAINER

        action = content.get('action')
        data = content.get('data', {})
        if not isinstance(data, dict):
            return

        # Structuring the plan is trainer-only; assistants may only tick entries off.
        if action in PLAN_STRUCTURE_ACTIONS and not self.can_edit_plan:
            await self.send_json({'type': 'error', 'message': 'Keine Berechtigung'})
            return
        if action == 'update_plan_entry' and not self.can_edit_plan:
            data = {'id': data.get('id'), 'checked': data.get('checked')}
            if data['checked'] is None or data['id'] is None:
                return

        if action == 'update_attendance':

            result = await self.db_update_attendance(data)
            if result is not None:
                await self.channel_layer.group_send(self.room_group, {
                    'type': 'broadcast_attendance',
                    'data': result,
                })
            else:
                await self.send_json({'type': 'error', 'message': 'Keine Berechtigung'})

        elif action == 'add_plan_entry':
            entry = await self.db_add_plan_entry(data)
            await self.channel_layer.group_send(self.room_group, {
                'type': 'broadcast_plan_add',
                'data': entry,
            })

        elif action == 'update_plan_entry':
            entry = await self.db_update_plan_entry(data)
            await self.channel_layer.group_send(self.room_group, {
                'type': 'broadcast_plan_update',
                'data': entry,
            })

        elif action == 'delete_plan_entry':
            await self.db_delete_plan_entry(data)
            await self.channel_layer.group_send(self.room_group, {
                'type': 'broadcast_plan_delete',
                'data': {'id': data['id']},
            })

        elif action == 'update_notes':
            await self.db_update_notes(data)
            await self.channel_layer.group_send(self.room_group, {
                'type': 'broadcast_notes',
                'data': data,
            })

        elif action == 'reorder_plan':
            await self.db_reorder_plan(data)
            await self.channel_layer.group_send(self.room_group, {
                'type': 'broadcast_reorder',
                'data': data,
            })
        elif action == 'sync_attendance':
            result = await self.db_sync_attendance()
            await self.channel_layer.group_send(self.room_group, {
                'type': 'broadcast_sync_attendance',
                'data': result,
            })

        elif action == 'photo_updated':
            # Photo uploads/deletions go through a regular HTTP endpoint
            # (binary data isn't sent over the JSON WebSocket). The client
            # re-broadcasts the resulting entry dict so every connected
            # device updates its view without re-querying the DB.
            entry = await self.db_get_plan_entry(data.get('id'))
            if entry:
                await self.channel_layer.group_send(self.room_group, {
                    'type': 'broadcast_plan_update',
                    'data': entry,
                })

        elif action == 'photo_entry_created':
            # A brand-new plan entry created directly from a photo (see
            # plan_entry_photo_create_view) — same rationale as
            # photo_updated above, but this one is an addition, not an
            # update, so every connected device should insert a new row.
            entry = await self.db_get_plan_entry(data.get('id'))
            if entry:
                await self.channel_layer.group_send(self.room_group, {
                    'type': 'broadcast_plan_add',
                    'data': entry,
                })

        elif action == 'attendance_added':
            # The row itself was created by session_add_swimmer_api; re-read it
            # from the DB (never trust client payloads) and tell everyone.
            att = await self.db_get_attendance(data.get('swimmer_id'))
            if att:
                await self.channel_layer.group_send(self.room_group, {
                    'type': 'broadcast_sync_attendance',
                    'data': {'added': [att], 'removed': []},
                })

        elif action == 'mark_unknown_absent':
            result = await self.db_mark_unknown_absent()
            await self.channel_layer.group_send(self.room_group, {
                'type': 'broadcast_bulk_attendance',
                'data': result,
            })

    # ── Channel layer event handlers ────────────────────────────────────────
    async def broadcast_attendance(self, event):
        await self.send_json({'type': 'attendance_update', 'data': event['data']})

    async def broadcast_plan_add(self, event):
        await self.send_json({'type': 'plan_add', 'data': event['data']})

    async def broadcast_plan_update(self, event):
        await self.send_json({'type': 'plan_update', 'data': event['data']})

    async def broadcast_plan_delete(self, event):
        await self.send_json({'type': 'plan_delete', 'data': event['data']})

    async def broadcast_notes(self, event):
        await self.send_json({'type': 'notes_update', 'data': event['data']})

    async def broadcast_reorder(self, event):
        await self.send_json({'type': 'plan_reorder', 'data': event['data']})

    async def broadcast_sync_attendance(self, event):
        await self.send_json({'type': 'sync_attendance', 'data': event['data']})

    async def broadcast_results(self, event):
        # Sent by the results HTTP views; clients re-fetch the list themselves.
        await self.send_json({'type': 'results_changed', 'data': event['data']})

    async def broadcast_bulk_attendance(self, event):
        await self.send_json({'type': 'bulk_attendance_update', 'data': event['data']})

    # ── Database helpers (run in thread pool) ───────────────────────────────
    @database_sync_to_async
    def get_level(self):
        """The connected user's CURRENT group level for this session (see accounts/permissions.py)."""
        from django.contrib.auth.models import User
        from training.models import SessionInstance
        from accounts import permissions as perm
        try:
            user = User.objects.select_related('profile').get(pk=self.scope['user'].pk)
            instance = SessionInstance.objects.select_related('recurring_session').get(pk=self.session_id)
            return int(perm.group_level(user, instance.recurring_session.group_id))
        except Exception:
            return 0

    @database_sync_to_async
    def db_get_plan_entry(self, entry_id):
        from training.models import TrainingPlanEntry
        entry = TrainingPlanEntry.objects.filter(pk=entry_id, session_id=self.session_id).first()
        return entry.to_dict() if entry else None

    @database_sync_to_async
    def get_session_state(self, session_id):
        from training.models import SessionInstance, Attendance, TrainingPlanEntry
        try:
            instance = SessionInstance.objects.select_related('recurring_session__group').get(pk=session_id)
            entries = [
                e.to_dict() for e in TrainingPlanEntry.objects.filter(session=instance)
            ]
            attendances = [
                a.to_dict()
                for a in Attendance.objects.filter(session=instance)
                .select_related('swimmer', 'marked_by')
                .distinct()
            ]
            return {
                'session_id': instance.pk,
                'trainer_notes': instance.trainer_notes,
                'plan_entries': entries,
                'attendances': attendances,
            }
        except Exception as e:
            return {'error': str(e)}

    @database_sync_to_async
    def db_update_attendance(self, data):
        """Update an attendance row for this session.

        Restricted to swimmers who legitimately belong here: either an active
        member of the session's group, or someone already carrying an
        Attendance row for this exact session (a guest added via
        session_add_swimmer_api, who may not be a group member at all).
        Returns None — and sends no broadcast — if neither applies, so a
        trainer can't fabricate attendance for an unrelated swimmer_id.
        """
        from training.models import SessionInstance, Attendance
        from swimmers.models import Swimmer
        from groups.models import GroupMembership
        from django.contrib.auth.models import User
        session = SessionInstance.objects.select_related('recurring_session__group').get(pk=self.session_id)
        swimmer_id = data['swimmer_id']

        is_group_member = GroupMembership.objects.filter(
            group=session.recurring_session.group, swimmer_id=swimmer_id, active=True,
        ).exists()
        is_existing_guest = Attendance.objects.filter(
            session=session, swimmer_id=swimmer_id,
        ).exists()
        if not (is_group_member or is_existing_guest):
            return None

        swimmer = Swimmer.objects.get(pk=swimmer_id)
        att, _ = Attendance.objects.get_or_create(session=session, swimmer=swimmer)
        att.status = data['status']
        att.notes = data.get('notes', '')
        att.marked_by = User.objects.get(pk=self.scope['user'].pk)
        att.save()
        return att.to_dict()

    @database_sync_to_async
    def db_add_plan_entry(self, data):
        from training.models import SessionInstance, TrainingPlanEntry
        session = SessionInstance.objects.get(pk=self.session_id)
        last = TrainingPlanEntry.objects.filter(session=session).order_by('order').last()
        entry = TrainingPlanEntry.objects.create(
            session=session,
            order=(last.order + 1) if last else 0,
            category=data.get('category', 'main'),
            description=data.get('description', ''),
            distance=data.get('distance', ''),
            intensity=data.get('intensity', ''),
            rest_seconds=data.get('rest_seconds'),
        )
        return entry.to_dict()

    @database_sync_to_async
    def db_update_plan_entry(self, data):
        from training.models import TrainingPlanEntry
        entry = TrainingPlanEntry.objects.get(pk=data['id'], session_id=self.session_id)
        for field in ('description', 'distance', 'intensity', 'rest_seconds', 'category', 'checked'):
            if field in data:
                setattr(entry, field, data[field])
        entry.save()
        return entry.to_dict()

    @database_sync_to_async
    def db_delete_plan_entry(self, data):
        from training.models import TrainingPlanEntry
        TrainingPlanEntry.objects.filter(pk=data['id'], session_id=self.session_id).delete()

    @database_sync_to_async
    def db_reorder_plan(self, data):
        from training.models import TrainingPlanEntry
        # data['order'] is a list of {'id': ..., 'order': ...}
        for item in data.get('order', []):
            TrainingPlanEntry.objects.filter(pk=item['id'], session_id=self.session_id).update(order=item['order'])

    @database_sync_to_async
    def db_update_notes(self, data):
        from training.models import SessionInstance
        SessionInstance.objects.filter(pk=self.session_id).update(trainer_notes=data.get('notes', ''))

    @database_sync_to_async
    def db_get_attendance(self, swimmer_id):
        from training.models import Attendance
        att = (
            Attendance.objects.select_related('swimmer', 'marked_by')
            .filter(session_id=self.session_id, swimmer_id=swimmer_id).first()
        )
        return att.to_dict() if att else None

    @database_sync_to_async
    def db_mark_unknown_absent(self):
        from training.models import SessionInstance, Attendance
        from django.contrib.auth.models import User
        session = SessionInstance.objects.get(pk=self.session_id)
        user = User.objects.get(pk=self.scope['user'].pk)
        qs = Attendance.objects.filter(session=session, status=Attendance.STATUS_UNKNOWN)
        updated = []
        for att in qs:
            att.status = Attendance.STATUS_ABSENT
            att.marked_by = user
            att.save()
            updated.append(att.to_dict())
        return {'updated': updated}

    @database_sync_to_async
    def db_sync_attendance(self):
        from training.models import SessionInstance, Attendance
        from groups.models import GroupMembership

        instance = SessionInstance.objects.select_related(
            'recurring_session__group'
        ).get(pk=self.session_id)
        group = instance.recurring_session.group

        # Active group member IDs right now
        active_ids = set(
            GroupMembership.objects.filter(group=group, active=True, swimmer__active=True)
            .values_list('swimmer_id', flat=True)
        )

        # Existing attendance rows for this session
        existing = {
            a.swimmer_id: a
            for a in Attendance.objects.filter(session=instance)
            .select_related('swimmer')
        }

        added = []
        for sid in active_ids:
            if sid not in existing:
                from swimmers.models import Swimmer
                swimmer = Swimmer.objects.get(pk=sid)
                att = Attendance.objects.create(session=instance, swimmer=swimmer)
                added.append(att.to_dict())

        removed = []
        for sid, att in existing.items():
            if sid not in active_ids and att.status == Attendance.STATUS_UNKNOWN:
                removed.append(sid)
                att.delete()

        return {'added': added, 'removed': removed}
