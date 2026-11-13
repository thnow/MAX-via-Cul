"""Translation files: complete, consistent and matching the error keys in the code."""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import string
import subprocess

import pytest

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
        # hassfest rejects placeholders in single quotes
        for value in (str(text), str(de[key])):
            assert not re.search(r"'\{[^}]+\}'", value), key


def test_other_languages_fit_the_english_source() -> None:
    """Any further translations/<lang>.json: only known keys, same placeholders.

    Missing keys are fine – Home Assistant falls back to English for them.
    """
    en = _flat(_load("translations/en.json"))
    for path in sorted((BASE / "translations").glob("*.json")):
        if path.name in ("en.json", "de.json"):
            continue
        other = _flat(json.loads(path.read_text(encoding="utf-8")))
        unknown = set(other) - set(en)
        assert not unknown, f"{path.name}: unknown keys {sorted(unknown)[:5]}"
        for key, text in other.items():
            assert _placeholders(str(text)) == _placeholders(str(en[key])), f"{path.name}: {key}"
            assert not re.search(r"'\{[^}]+\}'", str(text)), f"{path.name}: {key}"


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


CARD_TABLES = {
    "cul-max-queue-card.js": ["Q_TEXT"],
    "cul-max-pairing-card.js": ["P_TEXT"],
    "cul-max-vacation-card.js": ["V_TEXT"],
    "cul-max-week-profile-card.js": ["W_TEXT", "DAY_NAMES", "MODE_NAMES"],
}


def _missing(english: dict, other: dict, path: str = "") -> list[str]:
    """Entries of `english` missing in `other` (recursively)."""
    out = []
    for key, spec in english["keys"].items():
        if key not in other["keys"]:
            out.append(f"{path}{key}")
        elif spec["type"] == "object":
            out += _missing(spec, other["keys"][key], f"{path}{key}.")
    return out


def _mismatches(english: dict, other: dict, path: str = "") -> list[str]:
    """Entries of `other` that do not exist in English or differ in kind."""
    out = []
    for key, spec in other["keys"].items():
        ref = english["keys"].get(key)
        if ref is None:
            out.append(f"{path}{key}: not in English")
        elif ref["type"] != spec["type"]:
            out.append(f"{path}{key}: {spec['type']} instead of {ref['type']}")
        elif spec["type"] == "function" and spec["arity"] != ref["arity"]:
            out.append(f"{path}{key}: takes {spec['arity']} values instead of {ref['arity']}")
        elif spec["type"] == "object":
            out += _mismatches(ref, spec, f"{path}{key}.")
    return out


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.parametrize("card", sorted(CARD_TABLES))
def test_card_texts_fit_the_english_texts(card: str) -> None:
    """Every language block of a card has the shape of the English one; German is complete."""
    result = subprocess.run(
        ["node", str(BASE / "tests" / "card_texts.js"), str(BASE / "frontend" / card), *CARD_TABLES[card]],
        capture_output=True, text=True, check=True,
    )
    tables = json.loads(result.stdout)
    for name, languages in tables.items():
        english = languages["en"]
        for lang, texts in languages.items():
            assert not _mismatches(english, texts), f"{card} {name}.{lang}: {_mismatches(english, texts)}"
        assert not _missing(english, languages["de"]), f"{card} {name}.de missing {_missing(english, languages['de'])}"
