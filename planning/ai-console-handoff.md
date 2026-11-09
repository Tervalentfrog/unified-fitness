# One-tool AI console handover

Open a fresh Codex session in `C:\dev\unified-fitness` and paste the brief below.

## Implementation brief

Implement the one-tool AI console described in the
[implementation plan](implementation-plan.md#next-slice-one-tool-ai-console).
Read AGENTS.md, the [architecture](architecture.md#analytics-and-ai-boundary),
README, pyproject.toml, and the existing code and tests. Check Git status
before editing. The offline implementation baseline is commit `3404908`.

FitNotes and Strava ingestion, SQLite v2, and the offline weekly report are
already working. The latest baseline run passed all 46 tests. Use
`analytics.weekly_summary` for the tool result. The console exposes one
allowlisted function, `get_weekly_summary`, with two required ISO dates.
Use the official OpenAI Docs to verify the Responses API contract during
implementation. Add the SDK as an optional dependency and keep offline
commands usable without it.

Fix the known aggregate edge cases before connecting the tool. A positive
subnormal distance can underflow when converted to kilometers, and summing
large finite values can produce infinity. Add regression tests and enforce
finite JSON at the provider boundary.

Follow the plan's request budget, remote processing disclosure, and data
boundary. Keep the database path local and show deterministic evidence
separately from model commentary. Use a fake API client and invented SQLite
fixtures for default tests. Live calls require separate authorization. Keep
private data under ignored `data/` and credentials in the environment.

Run the Windows venv pytest suite and relevant offline CLI smoke checks.
Update the README and plan with actual verification results and remaining
limits. Stop after this slice for review.
