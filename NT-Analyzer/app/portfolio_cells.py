from __future__ import annotations

import re
from typing import Any, Dict, Optional


TARGET_PORTFOLIO_SLOTS = 10
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
    return (root_index * TARGET_PORTFOLIO_SLOTS) + slot_no


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
    max_number = len(PORTFOLIO_ROOT_ORDER) * TARGET_PORTFOLIO_SLOTS
    if 1 <= number <= max_number:
        return number
    return None


def root_for_cell_id(value: Any) -> str:
    number = cell_number_from_id(value)
    if number is None:
        return ""
    root_index = (number - 1) // TARGET_PORTFOLIO_SLOTS
    if 0 <= root_index < len(PORTFOLIO_ROOT_ORDER):
        return PORTFOLIO_ROOT_ORDER[root_index]
    return ""


def slot_for_cell_id(value: Any, root: Any = "") -> Optional[int]:
    number = cell_number_from_id(value)
    if number is None:
        return None
    slot = ((number - 1) % TARGET_PORTFOLIO_SLOTS) + 1
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