We are implementing Unified Fitness in `C:\dev\unified-fitness`. Complete the first
FitNotes ingestion milestone; planning and source discovery are already done.

Before changing anything, inspect Git status, applicable AGENTS.md instructions,
existing code/tests, pyproject.toml, and README.md. Read planning/handoff.md,
planning/architecture.md, planning/fitnotes-discovery.md, planning/decisions.md, and
planning/implementation-plan.md. Preserve existing work. The scaffold currently
contains no application functionality; verify that rather than assuming it.

Implement a small end-to-end workflow:

1. Consolidated SQLite persistence using only imports, exercises, and strength_sets
   for now, following the documented fields, uniqueness, foreign keys, transactions,
   and destination schema versioning. Add the running table only with Strava later.
2. A FitNotes importer for the inspected SQLite schema version 22. Open source files
   read-only, validate required schema and stored values, and reject source/destination
   file collisions before writes. Import only exercises referenced by accepted sets.
3. Idempotent imports keyed by source IDs: preserve identical legitimate sets with
   different IDs; unchanged records stay untouched; changed same-ID records update;
   absent records are not deleted. Test updates with synthetic snapshots without
   claiming FitNotes ID stability across real reorders/restores is established.
   Audit entries may grow on repeated imports; exercise/set rows must not.
4. Conservative normalization: canonical TEXT IDs, ISO date-only values, integer
   reps, and preserved raw load/type/unit/flag values. Initially support valid type-0
   rows with zero distance/duration; report other types/metrics as unsupported.
   Weight scaling and unit codes are unverified. Keep normalized load/unit, load kind,
   and set order NULL; do not guess kg/grams or infer bodyweight from zero.
5. An explicit performed-set option such as --assume-performed, recorded in import
   metadata. The user already confirmed the inspected backup's sets were performed:
   retain all 24 despite zero completion flags and four pending-update flags. Do not
   hardcode private filenames/IDs or generalize this confirmation to every backup.
6. A basic installed argparse CLI for import and a deterministic summary of sets,
   repetitions, and recorded training days, with a database-path option, meaningful
   exit statuses, and bounded diagnostics. Count every source set once across
   inserted/updated/unchanged/rejected/unsupported; distinguish warnings from outcomes.
7. Essential pytest coverage using invented temporary SQLite fixtures. Cover repeat
   imports, same-ID changes, legitimate repeated sets, normalization/raw preservation,
   malformed data, missing references, unsupported schemas/types/metrics, rollback,
   empty input, summary correctness, CLI behavior, and source/destination protection.

Keep the implementation small: Python standard library plus pytest; no ORM,
dataframe/agent frameworks, Strava, OpenAI integration, sessions, or load-based
analytics. Unknown weight encoding must not block the reps-only milestone.

Use py on Windows if python still resolves to the broken alias. Create a local
virtual environment, install .[dev], run the relevant tests and CLI smoke checks,
and report actual commands/results. If the existing private backup is present,
verify an import into an ignored local database followed by an unchanged re-import
(24 sets, one exercise, five days), and check the source hash remains unchanged.
Never dump personal records, modify originals, upload backups, or use real data as
tracked fixtures. Keep all private artifacts under ignored data/.

Use the handoff acceptance criteria to finish the milestone. Update README and
planning documents with working commands, test results, limitations, and any
deviations. Resolve routine choices pragmatically; ask only when a real ambiguity
affects correctness. Summarize what works and remaining risks, then stop. Do not
commit or push unless I ask.
