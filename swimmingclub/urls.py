from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
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

# In development Daphne does not serve static/media files automatically
# (unlike `runserver`), so we wire them into the URL router explicitly.
# staticfiles_urlpatterns() is a no-op when DEBUG=False, so this is safe
# to leave in place – production traffic goes through nginx instead.
if settings.DEBUG:
    urlpatterns += staticfiles_urlpatterns()
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
