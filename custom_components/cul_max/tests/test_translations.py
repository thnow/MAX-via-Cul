"""Translation files: complete, consistent and matching the error keys in the code."""

from __future__ import annotations

import json
import pathlib
import re
import string

BASE = pathlib.Path(__file__).resolve().parents[1]


def _load(name: str) -> dict:
    return json.loads((BASE / name).read_text(encoding="utf-8"))


def _flat(data: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            out.update(_flat(value, f"{prefix}{key}."))
        else:
            out[f"{prefix}{key}"] = value
    return out


def _placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_strings_json_is_the_english_source() -> None:
    assert _load("strings.json") == _load("translations/en.json")


def test_german_and_english_have_the_same_keys_and_placeholders() -> None:
    de, en = _flat(_load("translations/de.json")), _flat(_load("translations/en.json"))
    assert set(de) == set(en)
    for key, text in en.items():
        assert _placeholders(str(text)) == _placeholders(str(de[key])), key


def test_every_error_key_in_the_code_is_translated() -> None:
    from custom_components.cul_max.errors import MESSAGES

    exceptions = _load("translations/en.json")["exceptions"]
    german = _load("translations/de.json")["exceptions"]
    used: set[str] = set()
    for path in BASE.glob("*.py"):
        used |= set(re.findall(r'CulMaxError\(\s*"([a-z0-9_]+)"', path.read_text(encoding="utf-8")))
    assert used, "no CulMaxError found"
    assert used <= set(exceptions), used - set(exceptions)
    assert used <= set(german), used - set(german)
    for key in used:
        assert MESSAGES[key] == exceptions[key]["message"], key
