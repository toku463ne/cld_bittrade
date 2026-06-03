"""Bar-based trade simulator (DO NOT use backtrader — see CLAUDE.md).

Implements the two-bar fill rule: a signal fires at the close of bar T and is
filled at the open of bar T+1. Exits are evaluated bar-by-bar via
:mod:`src.exit.rules`.
"""

from src.simulator.multi_simulator import MultiSimulator
from src.simulator.simulator import SimResult, Simulator

__all__ = ["Simulator", "SimResult", "MultiSimulator"]
