"""Canonical forms for comparing extracted values.

Shared by the synthetic generator (ground truth) and by extraction / rule checks, so both sides
agree on what "the same value" means. The equivalences implemented here mirror policy rule R-2.4.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

_DATE_FORMATS = ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%B %d, %Y", "%b %d, %Y", "%b. %d, %Y")

# Street abbreviations and unit designators -> one canonical word.
_ADDRESS_WORDS = {
    "st": "street",
    "ave": "avenue",
    "av": "avenue",
    "blvd": "boulevard",
    "rd": "road",
    "dr": "drive",
    "ln": "lane",
    "ct": "court",
    "pl": "place",
    "hwy": "highway",
    "pkwy": "parkway",
    "apt": "unit",
    "apartment": "unit",
    "ste": "unit",
    "suite": "unit",
    "n": "north",
    "s": "south",
    "e": "east",
    "w": "west",
}


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_text(text: str) -> str:
    """Lower case, no accents, punctuation turned into spaces, single spaces."""
    cleaned = re.sub(r"[^a-z0-9]+", " ", strip_accents(text).lower())
    return " ".join(cleaned.split())


def normalize_name(name: str) -> str:
    """Normalized person name in "first [middle] last" order.

    Handles "Last, First Middle" and drops accents, case and punctuation. Hyphens become spaces.
    """
    if "," in name:
        last, _, rest = name.partition(",")
        name = f"{rest} {last}"
    cleaned = re.sub(r"['’`]", "", strip_accents(name).lower())
    return normalize_text(cleaned)


def _initial_compatible(a: str, b: str) -> bool:
    return a == b or (len(a) == 1 and b.startswith(a)) or (len(b) == 1 and a.startswith(b))


def names_equivalent(a: str, b: str) -> bool:
    """True when two names denote the same person under rule R-2.4.

    Same first and last name; middle names may be omitted or abbreviated to an initial.
    """
    ta, tb = normalize_name(a).split(), normalize_name(b).split()
    if len(ta) < 2 or len(tb) < 2:
        return ta == tb
    if ta[0] != tb[0] or ta[-1] != tb[-1]:
        return False
    mid_a, mid_b = ta[1:-1], tb[1:-1]
    if not mid_a or not mid_b:
        return True
    shorter, longer = sorted((mid_a, mid_b), key=len)
    return all(_initial_compatible(x, y) for x, y in zip(shorter, longer, strict=False))


def normalize_id(value: str) -> str:
    """Identity number without dots, spaces or dashes, upper case (rule R-2.2)."""
    return re.sub(r"[^A-Z0-9]", "", strip_accents(value).upper())


def normalize_address(address: str) -> str:
    text = strip_accents(address).lower().replace("#", " unit ")
    tokens = re.sub(r"[^a-z0-9]+", " ", text).split()
    return " ".join(_ADDRESS_WORDS.get(token, token) for token in tokens)


def addresses_equivalent(a: str, b: str) -> bool:
    return normalize_address(a) == normalize_address(b)


def normalize_money(value: str) -> Decimal:
    cleaned = value.replace("$", "").replace(",", "").strip()
    try:
        return Decimal(cleaned).quantize(Decimal("0.01"))
    except InvalidOperation:
        raise ValueError(f"not a money amount: {value!r}") from None


def normalize_date(value: str) -> date:
    text = " ".join(value.split())
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognized date: {value!r}")
