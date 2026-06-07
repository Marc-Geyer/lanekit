from django.conf import settings


def branding(request):
    """Inject APP_NAME and ORGANISATION_NAME into every template context."""
    return {
        'APP_NAME': getattr(settings, 'APP_NAME', 'LaneKit'),
        'ORGANISATION_NAME': getattr(settings, 'ORGANISATION_NAME', ''),
        'SITE_TITLE': getattr(settings, 'ORGANISATION_NAME', '') or getattr(settings, 'APP_NAME', 'LaneKit'),
    }


def i18n(request):
    """
    Inject translation strings and language metadata into every template.

    Template variables provided:
      {{ t.some_key }}   – translated string for the current language
      {{ lang }}         – active language code  e.g. 'de'
      {{ is_rtl }}       – True when the language reads right-to-left (Arabic)
      {{ LANGUAGES }}    – list of (code, name, flag) for the navbar switcher
    """
    from translations.registry import get_strings, LANGUAGES_DISPLAY, RTL_LANGUAGES, VALID_CODES
    default = getattr(settings, 'DEFAULT_LANGUAGE', 'de')
    lang = request.session.get('lang', default)
    if lang not in VALID_CODES:
        lang = default
    return {
        't':         get_strings(lang),
        'lang':      lang,
        'is_rtl':    lang in RTL_LANGUAGES,
        'LANGUAGES': LANGUAGES_DISPLAY,
    }
