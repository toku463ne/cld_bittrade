# Sign Debate — iterated analyst → proposer → critic → judge

Run the agent debate cycle defined in `.claude/agents/` and
`docs/evaluation_criteria.md`. Each round can autonomously gather new
evidence between iterations so the cycle does not stall on
"insufficient evidence" verdicts.

## Arguments

- **topic** (required) — the sign/strategy question to debate. Free text;
  the analyst figures out the scope.
- **max-iter** (optional, default `3`) — hard cap on cycles.

Example: `/sign-debate improve ema_atr_breakout ATR multiplier --max-iter 4`

## Protocol

**Per iteration** (i = 1 … max-iter):

1. **Analyst** — call the `analyst` subagent (via the `Agent` tool with
   `subagent_type: "analyst"`). Brief it with the topic and any evidence
   collected in prior iterations. It returns the per-strategy / per-sign
   number table from `src/backtest/benchmark.md`.

2. **Historian** — call `historian` with the same topic. It looks up
   prior sessions in memory + git log + strategy/sign module headers and
   reports whether a similar change has been attempted before, with sources.
   In iteration ≥ 2, skip this step unless the previous round's judge
   verdict was "Insufficient evidence" *and* the next action surfaced
   a new sub-topic — re-running historian on unchanged context is wasted
   tokens.

3. **Proposer** — call `proposer` with the analyst and historian outputs.
   It returns one concrete proposal in the canonical 6-section format.
   The "Risks" section should explicitly reference any historical
   precedent the historian flagged.

4. **Critic** — call `critic` with the proposer output (plus historian
   output if it flagged repeat-pattern risk). It returns a hole-by-hole
   review with H/M/L severity labels.

5. **Judge** — call `judge` with all of the above. It returns Accept /
   Reject / Insufficient evidence + confidence + falsifier + next action.

**Process the judge verdict:**

- `Accept` → stop. Report the final proposal as the recommendation; the
  main thread does not implement automatically (this is user-authorized work).
- `Reject` → stop. Report what was rejected and why; suggest follow-on.
- `Insufficient evidence` → extract the **Next action** field from the
  judge's output and execute it autonomously, then loop.

## Autonomous evidence-gathering rules

The judge's "Next action" can be one of these — execute without asking:

- **Run an existing analysis script.**
  E.g. `uv run --env-file .env.bt python -m src.backtest.analysis.<name> [args]`.
  Capture stdout for the next iteration's analyst.
- **Read benchmark / report files.**
  Add the relevant sections of `src/backtest/benchmark.md` to the evidence pack.
- **Query the DB read-only.** Via `get_session()` + `select(...)` against `.env.bt`.
- **Write a new one-off analysis script** of up to ~250 lines that mirrors
  the structure of an existing script in `src/backtest/analysis/`.
  Place it in `src/backtest/analysis/`. Run it once and feed output forward.

**Do NOT autonomously do any of these — stop and report instead:**

- Modify production sign / strategy / detector code.
- Run anything that mutates the DB (rebench writes, migrations).
- Run a full multi-month rebench (`scripts/rebenchmark_sign.sh`) —
  too long, always ask the user first.
- Anything that would require API keys or external network calls
  beyond the local DB.
- Anything reaching outside this repo.

If the next action falls outside the autonomous list above, stop the
cycle and report the next action as a recommendation for the user.

## Stopping conditions

Stop and report when any of these hold:

- Judge issues Accept or Reject.
- `i = max-iter` reached.
- Judge's next action is outside the autonomous list above.
- An autonomous action fails (script error, missing data) — report the
  error rather than swallowing it.
- Two consecutive iterations produce the same judge verdict with the
  same next action (no progress).

## Final report

At the end, output:

1. **Final verdict** — Accept / Reject / Stopped: <reason>.
2. **Recommended action** — what the user should do next (single sentence).
3. **Evidence trail** — bullet list of what was gathered each round
   (analyst summary, proposer's proposal, critic's main hole, judge
   verdict). One bullet per iteration.
4. **Open questions** — anything the cycle could not resolve.

Keep the final report under ~40 lines. The full transcripts of each
round live in the conversation history if the user wants to re-read.

## Notes

- All five agents (`analyst`, `proposer`, `critic`, `judge`, `historian`)
  reference `docs/evaluation_criteria.md` as the shared rubric.
  Re-read it if the topic touches an unfamiliar dimension.
- The agents are read-only advisors. The main thread (you) does the
  actual file edits and script execution; the agents only produce
  text reports.
- If an agent type is not yet available in this session (newly created
  but Claude Code hasn't reloaded), role-play it inline by following
  the spec in `.claude/agents/<role>.md`.
- Always use `.env.bt` for backtest/analysis runs; never `.env.dev`.
