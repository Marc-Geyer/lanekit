import json
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone


class SessionConsumer(AsyncJsonWebsocketConsumer):
    """WebSocket consumer for live attendance and training plan collaboration."""

    async def connect(self):
        self.session_id = self.scope['url_route']['kwargs']['session_id']
        self.room_group = f'session_{self.session_id}'
        user = self.scope['user']

        if not user.is_authenticated:
            await self.close()
            return

        # Verify user is a trainer of this session's group
        is_trainer = await self.check_is_trainer(user, self.session_id)
        self.is_trainer = is_trainer

        await self.channel_layer.group_add(self.room_group, self.channel_name)
        await self.accept()

        # Send current state on connect
        state = await self.get_session_state(self.session_id)
        await self.send_json({'type': 'init', 'data': state})

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.room_group, self.channel_name)

    async def receive_json(self, content):
        if not self.is_trainer:
            await self.send_json({'type': 'error', 'message': 'Keine Berechtigung'})
            return

        action = content.get('action')
        data = content.get('data', {})

        if action == 'update_attendance':
            result = await self.db_update_attendance(data)
            await self.channel_layer.group_send(self.room_group, {
                'type': 'broadcast_attendance',
                'data': result,
            })

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

    # ── Database helpers (run in thread pool) ───────────────────────────────
    @database_sync_to_async
    def check_is_trainer(self, user, session_id):
        from training.models import SessionInstance
        from groups.models import GroupMembership
        try:
            instance = SessionInstance.objects.select_related('recurring_session__group').get(pk=session_id)
            if user.profile.is_admin:
                return True
            if not hasattr(user, 'swimmer'):
                return False
            return GroupMembership.objects.filter(
                group=instance.recurring_session.group,
                swimmer=user.swimmer,
                role=GroupMembership.ROLE_TRAINER,
                active=True,
            ).exists()
        except Exception:
            return False

    @database_sync_to_async
    def get_session_state(self, session_id):
        from training.models import SessionInstance, Attendance, TrainingPlanEntry
        try:
            instance = SessionInstance.objects.select_related('recurring_session__group').get(pk=session_id)
            entries = list(TrainingPlanEntry.objects.filter(session=instance).values(
                'id', 'order', 'category', 'description', 'distance', 'intensity', 'rest_seconds'
            ))
            attendances = [a.to_dict() for a in Attendance.objects.filter(session=instance).select_related('swimmer', 'marked_by')]
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
        from training.models import SessionInstance, Attendance
        from swimmers.models import Swimmer
        from django.contrib.auth.models import User
        session = SessionInstance.objects.get(pk=self.session_id)
        swimmer = Swimmer.objects.get(pk=data['swimmer_id'])
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
        for field in ('description', 'distance', 'intensity', 'rest_seconds', 'category'):
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
