"""Download official, checksum-verified build tools into ignored build/toolchains.

No global installation, SDK manager, license acceptance, or system setting changes.
Requires macOS Apple Silicon. Java and Gradle versions are pinned by their metadata.
"""
import concurrent.futures
import hashlib
import json
import pathlib
import subprocess
import tarfile
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

root = pathlib.Path(__file__).resolve().parents[1]
dest = root / "build/toolchains"
dest.mkdir(parents=True, exist_ok=True)

def fetch(url, path, resume=False):
    flags = ["--continue-at", "-"] if resume else []
    subprocess.run(["curl", "-fLsS", "--connect-timeout", "15", "--max-time", "600", "--retry", "2"] + flags + [url, "-o", str(path)], check=True)
    return path

def metadata(url, name):
    return fetch(url, dest / name).read_bytes()

def download(name, url, checksum, algorithm):
    path = dest / name
    def valid():
        if not path.exists(): return False
        digest = hashlib.new(algorithm)
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""): digest.update(chunk)
        return digest.hexdigest() == checksum.strip()
    if not valid():
        print("Downloading", name, flush=True)
        fetch(url, path, resume=True)
    if not valid(): raise RuntimeError("Checksum mismatch: " + name)
    print("Verified", name, flush=True)
    return path

repository = ET.fromstring(metadata("https://dl.google.com/android/repository/repository2-3.xml", "repository.xml"))
jdk = json.loads(metadata("https://api.adoptium.net/v3/assets/latest/17/hotspot?architecture=aarch64&image_type=jdk&os=mac", "jdk.json"))[0]["binary"]["package"]
tasks = [("jdk.tar.gz", jdk["link"], jdk["checksum"], "sha256")]
for package in repository.findall("remotePackage"):
    if package.get("path") in ("platforms;android-35", "build-tools;35.0.0"):
        for archive in package.findall("./archives/archive"):
            if archive.findtext("host-os") in (None, "macosx"):
                name = archive.findtext("complete/url")
                tasks.append((name, "https://dl.google.com/android/repository/" + name, archive.findtext("complete/checksum"), "sha1"))
gradle_url = "https://services.gradle.org/distributions/gradle-8.11.1-bin.zip"
gradle_sha = metadata(gradle_url + ".sha256", "gradle.sha256").decode()
tasks.append(("gradle.zip", gradle_url, gradle_sha, "sha256"))
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
    paths = list(executor.map(lambda task: download(*task), tasks))
for path in paths:
    if path.name == "jdk.tar.gz":
        with tarfile.open(path) as archive: archive.extractall(dest)
    elif path.name.startswith("platform-"):
        temporary = dest / "platform-extracted"
        with zipfile.ZipFile(path) as archive: archive.extractall(temporary)
        source = next(p for p in temporary.iterdir() if p.is_dir())
        target = dest / "sdk/platforms/android-35"
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists(): source.rename(target)
    elif path.name.startswith("build-tools_"):
        temporary = dest / "buildtools-extracted"
        with zipfile.ZipFile(path) as archive:
            archive.extractall(temporary)
            for item in archive.infolist():
                permissions = item.external_attr >> 16
                if permissions: (temporary / item.filename).chmod(permissions & 0o777)
        source = next(p for p in temporary.iterdir() if p.is_dir())
        target = dest / "sdk/build-tools/35.0.0"
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists(): source.rename(target)
    else:
        with zipfile.ZipFile(path) as archive: archive.extractall(dest)
        (dest / "gradle-8.11.1/bin/gradle").chmod(0o755)
java = next(dest.glob("jdk-*/Contents/Home"))
(root / "android/local.properties").write_text("sdk.dir=" + str(dest / "sdk") + "\n")
print("Tools ready:", java, flush=True)
