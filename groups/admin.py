from django.contrib import admin
from .models import Group, GroupMembership

class MembershipInline(admin.TabularInline):
    model = GroupMembership
    extra = 1
    raw_id_fields = ('swimmer',)

@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'color', 'active', 'created_at')
    list_filter = ('active',)
    inlines = [MembershipInline]

@admin.register(GroupMembership)
class GroupMembershipAdmin(admin.ModelAdmin):
    list_display = ('swimmer', 'group', 'role', 'active', 'joined_date')
    list_filter = ('role', 'active', 'group')
    search_fields = ('swimmer__first_name', 'swimmer__last_name')
