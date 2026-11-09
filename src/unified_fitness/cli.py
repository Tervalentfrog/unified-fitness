"""Offline command-line entry point."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from .analytics import strength_summary
from .db import FitnessError
from .ingestion.fitnotes import import_file


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
    args = parser.parse_args(argv)

    try:
        if args.command == "summary":
            print(json.dumps(strength_summary(args.db), indent=2))
            return 0
        report = import_file(args.backup, args.db, assume_performed=args.assume_performed)
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
