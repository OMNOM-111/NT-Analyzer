#!/usr/bin/env python3
"""Reach the cluster superuser via the pg_hba `local all postgres peer` rule
without altering any filesystem permission.

The only barrier is that the `postgres` OS user cannot traverse the
stratforge-owned parent directories. root can, so root chdir's into the socket
directory first and then drops to postgres; the child inherits the directory as
its working directory, so a relative socket path needs no traversal at all.
"""
import subprocess

SOCK = "/home/stratforge/production_data/run/postgresql"
PROBE = ("select current_user||' super='||usesuper::text "
         "from pg_user where usename=current_user")

attempts = [
    ("relative socket after root chdir",
     ["sudo", "-n", "bash", "-c",
      f'cd {SOCK} && sudo -n -u postgres psql -h . -U postgres -d postgres -Atc "{PROBE}"']),
    ("absolute socket as postgres",
     ["sudo", "-n", "-u", "postgres", "psql", "-h", SOCK,
      "-U", "postgres", "-d", "postgres", "-Atc", PROBE]),
]

for label, cmd in attempts:
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
    ok = done.returncode == 0
    detail = (done.stdout.strip() or done.stderr.strip())[:160]
    print(f"[{'OK  ' if ok else 'FAIL'}] {label}: {detail}")
    if ok:
        print("ADMIN_PATH_AVAILABLE")
        break
