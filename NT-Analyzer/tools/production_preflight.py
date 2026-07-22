"""Fail-closed, secret-safe preflight for the Linux Production service."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import sys
from typing import Dict, Iterable, Iterator, Mapping

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import runtime_env, storage_router
from app.production_storage import StorageError, reset_for_tests


_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")


def parse_environment_file(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            raise ValueError(f"invalid environment assignment at line {number}")
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not _ENV_NAME.fullmatch(name):
            raise ValueError(f"invalid environment name at line {number}")
        if value[:1] in {"'", '"'}:
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f"unterminated quote at line {number}")
            value = value[1:-1]
        values[name] = value
    return values


@contextmanager
def temporary_environment(values: Mapping[str, str]) -> Iterator[None]:
    original = {name: os.environ.get(name) for name in values}
    os.environ.update({str(name): str(value) for name, value in values.items()})
    try:
        yield
    finally:
        for name, value in original.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _check(name: str, ok: bool, code: str) -> Dict[str, object]:
    return {"name": name, "ok": bool(ok), "code": str(code)}


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def run_preflight(
    *,
    app_root: Path,
    environment_file: Path | None = None,
    allow_non_linux: bool = False,
    require_binaries: Iterable[str] = ("systemctl", "cloudflared"),
) -> Dict[str, object]:
    checks = []
    env_values: Dict[str, str] = {}
    if environment_file is not None:
        try:
            env_values = parse_environment_file(environment_file)
            checks.append(_check("environment_file_syntax", True, "ok"))
        except (OSError, UnicodeError, ValueError):
            checks.append(_check("environment_file_syntax", False, "invalid"))
            return {"ok": False, "checks": checks}
        if os.name == "posix":
            mode = stat.S_IMODE(environment_file.stat().st_mode)
            checks.append(_check(
                "environment_file_permissions",
                not bool(mode & 0o077),
                "ok" if not bool(mode & 0o077) else "must_be_0600",
            ))

    with temporary_environment(env_values):
        reset_for_tests()
        try:
            config = runtime_env.assert_startup_safe()
            checks.append(_check("typed_config", True, "ok"))
        except runtime_env.RuntimeEnvError:
            checks.append(_check("typed_config", False, "rejected"))
            return {"ok": False, "checks": checks}

        if config.environment == runtime_env.PRODUCTION:
            try:
                storage_router.assert_production_storage_safe()
                checks.append(_check("production_storage_config", True, "ok"))
            except StorageError:
                checks.append(_check("production_storage_config", False, "rejected"))

            artifact_raw = str(os.environ.get("STRATFORGE_ARTIFACT_ROOT") or "").strip()
            artifact_root = Path(artifact_raw).expanduser().resolve() if artifact_raw else None
            artifact_ready = bool(
                artifact_root
                and artifact_root.is_dir()
                and os.access(str(artifact_root), os.R_OK | os.W_OK | os.X_OK)
            )
            checks.append(_check(
                "artifact_storage_root", artifact_ready,
                "ok" if artifact_ready else "missing_or_not_writable",
            ))

        linux = platform.system().lower() == "linux"
        checks.append(_check(
            "linux_runtime", linux or allow_non_linux,
            "ok" if linux else ("test_override" if allow_non_linux else "linux_required"),
        ))

        root = app_root.resolve()
        app_files_ok = (root / "app" / "server.py").is_file() and (
            root / "requirements.txt"
        ).is_file()
        checks.append(_check("application_release", app_files_ok, "ok" if app_files_ok else "incomplete"))

        data_root = Path(config.data_root).resolve()
        data_ok = data_root.is_dir()
        checks.append(_check("data_root", data_ok, "ok" if data_ok else "missing"))
        separated = root != data_root and root not in data_root.parents
        checks.append(_check(
            "release_data_separation", separated,
            "ok" if separated else "data_inside_release",
        ))
        if config.environment == runtime_env.PRODUCTION:
            artifact_raw = str(os.environ.get("STRATFORGE_ARTIFACT_ROOT") or "").strip()
            artifact_root = Path(artifact_raw).expanduser().resolve() if artifact_raw else root
            artifact_separated = (
                artifact_root != root
                and not _is_within(artifact_root, root)
                and artifact_root != data_root
                and not _is_within(artifact_root, data_root)
                and not _is_within(data_root, artifact_root)
            )
            checks.append(_check(
                "artifact_storage_separation", artifact_separated,
                "ok" if artifact_separated else "artifact_root_not_isolated",
            ))

        loopback_bind = config.bind_host in {"127.0.0.1", "::1"}
        edge_safe = config.edge_mode == "cloudflare-tunnel" and loopback_bind
        checks.append(_check(
            "private_origin", edge_safe,
            "ok" if edge_safe else "cloudflare_loopback_required",
        ))

        for binary in require_binaries:
            found = bool(shutil.which(str(binary)))
            checks.append(_check(
                f"binary_{binary}", found, "ok" if found else "missing",
            ))

    reset_for_tests()
    return {"ok": all(bool(item["ok"]) for item in checks), "checks": checks}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", type=Path, default=Path.cwd())
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--allow-non-linux", action="store_true")
    parser.add_argument("--skip-runtime-binaries", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = run_preflight(
        app_root=args.app_root,
        environment_file=args.env_file,
        allow_non_linux=args.allow_non_linux,
        require_binaries=() if args.skip_runtime_binaries else ("systemctl", "cloudflared"),
    )
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        for item in result["checks"]:
            state = "PASS" if item["ok"] else "FAIL"
            print(f"{state} {item['name']} ({item['code']})")
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
