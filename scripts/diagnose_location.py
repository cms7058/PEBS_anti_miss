#!/usr/bin/env python3
"""Read-only location delivery diagnosis. Never returns identities, coordinates or credentials.

Run inside the backend container using: python - < scripts/diagnose_location.py
"""
import argparse
import hashlib
import json
import os
import re
import urllib.request
from pathlib import Path
import sqlite3
import time


def age(timestamp, now):
    return None if timestamp is None else round(now - timestamp, 1)


def query_push_states(cids):
    """Query existing Getui identities; return only normalized statuses, never raw responses."""
    from backend.elder_push import GetuiClient
    client = GetuiClient()
    app_id = os.environ["GETUI_APP_ID"].strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{10,100}", app_id):
        raise ValueError("invalid app id")
    if not cids or any(not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", cid) for cid in cids):
        raise ValueError("invalid push identity")
    client.authenticate()
    result = {}
    for attempt in range(2):
        request = urllib.request.Request("https://restapi.getui.com/v2/" + app_id + "/user/status/" + ",".join(cids),
                                         headers={"token": client.token}, method="GET")
        with urllib.request.urlopen(request, timeout=10) as response:
            result = json.loads(response.read(65536))
        if result.get("code") != 10001 or attempt == 1:
            break
        client.authenticate()
    code = result.get("code")
    safe_code = code if type(code) is int else None
    if code != 0:
        return {"succeeded": False, "api_code": safe_code}, {}
    entries = result.get("data")
    if not isinstance(entries, dict):
        return {"succeeded": False, "error": "unexpected_response"}, {}
    states = {}
    for cid in cids:
        entry = entries.get(cid)
        status = entry.get("status") if isinstance(entry, dict) else None
        states[cid] = status if status in ("online", "offline") else "unknown"
    return {"succeeded": True, "api_code": safe_code}, states


def diagnose(database, code_root, now=None, live_push=False):
    now = time.time() if now is None else now
    source = Path(code_root) / "backend" / "elder_push.py"
    body = source.read_text() if source.is_file() else ""
    report = {
        "server_time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "push_worker_sha256": hashlib.sha256(body.encode()).hexdigest()[:16] if body else None,
        "ack_retry_code_present": "state IN ('pending','accepted') AND attempts<5" in body,
        "command_stream_code_present": (Path(code_root) / "backend" / "command_stream.py").is_file(),
        "getui_configured": all(bool(os.getenv(k, "").strip()) for k in ("GETUI_APP_ID", "GETUI_APP_KEY", "GETUI_MASTER_SECRET")),
        "devices": [],
    }
    # URI read-only prevents accidental DB creation and all writes, including request expiry updates.
    lookup = []
    db = sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        has_device_state = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='elder_device_state'").fetchone() is not None
        report["paired_device_count"] = db.execute("SELECT COUNT(*) FROM elders WHERE consent=1").fetchone()[0]
        rows = db.execute("SELECT id,version,applied_version,last_seen,last_location,settings FROM elders WHERE consent=1 ORDER BY created LIMIT 20").fetchall()
        for index, elder in enumerate(rows, 1):
            eid = elder["id"]
            diag = db.execute("SELECT app_version,sdk_online,registration_state,updated_at FROM elder_diagnostics WHERE elder_id=?", (eid,)).fetchone()
            push = db.execute("SELECT state,attempts,next_attempt,expires,last_error FROM elder_outbox WHERE elder_id=? AND kind='location'", (eid,)).fetchone()
            request = db.execute("SELECT state,requested_at,expires FROM location_requests WHERE elder_id=?", (eid,)).fetchone()
            registration = db.execute("SELECT cid,app_id FROM elder_push_devices WHERE elder_id=?", (eid,)).fetchone()
            registered = registration is not None
            if registration and registration["app_id"] == os.getenv("GETUI_APP_ID", "").strip():
                lookup.append((index, registration["cid"]))
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
            if has_device_state:
                state = db.execute("SELECT payload,updated_at FROM elder_device_state WHERE elder_id=?", (eid,)).fetchone()
                observed = json.loads(state["payload"]) if state else {}
                fields = ("precise_location", "background_location", "battery_unrestricted", "notifications", "location_enabled", "network_location", "guard_enabled", "service_running", "command_stream_connected")
                row["phone_state_at_last_report"] = {key: observed[key] for key in fields if type(observed.get(key)) is bool}
                row["phone_state_age_seconds"] = age(state["updated_at"], now) if state else None
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
                    "remaining_seconds": round(push["expires"] - now, 1),
                    "last_send_failed": bool(push["last_error"]) if push["attempts"] else None}
            report["devices"].append(row)
    finally:
        db.close()
    if live_push:
        result, states = {"succeeded": False, "error": "no_matching_registered_device"}, {}
        if not report["getui_configured"]:
            result = {"succeeded": False, "error": "getui_not_configured"}
        elif lookup:
            try:
                result, states = query_push_states([cid for _, cid in lookup])
            except Exception:
                # Upstream exceptions can embed credential headers, CIDs or response bodies.
                result = {"succeeded": False, "error": "getui_query_failed"}
        result["checked_at_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        report["getui_live_query"] = result
        for row in report["devices"]:
            cid = next((cid for slot, cid in lookup if slot == row["device_slot"]), None)
            row["getui_status_now"] = states.get(cid, "unknown")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=os.getenv("DATABASE_PATH", "family.sqlite3"))
    parser.add_argument("--code-root", default=os.getcwd())
    parser.add_argument("--live-push", action="store_true", help="查询个推当前CID在线状态，不发送推送或修改手机")
    args = parser.parse_args()
    try:
        result = diagnose(args.database, args.code_root, live_push=args.live_push)
    except (OSError, sqlite3.Error, ValueError, TypeError):
        print(json.dumps({"error": "无法读取诊断数据，请在后端容器中运行；本工具未修改数据库。"}, ensure_ascii=False))
        raise SystemExit(1)
    print(json.dumps(result, ensure_ascii=False, indent=2))
