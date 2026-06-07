"""
locale package – LaneKit translation system.

Quick reference
───────────────
  In Python (views):       from translations.helpers import tr
  In templates:            {{ t.some_key }}
  Language files:          locale/en.py  de.py  uk.py  ar.py
  Add a language:          locale/registry.py  (one import + one tuple)
"""
from .registry import get_strings, LANGUAGES_DISPLAY, VALID_CODES, RTL_LANGUAGES
from .helpers import tr, get_lang

__all__ = ['get_strings', 'LANGUAGES_DISPLAY', 'VALID_CODES',
           'RTL_LANGUAGES', 'tr', 'get_lang']
