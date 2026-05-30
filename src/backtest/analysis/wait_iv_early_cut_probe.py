"""Reference template: faithful composite-walk probe.

This is the reference probe the agent specs (`.claude/agents/proposer.md`,
`critic.md`, `judge.md`) point to for any entry/exit-timing change against a
band-based exit (ATR trail, fixed TP/SL). It is a TEMPLATE — copy and adapt it
when a debate's "Next action" requires a probe (see
`.claude/commands/sign-debate.md`).

A faithful composite walk:

1. Simulates the live exit bar-by-bar from ``open[fire+1]`` (two-bar fill).
2. Fires on whichever triggers first: live TP, live SL, OR the proposed gate.
3. Records per-event: ``r_at_gate``, MFE pre-gate, MAE pre-gate, terminal_r
   under baseline (no gate) AND under policy (with gate).
4. Reports mechanism (a) survivor-inflation vs (b) real-time-identifiable
   discrimination: ``mean_r|not_cut`` vs baseline, ``MFE|cut`` vs ``|MAE|cut``.

The pre-registered accept gate, frac_acted bounds and the sign-flip falsifier
cell MUST be written in the docstring of any concrete copy BEFORE it is run.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.core.types import Bar, ExitConfig, Side
from src.exit.rules import OpenPosition, evaluate_exit


@dataclass(frozen=True, slots=True)
class CompositeWalkRow:
    """Per-event record from a composite walk."""

    fired_at_idx: int
    side: Side
    r_at_gate: float
    mfe_pre_gate: float
    mae_pre_gate: float
    terminal_r_baseline: float
    terminal_r_policy: float
    cut_by_gate: bool


def composite_walk(
    bars: list[Bar],
    entry_idx: int,
    side: Side,
    entry_atr: float,
    exit_cfg: ExitConfig,
    *,
    gate_bars: int | None = None,
) -> CompositeWalkRow:
    """Walk one event under baseline and a (placeholder) early-cut gate.

    Args:
        bars: Full bar series.
        entry_idx: Signal bar index (entry fills at ``bars[entry_idx+1].open``).
        side: Trade direction.
        entry_atr: ATR at the signal bar (for ATR-based exit sizing).
        exit_cfg: The live exit configuration.
        gate_bars: Placeholder gate — cut after this many bars if not yet exited.
            Replace with the real gate condition in a concrete probe.

    Returns:
        A :class:`CompositeWalkRow` discriminating mechanism (a) vs (b).
    """
    if entry_idx + 1 >= len(bars):
        return CompositeWalkRow(entry_idx, side, 0.0, 0.0, 0.0, 0.0, 0.0, False)

    entry_price = bars[entry_idx + 1].open
    pos = OpenPosition(side=side, entry_price=entry_price, entry_atr=entry_atr)
    sign = side.sign

    mfe = mae = 0.0
    terminal_baseline = 0.0
    terminal_policy = 0.0
    cut = False
    r_at_gate = 0.0

    for offset, bar in enumerate(bars[entry_idx + 1 :], start=0):
        r = sign * (bar.close - entry_price) / entry_price
        mfe = max(mfe, r)
        mae = min(mae, r)

        # Policy: early-cut gate (placeholder = bar count).
        if not cut and gate_bars is not None and pos.bars_held >= gate_bars:
            cut = True
            r_at_gate = r
            terminal_policy = r

        exit_result = evaluate_exit(pos, bar, exit_cfg)
        if exit_result is not None:
            _, exit_price = exit_result
            terminal_baseline = sign * (exit_price - entry_price) / entry_price
            if not cut:
                terminal_policy = terminal_baseline
            break
        pos.bars_held += 1
    else:
        terminal_baseline = sign * (bars[-1].close - entry_price) / entry_price
        if not cut:
            terminal_policy = terminal_baseline

    return CompositeWalkRow(
        fired_at_idx=entry_idx,
        side=side,
        r_at_gate=r_at_gate,
        mfe_pre_gate=mfe,
        mae_pre_gate=mae,
        terminal_r_baseline=terminal_baseline,
        terminal_r_policy=terminal_policy,
        cut_by_gate=cut,
    )
