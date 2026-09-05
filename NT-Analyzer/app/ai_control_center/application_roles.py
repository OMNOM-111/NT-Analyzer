"""Explicit Persona assignment to existing application adapters, not authority.

These stable role keys do not grant capabilities, select credentials or create
another permission system. Existing NT/Desktop admission remains authoritative.
Legacy profiles without an assignment stay unassigned; names never imply roles.
"""
from .states import ContractError

ROLES = {
    "backtest_researcher": {"kind": "backtest", "legacy_id": "tolik", "label": "Бэктестирование"},
    "chart_researcher": {"kind": "chart", "legacy_id": "ivan", "label": "Рабочий стол и графики"},
}


def role_key(value):
    if type(value) is not str or (value and value not in ROLES):
        raise ContractError("invalid_application_role")
    return value


def for_kind(kind):
    return next((key for key, spec in ROLES.items() if spec["kind"] == kind), "")
