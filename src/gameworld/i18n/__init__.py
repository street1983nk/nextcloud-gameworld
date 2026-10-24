"""Server texts in the Nextcloud account language (D-25, backend part).

German is the source language and the message ID (gettext principle
"msgid = source text"): services keep raising their German constants, and the
API boundary (exception handlers, response serializers) translates them for the
requesting account. ``catalog_en`` and ``catalog_fr`` map each German constant
to its translation (``MESSAGES``) and each German template with ``{name}``
placeholders to the target template (``TEMPLATES``).

The catalogs import the source modules for their keys, so they are loaded on
the first call (functools.cache) to avoid import cycles.
"""

from __future__ import annotations

import functools
import re
import string
from dataclasses import dataclass

SUPPORTED_LANGUAGES = ("de", "en", "fr")
SOURCE_LANGUAGE = "de"
FALLBACK_LANGUAGE = "en"
# Longer texts are returned untouched without any regex run (T-06-77).
MAX_TRANSLATE_LENGTH = 2000

_FORMATTER = string.Formatter()


def normalize_language(raw: object) -> str:
    """Language code like the frontend: part before ``_`` or ``-``, lower case, only de/en/fr, else en."""
    if not isinstance(raw, str):
        return FALLBACK_LANGUAGE
    base = re.split(r"[_-]", raw.strip(), maxsplit=1)[0].lower()
    return base if base in SUPPORTED_LANGUAGES else FALLBACK_LANGUAGE


def placeholders(template: str) -> frozenset[str]:
    """Names of the ``{name}`` placeholders of a template."""
    return frozenset(name for _, name, _, _ in _FORMATTER.parse(template) if name)


@dataclass(frozen=True)
class _Template:
    pattern: re.Pattern[str]
    target: str


def _compile(source: str) -> re.Pattern[str]:
    """Anchored pattern of a German template; each placeholder is a non-greedy group."""
    parts: list[str] = []
    seen: set[str] = set()
    for literal, name, _, _ in _FORMATTER.parse(source):
        parts.append(re.escape(literal))
        if name is None:
            continue
        if name in seen:
            parts.append(f"(?P={name})")
        else:
            seen.add(name)
            parts.append(f"(?P<{name}>.+?)")
    return re.compile("".join(parts), re.DOTALL)


@dataclass(frozen=True)
class _Catalog:
    messages: dict[str, str]
    templates: tuple[_Template, ...]


def _load_module(language: str) -> tuple[dict[str, str], dict[str, str]]:
    if language == "en":
        from gameworld.i18n import catalog_en as module
    else:
        from gameworld.i18n import catalog_fr as module
    return module.MESSAGES, module.TEMPLATES


@functools.cache
def _catalog(language: str) -> _Catalog:
    messages, templates = _load_module(language)
    compiled = tuple(_Template(_compile(source), target) for source, target in templates.items())
    return _Catalog(dict(messages), compiled)


def translate(text: str, language: str) -> str:
    """German server text in ``language``; unknown texts come back unchanged (German).

    Exact catalog entries win; otherwise the first matching template is used and
    its parameters are inserted unchanged into the target template.
    """
    if language not in SUPPORTED_LANGUAGES:
        language = FALLBACK_LANGUAGE
    if language == SOURCE_LANGUAGE or len(text) > MAX_TRANSLATE_LENGTH:
        return text
    catalog = _catalog(language)
    exact = catalog.messages.get(text)
    if exact is not None:
        return exact
    for template in catalog.templates:
        match = template.pattern.fullmatch(text)
        if match is not None:
            return template.target.format_map(match.groupdict())
    return text


def translate_optional(text: str | None, language: str) -> str | None:
    """``translate`` for optional response fields."""
    return None if text is None else translate(text, language)
