"""Shared import counts and source-file protection."""

from collections import Counter
from dataclasses import dataclass, field

from .. import db

SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")
OUTCOMES = ("inserted", "updated", "unchanged", "rejected", "unsupported")


@dataclass
class ImportReport:
    counts: dict[str, int] = field(default_factory=lambda: dict.fromkeys(OUTCOMES, 0))
    diagnostics: Counter[str] = field(default_factory=Counter)
    warnings: list[str] = field(default_factory=list)


def check_destination(source, destination):
    # SQLite can write, truncate or remove destination sidecars during recovery.
    writable_paths = [destination, *(
        destination.with_name(destination.name + suffix) for suffix in SIDECAR_SUFFIXES
    )]
    if any(path == source or (path.exists() and source.samefile(path)) for path in writable_paths):
        raise db.FitnessError("Source and destination must be different files, including SQLite sidecars.")
