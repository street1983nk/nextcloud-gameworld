"""Dump every server-side text per language as JSON for the language audit.

Sources (German is the source language and the catalog key):
- gameworld.i18n.catalog_en / catalog_fr: MESSAGES and TEMPLATES (API texts)
- gameworld.provisioner.access_mod.MOD_TEXTS: in-game texts of gameworld_access
- gameworld.provisioner.time_mod.MOD_TEXTS: in-game texts of gameworld_time
- gameworld.notify.texts.NOTIFY_TEXTS / BOT_TEXTS: Nextcloud notifications, Talk bot
- gameworld.backup.naming.PRE_RESTORE_SUFFIXES: backup name suffix per language

Usage: uv run python scripts/audit/dump_catalog.py [out.json]   (default .dev/audit/server.json)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from gameworld.backup import naming
from gameworld.i18n import catalog_en, catalog_fr
from gameworld.notify import texts as notify_texts
from gameworld.provisioner import access_mod, time_mod

LANGS = ("de", "en", "fr")


def _flatten(value: object) -> list[str]:
    """All strings inside a (nested) NamedTuple / tuple / str."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, (tuple, list)):
        return [s for item in value for s in _flatten(item)]
    return []


def collect() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {lang: [] for lang in LANGS}
    out["de"] += list(catalog_en.MESSAGES) + list(catalog_en.TEMPLATES)
    out["de"] += list(catalog_fr.MESSAGES) + list(catalog_fr.TEMPLATES)
    out["en"] += list(catalog_en.MESSAGES.values()) + list(catalog_en.TEMPLATES.values())
    out["fr"] += list(catalog_fr.MESSAGES.values()) + list(catalog_fr.TEMPLATES.values())
    for table in (access_mod.MOD_TEXTS, time_mod.MOD_TEXTS, notify_texts.NOTIFY_TEXTS, notify_texts.BOT_TEXTS):
        for lang in LANGS:
            if lang in table:
                out[lang] += _flatten(table[lang])
    for lang in LANGS:
        out[lang].append(naming.PRE_RESTORE_SUFFIXES[lang])
    return out


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else ".dev/audit/server.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    data = collect()
    target.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print({k: len(v) for k, v in data.items()})


if __name__ == "__main__":
    main()
