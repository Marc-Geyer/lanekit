from django.core.cache import cache
from django.http import HttpResponseForbidden
from django.utils import timezone

CACHE_PREFIX = 'antibot:blocked:'
CACHE_TTL = 60  # seconds; worst case a freshly-blocked IP gets one more request through


def client_ip(request):
    """Best-effort real client IP behind the nginx reverse proxy.

    nginx sets X-Real-IP ($remote_addr, a single address — not a comma list
    like X-Forwarded-For) on every proxied location; fall back to
    REMOTE_ADDR for direct/dev access without nginx in front.
    """
    return request.META.get('HTTP_X_REAL_IP') or request.META.get('REMOTE_ADDR', '')


class HoneypotBlockMiddleware:
    """Rejects requests from IPs that have tripped the honeypot trap.

    Placed right after SecurityMiddleware (see settings.py MIDDLEWARE) so a
    blocked request never reaches sessions, auth, CSRF or any view — cheap
    for the attacker to hit, cheap for us to reject. A short-lived cache
    entry means a blocked IP's repeat requests don't hit the database.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        ip = client_ip(request)
        if ip and self._is_blocked(ip):
            return HttpResponseForbidden('Forbidden')
        return self.get_response(request)

    def _is_blocked(self, ip):
        cache_key = CACHE_PREFIX + ip
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        from .models import BlockedIP
        blocked = BlockedIP.objects.filter(
            ip_address=ip, blocked_until__gt=timezone.now(),
        ).exists()
        cache.set(cache_key, blocked, CACHE_TTL)
        return blocked
