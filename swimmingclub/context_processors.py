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


def trainer_status(request):
    """Expose the user's access level to all templates (see accounts/permissions.py).

    ``is_group_trainer`` – entered as trainer in at least one group (trainer section in the navbar),
    ``is_level_assistant`` / ``is_level_trainer`` / ``is_level_admin`` – global level at least that high,
    ``can_*`` – shortcuts for navigation items.
    Per-object decisions (one group, one person) are made in the views and passed in explicitly.
    """
    from accounts import permissions as perm
    user = getattr(request, 'user', None)
    lvl = perm.level(user)
    own_id = getattr(perm.own_swimmer(user), 'pk', None)
    match = getattr(request, 'resolver_match', None)
    on_own_person = bool(
        own_id and match and match.url_name == 'swimmer_detail' and match.kwargs.get('pk') == own_id
    )
    return {
        'is_group_trainer': perm.can_view_trainer_report(user),
        'access_level': int(lvl),
        'is_level_assistant': lvl >= perm.Level.ASSISTANT,
        'is_level_trainer': lvl >= perm.Level.TRAINER,
        'is_level_admin': lvl >= perm.Level.ADMIN,
        'can_create_group': perm.can_create_group(user),
        'can_create_exception': perm.can_create_exception(user),
        'own_swimmer_id': own_id,
        'nav_on_own_person': on_own_person,   # "My profile" is the active nav item, not "People"
    }
