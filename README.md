# Unified Fitness

A local-first, single-user application for importing FitNotes strength history and
Strava running history into SQLite, then querying measured trends from a console.

**Status: planning, initialization, and FitNotes discovery complete.** No importer, database schema, CLI,
analytics, or OpenAI integration has been implemented. There is no runnable
application command yet, and no application tests have been added.

## Development setup

Use Python 3.11 or newer with pip and venv. From the repository root in PowerShell:

```powershell
py --version
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -c "import unified_fitness"
```

On macOS/Linux, use `python3` to create the environment and
`.venv/bin/python` for the remaining commands. Activating the environment is optional.

Discovery environment (2026-11-09): `py` runs Python 3.14.10 and SQLite queries
successfully, with a path-location warning. `python` still resolves to an unusable
Windows App Execution Alias. Virtual-environment setup and package installation
have not been validated on this machine.

When the first feature tests exist, run:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

At this scaffold stage pytest would collect no tests (exit code 5); that is not a
passing test suite. Runtime dependencies are empty. Add the OpenAI SDK only when
implementing the AI milestone; ingestion and analytics will work offline.

## Configuration and privacy

`.env.example` documents proposed settings, not a working configuration loader.
No API key is needed now. Later code will read process environment variables;
copying the template to `.env` alone will not load it automatically.

Store private exports and databases under `data/`. Keep credentials, raw data,
personal reports, and transcripts out of Git. Only synthetic test fixtures belong
in `tests/fixtures/`. Review staged files before every commit: ignore rules are not
a guarantee against secrets in arbitrary files.

Local-first means storage and calculations remain local. Planned AI chat sends
questions and selected aggregate tool results to OpenAI. Raw backups, GPS tracks,
free-text workout notes, and the database itself will not be uploaded by the app.
Chat will disclose the data flow before use; offline reports remain available.

## Layout and plans

```text
planning/                 Architecture, milestones, and decisions
src/unified_fitness/       Python package (package marker only)
tests/fixtures/            Guidance for future synthetic test data
data/                     Ignored local personal data
.env.example              Proposed environment settings
.gitignore                Python, credentials, and personal data exclusions
pyproject.toml            Packaging and pytest configuration
README.md                 Setup and project status
```

- [Architecture and proposed data model](planning/architecture.md)
- [Prioritized implementation plan](planning/implementation-plan.md)
- [Decisions, trade-offs, and open questions](planning/decisions.md)
- [FitNotes discovery](planning/fitnotes-discovery.md)
- [Implementation handoff](planning/handoff.md)
- [Ready-to-paste next-session prompt](planning/next-session-prompt.md)

Next: implement the bounded FitNotes import/summary workflow described in the
handoff. Normalize IDs/dates/reps; keep load conversions unknown until validated.
