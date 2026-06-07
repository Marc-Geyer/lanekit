"""
locale/helpers.py
══════════════════════════════════════════════════════════════════════════════
Helper used inside Python view code to translate flash messages and other
strings that cannot use template variables.

Usage
─────
    from translations.helpers import tr

    # Simple key
    messages.success(request, tr(request, 'msg_profile_updated'))

    # Key with placeholders
    messages.success(request, tr(request, 'msg_swimmer_added', name=swimmer.full_name))
    messages.success(request, tr(request, 'msg_exception_saved', date=str(exc.date)))
══════════════════════════════════════════════════════════════════════════════
"""

from django.conf import settings
from .registry import get_strings, VALID_CODES


def get_lang(request) -> str:
    """Return the active language code for this request."""
    default = getattr(settings, 'DEFAULT_LANGUAGE', 'de')
    lang = request.session.get('lang', default)
    return lang if lang in VALID_CODES else default


def tr(request, key: str, **kwargs) -> str:
    """
    Translate *key* using the current request language.
    Extra keyword arguments are interpolated into the string with str.format().
    Returns the key itself if it is not found (never raises).
    """
    strings = get_strings(get_lang(request))
    text = strings.get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text
