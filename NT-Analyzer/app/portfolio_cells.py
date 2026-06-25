from __future__ import annotations

import re
from typing import Any, Dict, Optional


LEGACY_PORTFOLIO_SLOTS = 10
TARGET_PORTFOLIO_SLOTS = 15
CELL_ID_PATTERN = re.compile(r"^CELL-(\d{3})$")
PORTFOLIO_ROOT_ORDER = (
    "MGC",
    "MNQ",
    "M2K",
    "M6A",
    "M6B",
    "M6E",
    "M6J",
    "MBT",
    "MCL",
    "MES",
    "MET",
    "MYM",
)
PORTFOLIO_ROOT_INDEX = {
    root: idx for idx, root in enumerate(PORTFOLIO_ROOT_ORDER)
}
EXTRA_PORTFOLIO_SLOTS = TARGET_PORTFOLIO_SLOTS - LEGACY_PORTFOLIO_SLOTS
# Preserve the original 12x10 cell ids (001-120). Extra slots append after the
# legacy range so existing portfolio cards never get renumbered.
LEGACY_CELL_COUNT = len(PORTFOLIO_ROOT_ORDER) * LEGACY_PORTFOLIO_SLOTS
TOTAL_CELL_COUNT = LEGACY_CELL_COUNT + (len(PORTFOLIO_ROOT_ORDER) * EXTRA_PORTFOLIO_SLOTS)


def normalize_root(value: Any) -> str:
    text = str(value or "").strip().upper()
    match = re.match(r"^([A-Z0-9]+)", text)
    return match.group(1) if match else ""


def coerce_slot(value: Any) -> Optional[int]:
    try:
        slot = int(value)
    except (TypeError, ValueError):
        return None
    if 1 <= slot <= TARGET_PORTFOLIO_SLOTS:
        return slot
    return None


def portfolio_root_index(value: Any) -> Optional[int]:
    root = normalize_root(value)
    return PORTFOLIO_ROOT_INDEX.get(root)


def cell_number(value: Any, slot: Any) -> Optional[int]:
    root_index = portfolio_root_index(value)
    slot_no = coerce_slot(slot)
    if root_index is None or slot_no is None:
        return None
    if slot_no <= LEGACY_PORTFOLIO_SLOTS:
        return (root_index * LEGACY_PORTFOLIO_SLOTS) + slot_no
    extra_slot = slot_no - LEGACY_PORTFOLIO_SLOTS
    return LEGACY_CELL_COUNT + (root_index * EXTRA_PORTFOLIO_SLOTS) + extra_slot


def cell_id_for(value: Any, slot: Any) -> str:
    number = cell_number(value, slot)
    if number is None:
        return ""
    return f"CELL-{number:03d}"


def cell_number_from_id(value: Any) -> Optional[int]:
    match = CELL_ID_PATTERN.match(str(value or "").strip().upper())
    if not match:
        return None
    number = int(match.group(1))
    if 1 <= number <= TOTAL_CELL_COUNT:
        return number
    return None


def root_for_cell_id(value: Any) -> str:
    number = cell_number_from_id(value)
    if number is None:
        return ""
    if number <= LEGACY_CELL_COUNT:
        root_index = (number - 1) // LEGACY_PORTFOLIO_SLOTS
    else:
        root_index = (number - LEGACY_CELL_COUNT - 1) // EXTRA_PORTFOLIO_SLOTS
    if 0 <= root_index < len(PORTFOLIO_ROOT_ORDER):
        return PORTFOLIO_ROOT_ORDER[root_index]
    return ""


def slot_for_cell_id(value: Any, root: Any = "") -> Optional[int]:
    number = cell_number_from_id(value)
    if number is None:
        return None
    if number <= LEGACY_CELL_COUNT:
        slot = ((number - 1) % LEGACY_PORTFOLIO_SLOTS) + 1
    else:
        slot = LEGACY_PORTFOLIO_SLOTS + (((number - LEGACY_CELL_COUNT - 1) % EXTRA_PORTFOLIO_SLOTS) + 1)
    if root:
        expected_root = root_for_cell_id(value)
        if expected_root and expected_root != normalize_root(root):
            return None
    return slot


def portfolio_metadata(value: Any, slot: Any, strategy_name: Any = "") -> Dict[str, Any]:
    root = normalize_root(value)
    slot_no = coerce_slot(slot)
    cell_id = cell_id_for(root, slot_no)
    if not root or slot_no is None or not cell_id:
        return {}
    out: Dict[str, Any] = {
        "instrument": root,
        "slot": slot_no,
        "cell_id": cell_id,
    }
    name = str(strategy_name or "").strip()
    if name:
        out["strategy_name"] = name
    return out
