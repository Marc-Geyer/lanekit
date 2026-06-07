"""
translations/registry.py
══════════════════════════════════════════════════════════════════════════════
Central registry + safe fallback dict.

Adding a new language
─────────────────────
1. Create  translations/xx.py  (copy en.py, translate values).
2. Import it here and add one tuple to LANGUAGES.
3. If RTL, add its code to RTL_LANGUAGES.
══════════════════════════════════════════════════════════════════════════════
"""

import logging
from django.conf import settings

from . import en, de, uk, ar

logger = logging.getLogger('translations')

# ── Language registry ─────────────────────────────────────────────────────────
# (code, display_name, flag_emoji, module)
LANGUAGES = [
    ('en', 'English',    '🇬🇧', en),
    ('de', 'Deutsch',    '🇩🇪', de),
    ('uk', 'Українська', '🇺🇦', uk),
    ('ar', 'العربية',   '🇸🇦', ar),
]

RTL_LANGUAGES: set[str] = {'ar'}

_MODULES: dict = {code: mod for code, _, _, mod in LANGUAGES}
LANGUAGES_DISPLAY: list[tuple] = [(code, name, flag) for code, name, flag, _ in LANGUAGES]
VALID_CODES: set[str] = set(_MODULES.keys())


class TranslationDict(dict):
    """
    A dict that never raises KeyError or VariableDoesNotExist.

    When a template references {{ t.some_key }} and that key is missing:
    - Logs a WARNING so you can spot it immediately in the dev server console
    - In DEBUG mode: returns a visible  ⚠ [key_name]  marker in the page
    - In production:  returns the raw key name (always something readable)

    This means a forgotten translation key degrades gracefully instead of
    crashing the page.
    """

    def __missing__(self, key: str) -> str:
        logger.warning(
            "Missing translation key '%s' – add it to all language files "
            "in translations/",
            key,
        )
        if getattr(settings, 'DEBUG', False):
            return f'⚠ [{key}]'
        return key  # production: unobtrusive fallback


def get_strings(lang_code: str) -> TranslationDict:
    """
    Return a merged TranslationDict for *lang_code*.
    Missing keys fall back to the default language first, then to the
    key name itself (via TranslationDict.__missing__).
    """
    default = getattr(settings, 'DEFAULT_LANGUAGE', 'de')
    base    = getattr(_MODULES.get(default), 'STRINGS', {})
    target  = getattr(_MODULES.get(lang_code), 'STRINGS', {})
    return TranslationDict({**base, **target})