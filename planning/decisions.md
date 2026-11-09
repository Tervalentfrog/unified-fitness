# Decisions and open questions

Proposed for review on 2026-11-09. These choices can change after source inspection.

| Decision | Reason / trade-off |
| --- | --- |
| Python 3.11+, src layout, setuptools, pip/venv, pytest | Familiar packaging with a small toolchain. No runtime dependencies until features need them; no lockfile until dependencies are installed and validated. |
| Standard-library CLI, SQLite, CSV, and dataclasses | Enough for personal exports; avoid ORM, pandas, Pydantic, and orchestration frameworks until a concrete need appears. |
| One account per source, one database, synchronous operation | Avoid account registries, workers, and concurrency concerns. Additional accounts require a namespace change before import. |
| Separate runs and strength sets | Preserve different measurement semantics. Shared reporting functions can combine dates without a universal activity hierarchy. |
| Date-based strength analysis initially | Avoid fabricated sessions. Multiple workouts on one day remain one training day unless real session identity supports more. |
| Upsert by source identity; retain absent records | Handles repeats and corrections without accidental deletes. Imports are not full synchronization; older exports can overwrite newer values. |
| Inspect formats before writing importers | IDs, units, date formats, and completion flags cannot be safely guessed from product names. |
| Predefined analytics before AI | Calculations remain independently testable and useful offline. AI adds an interface and interpretation, not authority over stored facts. |
| Direct OpenAI SDK with strict tool schemas, added later | Small integration surface. No free-form SQL, agent framework, embeddings, vector database, or stored chat history. |
| Environment variables; no dotenv dependency initially | Avoid configuration layers. `.env.example` is documentation; a local `.env` is not automatically loaded. |

## Risks and validation gates

| Risk / uncertainty | Validation or mitigation |
| --- | --- |
| FitNotes backup format and schema version are unknown | Inspect a real file read-only. Identify keys and relations; reject unknown/incompatible schemas before any destination writes. |
| IDs may not survive app restore, or identical sets may lack identity | Compare backups if available. Never collapse records by metric equality; define fallback behavior before supporting a format without stable keys. |
| Weight, completion, and exercise semantics differ | Check global/per-exercise units, planned vs completed sets, renamed exercises, assisted/bodyweight movements, and distance/time records. Count unsupported rows. |
| Strava CSV layout and units vary | Inspect actual export headers and representative values; do not assume a particular CSV schema is guaranteed by bulk export documentation. |
| Date-only and timezone-less history | Preserve precision, require explicit assumptions, and do not invent UTC timestamps. Confirm `Asia/Singapore` and handling of historical travel. |
| Partial histories distort trends | Report coverage and rejected/missing records. Absence of imported workouts does not demonstrate rest. Avoid causal or medical claims. |
| Local-first can be mistaken for fully offline | Imports and reports stay local; AI questions and selected results leave the machine. Explain this boundary and review provider data handling at integration time. |
| Model mistakes, injected source text, API failure/cost | Fixed read-only tools, application-side validation, bounded calls/results, fake API tests, visible errors, configurable model, and optional live evaluation. |
| Personal files accidentally committed | Ignore data/exports/credentials, keep only invented fixtures, and inspect staged content. Arbitrary text files can still contain sensitive data. |
| Interpreter unavailable in current shell | Resolve Python before package installation or tests. No dependency installation or passing Python checks are claimed at kickoff. |
| Named timezone database unavailable on some systems | Check `zoneinfo` support when normalizing timestamps; add `tzdata` if needed, particularly on Windows. Never silently fall back to the machine timezone. |

## Open questions for source validation

1. Which FitNotes app/version produced the backup, and what stable keys, unit
   overrides, completion markers, and dates does the file actually contain?
2. Does the personal Strava export contain a usable activities CSV with stable IDs,
   unambiguous distance/duration fields, and sufficient timestamp information?
3. Should all weekly reports use Singapore calendar dates and Monday-start weeks?
   How should older naive timestamps and travel be interpreted?
4. Are observed load/reps, running volume/pace, and distinct training days sufficient
   for the first report set? Which exercise and question should anchor acceptance?

These questions gate the relevant implementation, not project initialization.
Model choice and API spend limits can wait until deterministic analytics work.

## Deferred scope

OAuth/live sync, scraping, automatic scheduling, cloud deployment, multi-user auth,
GPS/splits/heart-rate streams, FIT/GPX/TCX parsing, web UI, automatic exercise alias
merging, cross-provider activity matching, session inference, deletion reconciliation,
training plans, estimated 1RM, causal modeling, and production infrastructure.
No extra formats or dependencies unless the validated MVP workflow requires them.

## Source checks

Reviewed on 2026-11-09; documentation does not replace inspecting actual exports.

- [FitNotes settings](https://www.fitnotesapp.com/settings/): documents `.fitnotes`
  backups, CSV export, per-exercise unit overrides, and completion tracking. It does
  not establish the SQLite table schema or stored historical unit semantics.
- [Strava export documentation](https://support.strava.com/en-us/articles/15401919-how-do-i-export-my-strava-data):
  confirms official bulk account export; the actual CSV contract remains unverified.
- [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling):
  strict schemas constrain tool arguments; the application still executes tools and
  validates their meaning. Use explicit strict mode and compatible schemas.
