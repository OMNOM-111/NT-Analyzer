"""Canonical MNQ Research Hub ladder entrypoint.

The legacy run_mnq_cell020_session_edge_ladder.py module contains the shared
implementation and remains callable for old notes/jobs. New research should use
this filename so the process is not tied to CELL-020.
"""
from __future__ import annotations

import run_mnq_cell020_session_edge_ladder as ladder


if __name__ == "__main__":
    ladder.main()
