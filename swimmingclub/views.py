from django.shortcuts import redirect
from translations.registry import VALID_CODES


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
