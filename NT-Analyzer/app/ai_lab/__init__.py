"""AI Strategy Lab subsystem for NT-Analyzer.

Autonomous research engine that generates, validates, compiles, backtests and
arbitrates NinjaTrader 8 strategies in an isolated sandbox namespace.

Safety invariants enforced project-wide:
    - Historical backtests only. No live, no auto paper.
    - AI never writes into production strategy paths or uses production CELL ids.
    - Sandbox path: ~/Documents/NinjaTrader 8/bin/Custom/Strategies/NT-Analyzer_AI Labstrategies
    - lab_namespace == "AI_SANDBOX", ai_cell_id pattern: AI-CELL-<ROOT>-NNN
"""

from . import paths  # noqa: F401
