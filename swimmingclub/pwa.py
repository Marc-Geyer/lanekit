"""PWA endpoints: web app manifest + service worker.

The service worker MUST be served from the site root (/sw.js) so its scope
covers the whole app – a file under /static/ could only control /static/.
"""
import json

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.views.decorators.cache import never_cache

# Bump to force clients to drop old caches.
SW_VERSION = 'v1'


@never_cache
def manifest(request):
    name = getattr(settings, 'ORGANISATION_NAME', '') or getattr(settings, 'APP_NAME', 'LaneKit')
    app_name = getattr(settings, 'APP_NAME', 'LaneKit')
    data = {
        'name': f'{name} · {app_name}' if getattr(settings, 'ORGANISATION_NAME', '') else app_name,
        'short_name': app_name,
        'description': 'Swimming groups, training sessions and live attendance',
        'id': '/',
        'start_url': '/',
        'scope': '/',
        'display': 'standalone',
        'orientation': 'any',
        'background_color': '#1e2327',
        'theme_color': '#1e2327',
        'icons': [
            {'src': static('icons/icon-192.png'), 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any'},
            {'src': static('icons/icon-512.png'), 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any'},
            {'src': static('icons/icon-maskable-512.png'), 'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'},
        ],
    }
    return JsonResponse(data, content_type='application/manifest+json')


@never_cache
def service_worker(request):
    precache = [static('css/custom.css'), static('js/calendar.js'), static('js/session.js'),
                static('icons/icon-192.png'), '/offline/']
    js = render(request, 'pwa/sw.js', {'version': SW_VERSION, 'precache_json': json.dumps(precache)}).content
    resp = HttpResponse(js, content_type='application/javascript')
    resp['Service-Worker-Allowed'] = '/'
    return resp


def offline(request):
    return render(request, 'pwa/offline.html')
