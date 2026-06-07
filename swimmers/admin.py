from django.contrib import admin
from .models import Swimmer

@admin.register(Swimmer)
class SwimmerAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'email', 'phone', 'active', 'created_at')
    list_filter = ('active',)
    search_fields = ('first_name', 'last_name', 'email')
    raw_id_fields = ('user',)
