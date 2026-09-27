"""Minimal loopback HTTP entrypoint for the isolated Preview sandbox.

Unlike ``app.server.run`` this process intentionally starts no background
worker, Telegram consumer, market-data transport, AI model, tunnel or Connector
service.  It serves the exact same Handler and Aurora assets against an isolated
synthetic data root.
"""
from __future__ import annotations

import argparse
import signal
import threading
from http.server import ThreadingHTTPServer

from . import preview_sandbox, runtime_env


class PreviewHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def run(port: int) -> None:
    preview_sandbox.require_enabled()
    deployment = runtime_env.assert_startup_safe()
    preview_sandbox.install_network_guard()

    # Import after the environment and outbound-network guards are established.
    # Handler remains the production Handler; only process identity/data differ.
    from . import server as application_server

    httpd = PreviewHTTPServer(("127.0.0.1", int(port)), application_server.Handler)
    httpd.deployment_config = deployment  # type: ignore[attr-defined]

    def stop(_signum: int, _frame: object) -> None:
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, stop)
        except (OSError, ValueError):
            pass
    print(f"[preview-sandbox] ready http://127.0.0.1:{port}/ui/", flush=True)
    def exit_when_requested():
        preview_sandbox._EXIT_RESPONSE_SENT.wait()
        httpd.shutdown()
    threading.Thread(target=exit_when_requested, daemon=True, name="preview-exit").start()
    try:
        httpd.serve_forever(poll_interval=0.2)
    finally:
        httpd.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="StratForge isolated Preview sandbox")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    if not 1024 <= int(args.port) <= 65535:
        raise SystemExit("Preview port out of range")
    run(int(args.port))


if __name__ == "__main__":
    main()
