from datetime import timedelta

from django.core.cache import cache
from django.http import HttpResponseNotFound
from django.utils import timezone

from .middleware import CACHE_PREFIX, client_ip
from .models import BlockedIP

BLOCK_DURATION = timedelta(hours=24)


def honeypot_trap_view(request):
    """The honeypot itself.

    Nothing a real visitor can click leads here: the only link to this URL
    is hidden off-screen in base.html (aria-hidden, no tab stop), and the
    path is disallowed in robots.txt so compliant crawlers skip it too.
    Anything that still requests it is, by construction, either ignoring
    robots.txt or blindly following every <a href> in the raw HTML — never
    a human. Blocks the requester's IP for 24h and always answers 404, so
    the caller gets no signal that anything out of the ordinary happened.
    """
    ip = client_ip(request)
    if ip:
        existing = BlockedIP.objects.filter(ip_address=ip).order_by('-created_at').first()
        if existing is not None:
            existing.blocked_until = timezone.now() + BLOCK_DURATION
            existing.hit_path = request.path
            existing.user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]
            existing.hit_count += 1
            existing.save(update_fields=['blocked_until', 'hit_path', 'user_agent', 'hit_count'])
        else:
            BlockedIP.objects.create(
                ip_address=ip,
                hit_path=request.path,
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
                blocked_until=timezone.now() + BLOCK_DURATION,
            )
        # Close the race against the 60s cache TTL so the block applies
        # from this requester's very next request, not just eventually.
        cache.delete(CACHE_PREFIX + ip)
    return HttpResponseNotFound()
