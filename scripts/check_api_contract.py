"""Validate the real backend response against the iPhone's Codable models, without UI automation."""
from pathlib import Path
import json
import os
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from backend.server import Store

build = root / "build"
build.mkdir(exist_ok=True)
now = [1800000000.0]
store = Store(":memory:", lambda: now[0])
def call(method, path, data=None, token=""):
    return store.dispatch(method, path, data or {}, token)
owner = call("POST", "/auth/register", {"name": "fixture-owner", "password": "fixture-password-2026"})["token"]
viewer = call("POST", "/auth/register", {"name": "fixture-viewer", "password": "fixture-password-2026"})["token"]
created = call("POST", "/elders", {"name": "测试家人"}, owner)
eid = created["id"]
device = call("POST", "/device/pair", {"code": created["code"], "consent": True})["token"]
code = call("POST", f"/elders/{eid}/invites", {"can_edit": False}, owner)["code"]
call("POST", "/invites/accept", {"code": code}, viewer)
elder = call("GET", f"/elders/{eid}", token=owner)
settings = elder["settings"]
settings["fence"] = {"lat": 31, "lon": 121, "radius": 500}
call("PUT", f"/elders/{eid}/settings", {"version": 0, "settings": settings}, owner)
call("POST", "/push/device", {"token": "a" * 64}, owner)
call("POST", "/device/location", {"lat": 31, "lon": 121, "accuracy": 10, "battery": 70, "recorded_at": now[0], "applied_version": 1}, device)
now[0] += 601
store.tick()
fixture = build / "api-contract.json"
fixture.write_text(json.dumps(call("GET", "/elders", token=owner)))
store.db.close()
environment = dict(os.environ, DEVELOPER_DIR="/Applications/Xcode.app/Contents/Developer")
subprocess.run(["xcrun", "swiftc", "-module-cache-path", str(build / "swift-module-cache"),
                str(root / "ios_app_antimiss/ios_app_antimiss/Coordinates.swift"), str(root / "ios_app_antimiss/ios_app_antimiss/Models.swift"),
                str(root / "scripts/test_api_contract.swift"), "-o", str(build / "test-api-contract")], env=environment, check=True)
subprocess.run([str(build / "test-api-contract"), str(fixture)], check=True)
