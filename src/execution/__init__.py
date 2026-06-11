"""Live bitFlyer execution layer (CLAUDE.md step 12).

Currently **read-only**: an authenticated client for account / position / order /
execution *monitoring*. Order placement is intentionally disabled — the strategies
are still forward-ACCRUING (no confirmed live record), and per CLAUDE.md trading is
human-executed at the 0.001 minimum lot only *after* the benchmark passes.
"""
