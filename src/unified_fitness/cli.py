"""Offline command-line entry point."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from .analytics import running_summary, strength_summary
from .db import FitnessError
from .ingestion import fitnotes, strava


def main(argv=None):
    parser = argparse.ArgumentParser(prog="unified-fitness")
    parser.add_argument("--db", type=Path, default=Path("data/unified-fitness.sqlite3"),
                        help="consolidated database path (default: data/unified-fitness.sqlite3)")
    commands = parser.add_subparsers(dest="command", required=True)
    importer = commands.add_parser("import-fitnotes", help="import a standalone FitNotes v22 backup")
    importer.add_argument("backup", type=Path)
    importer.add_argument("--assume-performed", action="store_true",
                          help="assert that the backup's sets were performed")
    commands.add_parser("summary", help="report stored strength sets, repetitions and days")
    strava_importer = commands.add_parser("import-strava", help="import runs from Strava activities.csv")
    strava_importer.add_argument("activities", type=Path)
    commands.add_parser("running-summary", help="report stored running totals and moving pace")
    args = parser.parse_args(argv)

    try:
        if args.command == "summary":
            print(json.dumps(strength_summary(args.db), indent=2))
            return 0
        if args.command == "running-summary":
            print(json.dumps(running_summary(args.db), indent=2))
            return 0
        if args.command == "import-strava":
            report = strava.import_file(args.activities, args.db)
        else:
            report = fitnotes.import_file(args.backup, args.db, assume_performed=args.assume_performed)
    except FitnessError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except (sqlite3.Error, OSError, RuntimeError):
        print("Error: Cannot access the requested files. Check paths and permissions.", file=sys.stderr)
        return 1

    print(json.dumps(report.counts))
    for reason, count in sorted(report.diagnostics.items()):
        print(f"{count} row(s): {reason}", file=sys.stderr)
    for warning in report.warnings:
        print(f"Warning: {warning}", file=sys.stderr)
    return 3 if report.counts["rejected"] or report.counts["unsupported"] else 0


if __name__ == "__main__":
    sys.exit(main())
