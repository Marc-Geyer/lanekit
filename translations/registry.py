"""
locale/registry.py
══════════════════════════════════════════════════════════════════════════════
Central registry that wires the per-language modules together.

Adding a new language
─────────────────────
1. Create  locale/xx.py  (copy en.py as a starting point, translate values).
2. Import it below.
3. Add one tuple to LANGUAGES.
4. If RTL, add its code to RTL_LANGUAGES.
5. Done – it will appear in the navbar switcher automatically.
══════════════════════════════════════════════════════════════════════════════
"""

from django.conf import settings

# ── Import one module per language ────────────────────────────────────────────
from . import en
from . import de
from . import uk
from . import ar

# ── Language registry ─────────────────────────────────────────────────────────
# Each entry:  (code, display_name, flag_emoji, module)
# The code must match a key in _MODULES below and the session value.
LANGUAGES = [
    ('en', 'English',    '🇬🇧', en),
    ('de', 'Deutsch',    '🇩🇪', de),
    ('uk', 'Українська', '🇺🇦', uk),
    ('ar', 'العربية',   '🇸🇦', ar),
]

# Codes whose script flows right-to-left (Bootstrap RTL CSS is loaded for these)
RTL_LANGUAGES: set[str] = {'ar'}

# ── Internal lookup helpers ───────────────────────────────────────────────────
_MODULES: dict = {code: mod for code, _, _, mod in LANGUAGES}

# Display tuples without the module (used in templates / context processor)
LANGUAGES_DISPLAY: list[tuple] = [(code, name, flag) for code, name, flag, _ in LANGUAGES]

VALID_CODES: set[str] = set(_MODULES.keys())


def get_strings(lang_code: str) -> dict:
    """
    Return a merged strings dict for *lang_code*.

    Missing keys fall back to the default language so the UI never shows
    a raw key even when a translation is incomplete.
    """
    default = getattr(settings, 'DEFAULT_LANGUAGE', 'de')
    base = getattr(_MODULES.get(default), 'STRINGS', {})
    target = getattr(_MODULES.get(lang_code), 'STRINGS', {})
    return {**base, **target}
