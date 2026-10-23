"""Create a reproducible code-only release. No database, account, image or secret is uploaded."""
import gzip
import hashlib
import io
from pathlib import Path
import tarfile

root = Path(__file__).resolve().parents[1]
paths = [
    ".dockerignore", "deploy/Dockerfile", "deploy/compose.yaml", "deploy/compose.http.yaml", "deploy/cloud.env.example",
    "backend/__init__.py", "backend/server.py", "backend/wsgi.py", "backend/elder_push.py", "backend/command_stream.py", "backend/requirements.txt",
    "deploy/requirements.txt", "deploy/gunicorn.conf.py", "deploy/Caddyfile",
    "deploy/backend.env.example", "deploy/familyguard.service", "deploy/backup.py",
    "deploy/familyguard-backup.service", "deploy/familyguard-backup.timer", "deploy/README.md",
]
manifest = "".join(hashlib.sha256((root / p).read_bytes()).hexdigest() + "  " + p + "\n" for p in paths).encode()
version = hashlib.sha256(manifest).hexdigest()[:12]
buffer = io.BytesIO()
with tarfile.open(fileobj=buffer, mode="w") as archive:
    for name, data in [(p, (root / p).read_bytes()) for p in paths] + [("MANIFEST.sha256", manifest)]:
        item = tarfile.TarInfo(name)
        item.size, item.mode, item.mtime = len(data), 0o644, 0
        archive.addfile(item, io.BytesIO(data))
destination = root / "build/deploy"
destination.mkdir(parents=True, exist_ok=True)
package = destination / ("familyguard-" + version + ".tar.gz")
package.write_bytes(gzip.compress(buffer.getvalue(), mtime=0))
checksum = hashlib.sha256(package.read_bytes()).hexdigest()
package.with_suffix(package.suffix + ".sha256").write_text(checksum + "  " + package.name + "\n")
print(package)
