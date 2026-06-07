from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from training.views import CalendarView
from swimmingclub.views import set_language

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', CalendarView.as_view(), name='calendar'),
    path('set-language/', set_language, name='set_language'),
    path('accounts/', include('accounts.urls')),
    path('swimmers/', include('swimmers.urls')),
    path('groups/', include('groups.urls')),
    path('training/', include('training.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
