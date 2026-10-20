"""Online SQLite backup; never copy a live WAL database with a plain file copy."""
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import tempfile
from urllib.parse import quote


def backup(database, directory):
    os.umask(0o077)
    source = Path(database).resolve(strict=True)
    destination = Path(directory)
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = destination / ("family-" + timestamp + ".sqlite3")
    handle, temporary = tempfile.mkstemp(prefix=".backup-", dir=destination)
    os.close(handle)
    try:
        with sqlite3.connect("file:" + quote(str(source)) + "?mode=ro", uri=True) as src:
            with sqlite3.connect(temporary) as dst:
                src.backup(dst)
                if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("Backup integrity check failed")
        os.replace(temporary, target)
        return target
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()


if __name__ == "__main__":
    print(backup(os.environ["DATABASE_PATH"], os.getenv("BACKUP_DIR", "/var/lib/familyguard/backups")))
