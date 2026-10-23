#!/usr/bin/env python3
"""Read-only location delivery diagnosis. Never returns identities, coordinates or credentials.

Run inside the backend container using: python - < scripts/diagnose_location.py
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time


def age(timestamp, now):
    return None if timestamp is None else round(now - timestamp, 1)


def diagnose(database, code_root, now=None):
    now = time.time() if now is None else now
    source = Path(code_root) / "backend" / "elder_push.py"
    body = source.read_text() if source.is_file() else ""
    report = {
        "server_time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "push_worker_sha256": hashlib.sha256(body.encode()).hexdigest()[:16] if body else None,
        "ack_retry_code_present": "state IN ('pending','accepted') AND attempts<5" in body,
        "getui_configured": all(bool(os.getenv(k, "").strip()) for k in ("GETUI_APP_ID", "GETUI_APP_KEY", "GETUI_MASTER_SECRET")),
        "devices": [],
    }
    # URI read-only prevents accidental DB creation and all writes, including request expiry updates.
    db = sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        report["paired_device_count"] = db.execute("SELECT COUNT(*) FROM elders WHERE consent=1").fetchone()[0]
        rows = db.execute("SELECT id,version,applied_version,last_seen,last_location,settings FROM elders WHERE consent=1 ORDER BY created LIMIT 20").fetchall()
        for index, elder in enumerate(rows, 1):
            eid = elder["id"]
            diag = db.execute("SELECT app_version,sdk_online,registration_state,updated_at FROM elder_diagnostics WHERE elder_id=?", (eid,)).fetchone()
            push = db.execute("SELECT state,attempts,next_attempt,expires FROM elder_outbox WHERE elder_id=? AND kind='location'", (eid,)).fetchone()
            request = db.execute("SELECT state,requested_at,expires FROM location_requests WHERE elder_id=?", (eid,)).fetchone()
            registered = db.execute("SELECT 1 FROM elder_push_devices WHERE elder_id=?", (eid,)).fetchone() is not None
            location = json.loads(elder["last_location"]) if elder["last_location"] else None
            settings = json.loads(elder["settings"])
            row = {
                "device_slot": index,
                "app_version": diag["app_version"] if diag else None,
                "sdk_online_at_last_report": bool(diag["sdk_online"]) if diag and diag["sdk_online"] is not None else None,
                "registration_state": diag["registration_state"] if diag else None,
                "diagnostics_age_seconds": age(diag["updated_at"], now) if diag else None,
                "push_device_registered": registered,
                "automatic_mode": bool(settings.get("fence") or (settings.get("trip") or {}).get("status") == "active"),
                "settings_applied": elder["version"] == elder["applied_version"],
                "last_upload_age_seconds": age(elder["last_seen"], now),
                "last_capture_age_seconds": age(location.get("recorded_at"), now) if location else None,
                "request": None,
                "location_hint": None,
            }
            if request:
                row["request"] = {
                    "state": request["state"],
                    "age_seconds": age(request["requested_at"], now),
                    "remaining_seconds": round(request["expires"] - now, 1),
                    "command_fetch_recorded": request["state"] in ("received", "completed") or bool(push and push["state"] == "received"),
                    "post_request_capture_present": bool(location and location["recorded_at"] >= request["requested_at"]),
                }
            if push:
                row["location_hint"] = {"state": push["state"], "send_attempts": push["attempts"],
                    "next_attempt_in_seconds": round(push["next_attempt"] - now, 1),
                    "remaining_seconds": round(push["expires"] - now, 1)}
            report["devices"].append(row)
    finally:
        db.close()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=os.getenv("DATABASE_PATH", "family.sqlite3"))
    parser.add_argument("--code-root", default=os.getcwd())
    args = parser.parse_args()
    try:
        result = diagnose(args.database, args.code_root)
    except (OSError, sqlite3.Error, ValueError, TypeError):
        print(json.dumps({"error": "无法读取诊断数据，请在后端容器中运行；本工具未修改数据库。"}, ensure_ascii=False))
        raise SystemExit(1)
    print(json.dumps(result, ensure_ascii=False, indent=2))
