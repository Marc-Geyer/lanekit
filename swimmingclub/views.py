from django.http import HttpResponse
from django.shortcuts import redirect
from translations.registry import VALID_CODES


def robots_txt(request):
    """Disallow the admin and the antibot honeypot trap (see antibot app).

    Compliant crawlers (Googlebot etc.) will skip the trap path entirely;
    anything that requests it anyway gets IP-blocked by HoneypotBlockMiddleware.
    """
    lines = [
        'User-agent: *',
        'Disallow: /admin/',
        'Disallow: /system/',
        '',
    ]
    return HttpResponse('\n'.join(lines), content_type='text/plain')


def set_language(request):
    """
    Store the chosen language code in the session then redirect back.
    Called by the navbar language switcher:
        <a href="{% url 'set_language' %}?lang=uk&next={{ request.path }}">…</a>
    """
    lang = request.GET.get('lang', '')
    if lang in VALID_CODES:
        request.session['lang'] = lang

    # Redirect to ?next= or the HTTP referer, staying on-site only.
    next_url = request.GET.get('next', '')
    if not next_url or next_url.startswith('http'):
        next_url = request.META.get('HTTP_REFERER', '/')
    if next_url.startswith('http'):
        next_url = '/'
    return redirect(next_url)
