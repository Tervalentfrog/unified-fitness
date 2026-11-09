# Decisions and open questions

FitNotes discovery recommendations accepted by the user on 2026-11-09. Remaining
source uncertainties are validation work, not confirmed encoding assumptions.

[FitNotes discovery](fitnotes-discovery.md) now records the first inspected backup
and accepted model adjustments. Those decisions are not implemented.

| Decision | Reason / trade-off |
| --- | --- |
| Python 3.11+, src layout, setuptools, pip/venv, pytest | Familiar packaging with a small toolchain. No runtime dependencies until features need them; no lockfile until dependencies are installed and validated. |
| Standard-library CLI, SQLite, CSV, and dataclasses | Enough for personal exports; avoid ORM, pandas, Pydantic, and orchestration frameworks until a concrete need appears. |
| One account per source, one database, synchronous operation | Avoid account registries, workers, and concurrency concerns. Additional accounts require a namespace change before import. |
| Separate runs and strength sets | Preserve different measurement semantics. Shared reporting functions can combine dates without a universal activity hierarchy. |
| Date-based strength analysis initially | Avoid fabricated sessions. Multiple workouts on one day remain one training day unless real session identity supports more. |
| Reps-focused first FitNotes report | Report per-exercise sets/repetitions and recorded training days. Zero source loads do not justify normalized load, bodyweight, or volume claims. |
| Preserve source codes and flags | Keep exercise type/unit codes and set unit/completion/pending flags alongside raw load; keep schema/settings/completion policy in existing import metadata. Import only referenced exercise definitions. |
| Completion policy scoped to the inspected backup | Its sets were confirmed performed, so neither raw flag filters them out. Future backups need a documented policy; the current app setting cannot establish historical completion. |
| Leave unverified values unset | Normalized load/unit, load kind, and set order remain NULL. No extra sessions table or timed/distance-based FitNotes support until justified by validated examples. |
| Three tables for the first slice | Create import audit, referenced exercises, and sets now; add running activities with Strava. No unused feature tables. |
| Explicit performed-set assertion | Require an import option and record it. Confirmation already exists for the inspected backup; do not assume future files are all performed or embed private IDs in code. |
| Bounded source support and normalization | Validate source version 22; accept type 0 with zero distance/duration, preserve raw load/codes, normalize IDs/dates/reps, and leave physical conversions unknown. Report other records as unsupported. |
| Idempotence applies to domain rows | Repeat imports do not mutate exercises/sets or their last-change provenance. A new audit entry records each committed attempt; counters count source set rows only. |
| Upsert by source identity; retain absent records | Handles repeats and corrections without accidental deletes. Imports are not full synchronization; older exports can overwrite newer values. |
| Preserve valid data on incomplete or malformed updates | Absent optional columns preserve stored values; malformed optional updates reject the record. Only source-defined explicit empties clear a field. |
| Singapore reporting dates and Monday-start weeks (confirmed) | One timezone per database avoids mixing differently calculated dates. A timezone change requires an explicit rebuild/reimport for the MVP. Date-only history stays date-only. |
| Inspect formats before writing importers | IDs, units, date formats, and completion flags cannot be safely guessed from product names. |
| Predefined analytics before AI | Calculations remain independently testable and useful offline. AI adds an interface and interpretation, not authority over stored facts. |
| Direct OpenAI SDK with strict tool schemas, added later | Small integration surface. No free-form SQL, agent framework, embeddings, vector database, or stored chat history. |
| Environment variables; no dotenv dependency initially | Avoid configuration layers. `.env.example` is documentation; a local `.env` is not automatically loaded. |

## Risks and validation gates

| Risk / uncertainty | Validation or mitigation |
| --- | --- |
| FitNotes source contract only partially validated | First backup is SQLite user_version 22 with valid exercise/set joins. Units, weight scaling, unused exercise types, and flags still need controlled examples; see discovery findings. |
| IDs may change across edits/reorders/restores | Source IDs distinguish repeated sets in the inspected backup. Validate with controlled examples before promising cross-backup updates; never collapse records by metric equality. |
| Weight, completion, and exercise semantics differ | Check global/per-exercise units, planned vs completed sets, renamed exercises, assisted/bodyweight movements, and distance/time records. Count unsupported rows. |
| Strava CSV layout and units vary | Inspect actual export headers and representative values; do not assume a particular CSV schema is guaranteed by bulk export documentation. |
| Date-only and timezone-less history | Reporting uses confirmed `Asia/Singapore` dates. Preserve precision and do not invent UTC timestamps; naive source times and historical travel still require validation. |
| Partial histories distort trends | Report observed date ranges and metric-specific missing/excluded counts. Show import rejection totals separately, without claiming date-filtered rejection counts or complete coverage. Absence of imported workouts does not demonstrate rest. |
| Local-first can be mistaken for fully offline | Imports and reports stay local; AI questions and selected results leave the machine. Explain this boundary and review provider data handling at integration time. |
| Model mistakes, injected source text, API failure/cost | Fixed read-only tools, application-side validation, bounded calls/results, fake API tests, visible errors, configurable model, and optional live evaluation. |
| Personal files accidentally committed | Ignore data/exports/credentials, keep only invented fixtures, and inspect staged content. Arbitrary text files can still contain sensitive data. |
| Python setup only partly verified | `py` now executes Python 3.14.10 for discovery; `python` still resolves to an unusable alias. Package installation and application tests remain unverified. |
| Named timezone database unavailable on some systems | Check `zoneinfo` support when normalizing timestamps; add `tzdata` if needed, particularly on Windows. Never silently fall back to the machine timezone. |

## Open questions for source validation

1. Which FitNotes app version produced schema version 22, how are nonzero weights
   encoded, and do IDs survive edits/reordering? Dates are date-only; the user
   confirmed this backup's sets were performed despite their raw completion flags.
2. Does the personal Strava export contain a usable activities CSV with stable IDs,
   unambiguous distance/duration fields, and sufficient timestamp information?
3. How should older naive timestamps and travel be interpreted? Reporting dates are
   confirmed as Singapore dates with Monday-start weeks; source timezones are separate.

The first FitNotes report scope is settled: per-exercise set/repetition totals and
recorded training days. Load-based progression and volume wait for source validation.

These questions gate the relevant implementation, not project initialization.
Model choice and API spend limits can wait until deterministic analytics work.
For the next milestone, synthetic same-ID update tests establish our upsert behavior
only; real FitNotes ID stability remains an explicit limitation. Unknown load units
and source app version do not block the inspected schema's reps-only import path.

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
