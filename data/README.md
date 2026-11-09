# Local personal data

Keep original exports, working databases, and local reports under this directory.
Everything here except this README is ignored by Git. Suggested paths when needed:

- `data/raw/` for untouched FitNotes backups and extracted Strava exports.
- `data/unified-fitness.sqlite3` for the application's database.

Imports will read originals without modifying them. Retain a separate backup of
originals: Git exclusions do not provide backup or encryption. Do not place private
files in `tests/fixtures/`, whose contents are eligible for version control.
