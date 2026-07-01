"""Windows DPAPI-backed local secret storage.

The encrypted payload is tied to the current Windows user.  API responses use
only masks and availability flags; plaintext values never leave this module.
On non-Windows systems the backend is read-only/unavailable unless tests
replace the protect/unprotect functions explicitly.
"""
from __future__ import annotations

import base64
import ctypes
import json
import os
import threading
from ctypes import wintypes
from pathlib import Path
from typing import Dict, Optional, Tuple


_LOCK = threading.RLock()
_MAGIC = b"NTA-DPAPI-1\n"
_ENTROPY = b"StratForgeAI-AgentKeys-v1"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class SecureStoreError(RuntimeError):
    """Safe-to-display secure storage error."""


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def store_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "integrations" / "ai_agent_keys.dpapi"


def available() -> bool:
    return os.name == "nt" and hasattr(ctypes, "windll")


def backend_name() -> str:
    return "Windows DPAPI (CurrentUser)" if available() else "unavailable"


def _blob(data: bytes) -> Tuple[_DATA_BLOB, object]:
    size = max(1, len(data))
    buffer = (ctypes.c_ubyte * size)()
    if data:
        ctypes.memmove(buffer, data, len(data))
    return _DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer


def _protect(data: bytes) -> bytes:
    if not available():
        raise SecureStoreError("Windows DPAPI недоступен на этой системе.")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB), wintypes.LPCWSTR, ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DATA_BLOB),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    source, source_buffer = _blob(data)
    entropy, entropy_buffer = _blob(_ENTROPY)
    output = _DATA_BLOB()
    _ = source_buffer, entropy_buffer
    ok = crypt32.CryptProtectData(
        ctypes.byref(source), "StratForge AI agent keys", ctypes.byref(entropy),
        None, None, _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(output),
    )
    if not ok:
        raise SecureStoreError(f"DPAPI encryption failed ({ctypes.GetLastError()}).")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(output.pbData)


def _unprotect(data: bytes) -> bytes:
    if not available():
        raise SecureStoreError("Windows DPAPI недоступен на этой системе.")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB), ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p,
        wintypes.DWORD, ctypes.POINTER(_DATA_BLOB),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    source, source_buffer = _blob(data)
    entropy, entropy_buffer = _blob(_ENTROPY)
    output = _DATA_BLOB()
    description = wintypes.LPWSTR()
    _ = source_buffer, entropy_buffer
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(source), ctypes.byref(description), ctypes.byref(entropy),
        None, None, _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(output),
    )
    if not ok:
        raise SecureStoreError(
            "Не удалось расшифровать API-ключи: файл принадлежит другому Windows-пользователю или повреждён."
        )
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        if description:
            kernel32.LocalFree(description)
        kernel32.LocalFree(output.pbData)


def _read_all() -> Dict[str, str]:
    path = store_path()
    if not path.is_file():
        return {}
    try:
        raw = path.read_bytes()
        if not raw.startswith(_MAGIC):
            raise SecureStoreError("Неизвестный формат защищённого хранилища ключей.")
        encrypted = base64.b64decode(raw[len(_MAGIC):], validate=True)
        doc = json.loads(_unprotect(encrypted).decode("utf-8"))
    except SecureStoreError:
        raise
    except Exception as exc:
        raise SecureStoreError(f"Не удалось прочитать защищённое хранилище: {exc}") from None
    if not isinstance(doc, dict):
        raise SecureStoreError("Защищённое хранилище имеет некорректную структуру.")
    return {
        str(key): str(value)
        for key, value in doc.items()
        if str(key).strip() and isinstance(value, str) and value
    }


def _write_all(values: Dict[str, str]) -> None:
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    plaintext = json.dumps(values, ensure_ascii=False, sort_keys=True).encode("utf-8")
    payload = _MAGIC + base64.b64encode(_protect(plaintext))
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_bytes(payload)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise SecureStoreError(f"Не удалось сохранить защищённое хранилище: {exc}") from None


def set_secret(secret_id: str, value: str) -> None:
    key = str(secret_id or "").strip()
    secret = str(value or "").strip()
    if not key or not secret:
        raise SecureStoreError("Secret id и значение API-ключа обязательны.")
    with _LOCK:
        values = _read_all()
        values[key] = secret
        _write_all(values)


def get_secret(secret_id: str) -> Optional[str]:
    with _LOCK:
        return _read_all().get(str(secret_id or "").strip())


def delete_secret(secret_id: str) -> bool:
    with _LOCK:
        values = _read_all()
        existed = values.pop(str(secret_id or "").strip(), None) is not None
        if existed:
            _write_all(values)
        return existed


def mask_secret(value: Optional[str]) -> str:
    secret = str(value or "")
    if not secret:
        return ""
    suffix = secret[-4:] if len(secret) >= 4 else secret
    if secret.startswith("sk-"):
        return f"sk-****{suffix}"
    prefix = secret[:3] if len(secret) >= 8 else ""
    return f"{prefix}****{suffix}"


def secret_mask(secret_id: str) -> str:
    return mask_secret(get_secret(secret_id))
