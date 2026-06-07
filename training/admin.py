from django.contrib import admin
from .models import (
    RecurringSession, SessionException, SessionInstance,
    TrainingPlanEntry, Attendance, ExcuseToken
)


class PlanEntryInline(admin.TabularInline):
    model = TrainingPlanEntry
    extra = 1


class AttendanceInline(admin.TabularInline):
    model = Attendance
    extra = 0
    raw_id_fields = ('swimmer',)


@admin.register(RecurringSession)
class RecurringSessionAdmin(admin.ModelAdmin):
    list_display = ('group', 'get_day_of_week_display', 'start_time', 'end_time', 'location', 'active')
    list_filter = ('group', 'active', 'day_of_week')


@admin.register(SessionException)
class SessionExceptionAdmin(admin.ModelAdmin):
    list_display = ('date', 'reason', 'affects_all')
    filter_horizontal = ('affected_sessions',)


@admin.register(SessionInstance)
class SessionInstanceAdmin(admin.ModelAdmin):
    list_display = ('recurring_session', 'date', 'created_by', 'created_at')
    list_filter = ('recurring_session__group',)
    inlines = [PlanEntryInline, AttendanceInline]


@admin.register(ExcuseToken)
class ExcuseTokenAdmin(admin.ModelAdmin):
    list_display = ('swimmer', 'recurring_session', 'date', 'used', 'created_at')
    list_filter = ('used',)


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ('swimmer', 'session', 'status', 'marked_by', 'marked_at')
    list_filter = ('status',)
    search_fields = ('swimmer__first_name', 'swimmer__last_name')
