from django.contrib import admin
from .models import BlockedIP


@admin.register(BlockedIP)
class BlockedIPAdmin(admin.ModelAdmin):
    list_display = ('ip_address', 'is_active', 'hit_count', 'hit_path', 'blocked_until', 'created_at')
    list_filter = ('reason',)
    search_fields = ('ip_address', 'hit_path', 'user_agent')
    readonly_fields = ('created_at',)
    ordering = ('-created_at',)

    @admin.display(boolean=True, description='aktiv')
    def is_active(self, obj):
        return obj.is_active
