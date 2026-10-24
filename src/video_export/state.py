"""Private, atomic run records and explicit master reuse evidence."""

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .common import ExportError, path


def fingerprint(filename):
    file = path(filename)
    stat = file.stat()
    # Metadata fingerprint avoids hashing multi-gigabyte masters on every retry.
    return {"path": str(file), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def identity(config):
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


class RunState:
    def __init__(self, directory=None):
        base = path(directory or Path.home() / ".local/state/video-export")
        self.folder = base / uuid.uuid4().hex
        self.folder.mkdir(parents=True, mode=0o700)
        self.filename = self.folder / "manifest.json"
        self.data = {"created_at": datetime.now(UTC).isoformat(), "status": "running"}
        self.save()

    def save(self, **changes):
        self.data.update(changes)
        temporary = self.folder / "manifest.tmp"
        temporary.write_text(json.dumps(self.data, indent=2, default=str))
        os.chmod(temporary, 0o600)
        temporary.replace(self.filename)


def reuse_master(manifest, config):
    try:
        record = json.loads(path(manifest).read_text())
        master = record["master"]
        valid = (master["identity"] == identity(config)
                 and master["fingerprint"] == fingerprint(config["output"])
                 and master["verified"] is True)
    except (OSError, ValueError, KeyError, TypeError):
        valid = False
    if not valid:
        raise ExportError("unverified_master_provenance", "Master does not match the prior manifest")
    return master
