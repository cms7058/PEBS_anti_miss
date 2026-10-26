"""Family safety prototype. Run: python3 -m backend.server. No third-party API dependencies."""
import hashlib
import errno
import hmac
import json
import math
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from backend.elder_push import ElderPushWorker, run_command_push, configured as elder_push_configured
from backend.command_stream import CommandStream


MAX_FENCE_SAMPLE_GAP = 180


class APIError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def require(condition, message, status=400):
    if not condition:
        raise APIError(status, message)


def number(data, key, low, high):
    value = data.get(key)
    require(type(value) in (int, float) and math.isfinite(value) and low <= value <= high,
            f"{key} 必须在 {low} 至 {high} 之间")
    return value


def coordinates(data):
    number(data, "lat", -90, 90)
    number(data, "lon", -180, 180)


def distance(a, b):
    lat1, lat2 = math.radians(a["lat"]), math.radians(b["lat"])
    v = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(math.radians(b["lon"] - a["lon"]) / 2) ** 2
    return 6371000 * 2 * math.asin(min(1, math.sqrt(v)))


def automatic_guard(settings):
    return settings.get("fence") is not None or (settings.get("trip") or {}).get("status") == "active"


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Store:
    def __init__(self, path, clock=time.time):
        self.clock = clock
        self.lock = threading.RLock()
        self.command_ready = threading.Event()
        self.command_condition = threading.Condition(self.lock)
        self.command_versions = {}
        self.command_streams = {}
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        PRAGMA foreign_keys=ON;
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, name TEXT UNIQUE, salt TEXT, password TEXT);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id), expires REAL);
        CREATE TABLE IF NOT EXISTS elders(id TEXT PRIMARY KEY, name TEXT, owner TEXT REFERENCES users(id),
          device_token TEXT UNIQUE, pair_code TEXT UNIQUE, pair_expires REAL, consent INTEGER DEFAULT 0,
          created REAL, last_location TEXT, last_seen REAL, settings TEXT, version INTEGER DEFAULT 0,
          applied_version INTEGER DEFAULT 0, outside_since REAL, outside_count INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS members(elder_id TEXT REFERENCES elders(id), user_id TEXT REFERENCES users(id),
          can_edit INTEGER DEFAULT 0, PRIMARY KEY(elder_id,user_id));
        CREATE TABLE IF NOT EXISTS invites(code TEXT PRIMARY KEY, elder_id TEXT REFERENCES elders(id),
          can_edit INTEGER, expires REAL);
        CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, elder_id TEXT REFERENCES elders(id), kind TEXT,
          message TEXT, created REAL, location TEXT, active INTEGER DEFAULT 1,
          acknowledged_by TEXT, acknowledged_at REAL);
        CREATE UNIQUE INDEX IF NOT EXISTS active_kind ON events(elder_id,kind) WHERE active=1;
        CREATE TABLE IF NOT EXISTS muted_incidents(elder_id TEXT REFERENCES elders(id), kind TEXT,
          PRIMARY KEY(elder_id,kind));
        CREATE TABLE IF NOT EXISTS location_requests(elder_id TEXT PRIMARY KEY REFERENCES elders(id),
          id TEXT, requested_at REAL, expires REAL, state TEXT, completed_at REAL, completion_source TEXT);
        CREATE TABLE IF NOT EXISTS elder_diagnostics(elder_id TEXT PRIMARY KEY REFERENCES elders(id),
          app_version TEXT,push_consent INTEGER,cid_available INTEGER,sdk_online INTEGER,registration_state TEXT,updated_at REAL);
        CREATE TABLE IF NOT EXISTS elder_push_devices(elder_id TEXT PRIMARY KEY REFERENCES elders(id), cid TEXT UNIQUE, app_id TEXT);
        CREATE TABLE IF NOT EXISTS elder_device_state(elder_id TEXT PRIMARY KEY REFERENCES elders(id), payload TEXT, updated_at REAL);
        CREATE TABLE IF NOT EXISTS elder_setup_requests(elder_id TEXT PRIMARY KEY REFERENCES elders(id), id TEXT,
          action TEXT, requested_at REAL, expires REAL, state TEXT);
        CREATE TABLE IF NOT EXISTS elder_outbox(elder_id TEXT REFERENCES elders(id), kind TEXT,
          generation TEXT, expires REAL, state TEXT, attempts INTEGER DEFAULT 0,
          next_attempt REAL DEFAULT 0, last_error TEXT, PRIMARY KEY(elder_id,kind));
        CREATE TABLE IF NOT EXISTS devices(token TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS outbox(event_id TEXT REFERENCES events(id), token TEXT,
          state TEXT DEFAULT 'pending', attempts INTEGER DEFAULT 0, next_attempt REAL DEFAULT 0,
          last_error TEXT, PRIMARY KEY(event_id,token));
        """)
        if "completion_source" not in {r["name"] for r in self.db.execute("PRAGMA table_info(location_requests)")}:
            with self.db:
                self.db.execute("ALTER TABLE location_requests ADD COLUMN completion_source TEXT")

    def one(self, sql, args=()):
        row = self.db.execute(sql, args).fetchone()
        return dict(row) if row else None

    def rows(self, sql, args=()):
        return [dict(r) for r in self.db.execute(sql, args)]

    def user(self, token):
        row = self.one("SELECT user_id FROM sessions WHERE token=? AND expires>?", (digest(token), self.clock()))
        require(row, "请重新登录", 401)
        return row["user_id"]

    def access(self, elder_id, uid, edit=False, owner=False):
        elder = self.one("SELECT * FROM elders WHERE id=?", (elder_id,))
        require(elder, "未找到老人", 404)
        member = self.one("SELECT * FROM members WHERE elder_id=? AND user_id=?", (elder_id, uid))
        require(elder["owner"] == uid or (member and not owner and (not edit or member["can_edit"])), "没有操作权限", 403)
        return elder

    def event(self, elder, kind, message):
        if self.one("SELECT 1 FROM muted_incidents WHERE elder_id=? AND kind=?", (elder["id"], kind)):
            return
        if self.one("SELECT id FROM events WHERE elder_id=? AND kind=? AND active=1", (elder["id"], kind)):
            return
        eid = secrets.token_hex(12)
        self.db.execute("INSERT INTO events(id,elder_id,kind,message,created,location) VALUES(?,?,?,?,?,?)",
                        (eid, elder["id"], kind, message, self.clock(), elder["last_location"]))
        for d in self.rows("SELECT token FROM devices WHERE user_id=? OR user_id IN (SELECT user_id FROM members WHERE elder_id=?)",
                           (elder["owner"], elder["id"])):
            self.db.execute("INSERT OR IGNORE INTO outbox(event_id,token) VALUES(?,?)", (eid, d["token"]))

    def resolve(self, elder_id, kind):
        self.db.execute("DELETE FROM muted_incidents WHERE elder_id=? AND kind=?", (elder_id, kind))
        self.db.execute("UPDATE events SET active=0 WHERE elder_id=? AND kind=?", (elder_id, kind))

    def enqueue_elder(self, elder_id, kind, ttl, generation=None):
        self.db.execute("INSERT OR REPLACE INTO elder_outbox(elder_id,kind,generation,expires,state) VALUES(?,?,?,?, 'pending')",
                        (elder_id, kind, generation or secrets.token_hex(12), self.clock() + ttl))
        self.command_ready.set()
        with self.command_condition:
            self.command_versions[elder_id] = self.command_versions.get(elder_id, 0) + 1
            self.command_condition.notify_all()

    def open_command_stream(self, token):
        with self.command_condition:
            device = self.one("SELECT id FROM elders WHERE device_token=? AND consent=1", (digest(token),))
            require(device, "设备尚未绑定", 401)
            eid = device["id"]
            require(eid in self.command_streams or len(self.command_streams) < 4, "备用通道繁忙，请稍后重连", 503)
            previous = self.command_streams.get(eid)
            if previous:
                previous.close()
            stream = CommandStream(self, eid, digest(token))
            self.command_streams[eid] = stream
            self.command_condition.notify_all()
            return stream

    def close_command_streams(self):
        with self.command_condition:
            for stream in list(self.command_streams.values()):
                stream.close()

    def elder_push_status(self, elder_id):
        device = self.one("SELECT app_id FROM elder_push_devices WHERE elder_id=?", (elder_id,))
        ready = bool(device and device["app_id"] == os.getenv("GETUI_APP_ID", "").strip())
        return {"configured": elder_push_configured(), "registered": ready,
                "command_stream_registered": elder_id in self.command_streams,
                "location_delivery": self.one("SELECT state,last_error FROM elder_outbox WHERE elder_id=? AND kind='location'", (elder_id,)),
                "settings_delivery": self.one("SELECT state,last_error FROM elder_outbox WHERE elder_id=? AND kind='settings'", (elder_id,))}

    def location_request(self, elder_id):
        self.db.execute("UPDATE location_requests SET state='expired' WHERE elder_id=? AND state IN ('pending','received') AND expires<=?", (elder_id, self.clock()))
        return self.one("SELECT id,requested_at,expires,state,completed_at,completion_source FROM location_requests WHERE elder_id=?", (elder_id,))

    def setup_request(self, elder_id):
        self.db.execute("UPDATE elder_setup_requests SET state='expired' WHERE elder_id=? AND expires<=? AND state!='opened'", (elder_id, self.clock()))
        return self.one("SELECT id,action,requested_at,expires,state FROM elder_setup_requests WHERE elder_id=?", (elder_id,))

    def snapshot(self, elder, uid):
        result = {k: elder[k] for k in ("id", "name", "last_seen", "version", "applied_version", "created")}
        result["location"] = json.loads(elder["last_location"]) if elder["last_location"] else None
        result["settings"] = json.loads(elder["settings"])
        result["location_request"] = self.location_request(elder["id"])
        result["elder_push"] = self.elder_push_status(elder["id"])
        diag = self.one("SELECT app_version,push_consent,cid_available,sdk_online,registration_state,updated_at FROM elder_diagnostics WHERE elder_id=?", (elder["id"],))
        if diag:
            for key in ("push_consent", "cid_available", "sdk_online"):
                diag[key] = bool(diag[key]) if diag[key] is not None else None
        result["device_diagnostics"] = diag
        state = self.one("SELECT payload,updated_at FROM elder_device_state WHERE elder_id=?", (elder["id"],))
        result["device_state"] = dict(json.loads(state["payload"]), updated_at=state["updated_at"]) if state else None
        result["setup_request"] = self.setup_request(elder["id"])
        result["paired"] = bool(elder["consent"])
        result["is_owner"] = elder["owner"] == uid
        member = self.one("SELECT can_edit FROM members WHERE elder_id=? AND user_id=?", (elder["id"], uid))
        result["can_edit"] = result["is_owner"] or bool(member and member["can_edit"])
        result["events"] = self.event_rows(elder["id"], uid)
        result["fence_status"] = self.fence_status(elder)
        if result["is_owner"]:
            result["members"] = self.rows("SELECT u.id,u.name,m.can_edit FROM members m JOIN users u ON u.id=m.user_id WHERE elder_id=?", (elder["id"],))
        else:
            result["members"] = []
        return result

    def event_rows(self, elder_id, uid):
        events = self.rows("SELECT e.*,u.name AS handler FROM events e LEFT JOIN users u ON u.id=e.acknowledged_by WHERE elder_id=? ORDER BY created DESC LIMIT 100", (elder_id,))
        for event in events:
            event["location"] = json.loads(event["location"]) if event["location"] else None
            # Read notification state only for this account's devices.
            event["delivery"] = self.rows("SELECT state,attempts,last_error FROM outbox WHERE event_id=? AND token IN (SELECT token FROM devices WHERE user_id=?)", (event["id"], uid))
        return events

    def fence_status(self, elder):
        settings = json.loads(elder["settings"])
        fence, trip = settings.get("fence"), settings.get("trip")
        if not fence: return {"state": "disabled", "message": "尚未开启电子围栏"}
        if not elder["consent"]: return {"state": "waiting_device", "message": "围栏已保存，等待老人手机绑定并开启守护"}
        if trip and trip["status"] in ("active", "arrived"):
            return {"state": "trip_exempt", "message": "本次行程允许离开围栏；结束行程后恢复越界提醒"}
        loc = json.loads(elder["last_location"]) if elder["last_location"] else None
        if not loc or self.clock() - loc["recorded_at"] >= 120:
            return {"state": "waiting_location", "message": "围栏已开启，等待手机上传新位置"}
        if loc["accuracy"] > 100:
            return {"state": "imprecise", "message": "围栏已开启，当前定位精度不足，暂不能确认越界"}
        delta = distance(loc, fence)
        if delta - loc["accuracy"] > fence["radius"]:
            since = elder["outside_since"] if elder["outside_since"] is not None else loc["recorded_at"]
            elapsed = max(0, loc["recorded_at"] - since)
            if elder["outside_count"] >= 2 and elapsed >= settings["outside_delay"]:
                return {"state": "outside_alert", "message": "已确认持续越界，请查看异常提醒"}
            remaining = max(0, int(settings["outside_delay"] - elapsed))
            return {"state": "outside", "message": f"已确认在围栏外，持续时间还需约{remaining}秒，并需多次有效定位确认"}
        if delta + loc["accuracy"] <= fence["radius"]:
            return {"state": "inside", "message": "围栏监测中，当前在范围内"}
        return {"state": "uncertain", "message": "当前位置接近围栏边缘，误差范围内不判为越界"}

    def evaluate(self, elder):
        settings = json.loads(elder["settings"])
        loc = json.loads(elder["last_location"]) if elder["last_location"] else None
        trip = settings.get("trip")
        if trip and trip["status"] in ("active", "arrived"):
            if trip["status"] == "active" and loc and self.clock() - loc["recorded_at"] < 120 and loc["accuracy"] <= 100 and distance(loc, trip) + loc["accuracy"] <= trip["radius"]:
                trip["status"] = "arrived"
                self.db.execute("UPDATE elders SET settings=?,version=version+1 WHERE id=?", (json.dumps(settings), elder["id"]))
                self.resolve(elder["id"], "overdue")
            elif trip["status"] == "active" and self.clock() > trip["deadline"]:
                self.event(elder, "overdue", "超过预计时间，尚未确认到达目的地")
            # Trip exemption lasts until a guardian explicitly ends the trip, including after arrival.
            self.resolve(elder["id"], "outside")
            self.db.execute("UPDATE elders SET outside_since=NULL,outside_count=0 WHERE id=?", (elder["id"],))
        else:
            fence = settings.get("fence")
            if fence and loc and self.clock() - loc["recorded_at"] < 120 and loc["accuracy"] <= 100:
                delta = distance(loc, fence)
                # Accuracy margin avoids treating GPS drift as a confident crossing.
                if delta - loc["accuracy"] > fence["radius"]:
                    if elder["outside_since"] is not None and elder["outside_count"] >= 2 and loc["recorded_at"] - elder["outside_since"] >= settings["outside_delay"]:
                        self.event(elder, "outside", "持续离开设定的安全活动范围")
                elif delta + loc["accuracy"] <= fence["radius"]:
                    self.db.execute("UPDATE elders SET outside_since=NULL,outside_count=0 WHERE id=?", (elder["id"],))
                    self.resolve(elder["id"], "outside")

    def tick(self):
        with self.lock, self.db:
            for elder in self.rows("SELECT * FROM elders WHERE consent=1"):
                settings = json.loads(elder["settings"])
                # Use location capture time, not receipt time; replayed data cannot conceal an outage.
                loc = json.loads(elder["last_location"]) if elder["last_location"] else None
                last = loc["recorded_at"] if loc else elder["created"]
                if not automatic_guard(settings):
                    self.resolve(elder["id"], "offline")
                elif self.clock() - last > settings["offline_after"]:
                    self.event(elder, "offline", "手机位置长时间未更新，请联系老人确认")
                self.evaluate(elder)

    def dispatch(self, method, path, data, token=""):
        with self.lock, self.db:
            try:
                return self._dispatch(method, path, data, token)
            finally:
                if method != "GET":
                    self.command_condition.notify_all()

    def _dispatch(self, method, path, data, token):
        now = self.clock()
        if method == "GET" and path == "/health":
            return {"ok": True, "elder_push_configured": elder_push_configured(), "push_configured": all(os.getenv(k) for k in ("APNS_KEY_PATH", "APNS_KEY_ID", "APNS_TEAM_ID", "APNS_TOPIC"))}
        if method == "POST" and path in ("/auth/register", "/auth/login"):
            name, password = data.get("name", ""), data.get("password", "")
            require(isinstance(name, str) and 2 <= len(name.strip()) <= 40 and isinstance(password, str) and 10 <= len(password) <= 128, "账号需 2–40 字，密码需 10–128 字")
            name = name.strip()
            if path.endswith("register"):
                require(not self.one("SELECT id FROM users WHERE name=?", (name,)), "账号已存在", 409)
                salt, uid = secrets.token_hex(16), secrets.token_hex(12)
                pwd = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 310000).hex()
                self.db.execute("INSERT INTO users VALUES(?,?,?,?)", (uid, name, salt, pwd))
            else:
                user = self.one("SELECT * FROM users WHERE name=?", (name,))
                salt = user["salt"] if user else "0" * 32
                pwd = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 310000).hex()
                require(user and hmac.compare_digest(pwd, user["password"]), "账号或密码错误", 401)
                uid = user["id"]
            session = secrets.token_urlsafe(32)
            self.db.execute("INSERT INTO sessions VALUES(?,?,?)", (digest(session), uid, now + 30 * 86400))
            return {"token": session, "user_id": uid, "name": name}
        if method == "POST" and path == "/device/pair":
            require(data.get("consent") is True, "需在老人手机上确认位置共享")
            elder = self.one("SELECT * FROM elders WHERE pair_code=? AND pair_expires>?", (data.get("code"), now))
            require(elder, "绑定码无效或已过期", 404)
            # Commit the replacement only after fresh on-device consent. Issuing a code
            # leaves the currently paired phone usable until this transaction succeeds.
            self.db.execute("DELETE FROM elder_diagnostics WHERE elder_id=?", (elder["id"],))
            self.db.execute("DELETE FROM elder_device_state WHERE elder_id=?", (elder["id"],))
            self.db.execute("DELETE FROM elder_setup_requests WHERE elder_id=?", (elder["id"],))
            self.db.execute("DELETE FROM muted_incidents WHERE elder_id=?", (elder["id"],))
            self.db.execute("DELETE FROM elder_push_devices WHERE elder_id=?", (elder["id"],))
            self.db.execute("DELETE FROM elder_outbox WHERE elder_id=?", (elder["id"],))
            self.db.execute("DELETE FROM location_requests WHERE elder_id=?", (elder["id"],))
            self.db.execute("UPDATE events SET active=0 WHERE elder_id=?", (elder["id"],))
            device_token = secrets.token_urlsafe(32)
            self.db.execute("UPDATE elders SET consent=1,device_token=?,pair_code=NULL,created=?,last_location=NULL,last_seen=NULL,outside_since=NULL,outside_count=0,applied_version=0 WHERE id=?", (digest(device_token), now, elder["id"]))
            return {"token": device_token, "elder_id": elder["id"], "name": elder["name"]}
        if path.startswith("/device/"):
            elder = self.one("SELECT * FROM elders WHERE device_token=? AND consent=1", (digest(token),))
            require(elder, "设备尚未绑定", 401)
            if method == "POST" and path == "/device/state":
                fields = ("precise_location", "background_location", "battery_unrestricted", "notifications", "location_enabled", "network_location", "guard_enabled", "service_running")
                require(all(type(data.get(key)) is bool for key in fields), "手机权限状态格式错误")
                require(type(data.get("settings_version")) is int and 0 <= data["settings_version"] <= elder["version"], "设置版本无效")
                require(type(data.get("automatic_interval")) is int and 30 <= data["automatic_interval"] <= 120, "采集间隔无效")
                state = {key: data[key] for key in fields + ("settings_version", "automatic_interval")}
                if "command_stream_connected" in data:
                    require(type(data["command_stream_connected"]) is bool, "备用通道状态格式错误")
                    state["command_stream_connected"] = data["command_stream_connected"]
                self.db.execute("INSERT OR REPLACE INTO elder_device_state VALUES(?,?,?)", (elder["id"], json.dumps(state), now))
                self.db.execute("UPDATE elders SET applied_version=MAX(applied_version,?) WHERE id=?", (data["settings_version"], elder["id"]))
                if data.get("setup_request_id"):
                    request = self.setup_request(elder["id"])
                    require(request and request["id"] == data["setup_request_id"], "设置提醒已失效", 409)
                    ack = data.get("setup_state")
                    require(ack in ("received", "notified", "opened"), "提醒状态无效")
                    order = {"pending": 0, "received": 1, "notified": 2, "opened": 3, "expired": 4}
                    if order[ack] > order[request["state"]]:
                        self.db.execute("UPDATE elder_setup_requests SET state=? WHERE elder_id=?", (ack, elder["id"]))
                return {"ok": True}
            if method == "POST" and path == "/device/diagnostics":
                version = data.get("app_version")
                require(isinstance(version, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,30}", version), "应用版本格式错误")
                require(type(data.get("push_consent")) is bool and type(data.get("cid_available")) is bool, "推送状态格式错误")
                online = data.get("sdk_online")
                require(online is None or type(online) is bool, "SDK连接状态格式错误")
                state = data.get("registration_state")
                require(state in ("waiting_cid", "waiting_registration", "registered", "registration_failed", "initialization_failed", "disabled"), "登记状态格式错误")
                self.db.execute("INSERT OR REPLACE INTO elder_diagnostics VALUES(?,?,?,?,?,?,?)",
                                (elder["id"], version, int(data["push_consent"]), int(data["cid_available"]),
                                 int(online) if online is not None else None, state, now))
                return {"ok": True}
            if method == "POST" and path == "/device/push":
                if data.get("enabled") is False:
                    self.db.execute("DELETE FROM elder_push_devices WHERE elder_id=?", (elder["id"],))
                    self.db.execute("UPDATE elder_outbox SET state='cancelled' WHERE elder_id=?", (elder["id"],))
                    return {"ok": True}
                cid, app_id = data.get("cid"), data.get("app_id")
                require(isinstance(cid, str) and re.fullmatch(r"[A-Za-z0-9_-]{16,128}", cid), "推送设备标识无效")
                require(app_id == os.getenv("GETUI_APP_ID", "").strip() and bool(app_id), "服务端个推 AppID 尚未配置或不匹配", 409)
                conflict = self.one("SELECT elder_id FROM elder_push_devices WHERE cid=?", (cid,))
                require(not conflict or conflict["elder_id"] == elder["id"], "该推送设备已绑定其他使用者", 409)
                previous = self.one("SELECT cid FROM elder_push_devices WHERE elder_id=?", (elder["id"],))
                self.db.execute("INSERT OR REPLACE INTO elder_push_devices VALUES(?,?,?)", (elder["id"], cid, app_id))
                if not previous or previous["cid"] != cid:
                    self.enqueue_elder(elder["id"], "settings", 3600)
                    pending = self.location_request(elder["id"])
                    if pending and pending["state"] in ("pending", "received"):
                        self.enqueue_elder(elder["id"], "location", pending["expires"] - now, pending["id"])
                return {"ok": True}
            if method == "GET" and path == "/device/commands":
                self.db.execute("UPDATE elder_outbox SET state='received' WHERE elder_id=? AND expires>? AND state IN ('pending','accepted')", (elder["id"], now))
                request = self.location_request(elder["id"])
                if request and request["state"] in ("pending", "received"):
                    self.db.execute("UPDATE location_requests SET state='received' WHERE elder_id=?", (elder["id"],))
                    request["state"] = "received"
                else:
                    request = None
                setup = self.setup_request(elder["id"])
                return {"location_request": request, "setup_request": setup if setup and setup["state"] not in ("opened", "expired") else None,
                        "version": elder["version"], "settings": json.loads(elder["settings"])}
            if method == "GET" and path == "/device/settings":
                last = json.loads(elder["last_location"])["recorded_at"] if elder["last_location"] else None
                return {"version": elder["version"], "settings": json.loads(elder["settings"]), "last_recorded_at": last}
            if method == "POST" and path == "/device/unpair":
                self.db.execute("DELETE FROM elder_diagnostics WHERE elder_id=?", (elder["id"],))
                self.db.execute("DELETE FROM elder_device_state WHERE elder_id=?", (elder["id"],))
                self.db.execute("DELETE FROM elder_setup_requests WHERE elder_id=?", (elder["id"],))
                self.db.execute("DELETE FROM elder_push_devices WHERE elder_id=?", (elder["id"],))
                self.db.execute("DELETE FROM elder_outbox WHERE elder_id=?", (elder["id"],))
                self.db.execute("DELETE FROM location_requests WHERE elder_id=?", (elder["id"],))
                self.db.execute("UPDATE elders SET consent=0,device_token=NULL WHERE id=?", (elder["id"],))
                self.db.execute("UPDATE events SET active=0 WHERE elder_id=?", (elder["id"],))
                return {"ok": True}
            if method == "POST" and path == "/device/location":
                coordinates(data)
                number(data, "accuracy", 0, 10000)
                number(data, "recorded_at", now - 86400, now + 30)
                number(data, "battery", 0, 100)
                number(data, "applied_version", 0, elder["version"])
                require(type(data["applied_version"]) is int, "无效设置版本")
                request_id = data.get("request_id")
                request = self.location_request(elder["id"])
                if request_id is not None:
                    require(request and request["id"] == request_id, "定位请求无效", 409)
                    require(data["recorded_at"] >= request["requested_at"],
                            "本次请求需要重新采集位置", 409)
                previous = json.loads(elder["last_location"]) if elder["last_location"] else None
                require(not previous or data["recorded_at"] > previous["recorded_at"], "位置时间重复或早于已保存的位置", 409)
                loc = {k: data[k] for k in ("lat", "lon", "accuracy", "recorded_at", "battery")}
                if "provider" in data:
                    require(data["provider"] in ("gps", "network"), "无效定位来源")
                    loc["provider"] = data["provider"]
                self.db.execute("UPDATE elders SET last_location=?,last_seen=?,applied_version=? WHERE id=?", (json.dumps(loc), now, data["applied_version"], elder["id"]))
                if now - loc["recorded_at"] < 120:
                    self.resolve(elder["id"], "offline")
                settings = json.loads(elder["settings"])
                fence = settings.get("fence")
                trip = settings.get("trip")
                if previous and loc["recorded_at"] - previous["recorded_at"] > MAX_FENCE_SAMPLE_GAP:
                    self.db.execute("UPDATE elders SET outside_since=NULL,outside_count=0 WHERE id=?", (elder["id"],))
                if fence and not (trip and trip["status"] in ("active", "arrived")) and loc["accuracy"] <= 100 and now - loc["recorded_at"] < 120 and distance(loc, fence) - loc["accuracy"] > fence["radius"]:
                    self.db.execute("UPDATE elders SET outside_since=COALESCE(outside_since,?),outside_count=outside_count+1 WHERE id=?", (loc["recorded_at"], elder["id"]))
                else:
                    # Uncertain or low-quality samples cannot substantiate continuous outside dwell.
                    self.db.execute("UPDATE elders SET outside_since=NULL,outside_count=0 WHERE id=?", (elder["id"],))
                if (request and request["state"] in ("pending", "received")
                        and request["requested_at"] <= loc["recorded_at"] < request["expires"]
                        and now - loc["recorded_at"] < 120):
                    source = "requested" if request_id == request["id"] else "automatic"
                    self.db.execute("UPDATE location_requests SET state='completed',completed_at=?,completion_source=? WHERE elder_id=?",
                                    (now, source, elder["id"]))
                    # The newest valid fix answers the query even if it came from scheduled tracking.
                    self.db.execute("UPDATE elder_outbox SET state='cancelled' WHERE elder_id=? AND kind='location' AND generation=? AND state IN ('pending','accepted')",
                                    (elder["id"], request["id"]))
                self.evaluate(self.one("SELECT * FROM elders WHERE id=?", (elder["id"],)))
                return {"ok": True}
            raise APIError(404, "接口不存在")
        uid = self.user(token)
        if method == "POST" and path == "/auth/logout":
            self.db.execute("DELETE FROM sessions WHERE token=?", (digest(token),))
            return {"ok": True}
        if path == "/push/device" and method in ("POST", "DELETE"):
            value = data.get("token", "")
            require(isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{32,256}", value), "推送设备令牌无效")
            if method == "POST":
                self.db.execute("INSERT INTO devices VALUES(?,?) ON CONFLICT(token) DO UPDATE SET user_id=excluded.user_id", (value, uid))
                # Deliver still-active unhandled events when a device is registered later.
                for event in self.rows("SELECT e.id FROM events e JOIN elders l ON l.id=e.elder_id WHERE e.active=1 AND e.acknowledged_by IS NULL AND (l.owner=? OR l.id IN (SELECT elder_id FROM members WHERE user_id=?))", (uid, uid)):
                    self.db.execute("INSERT OR IGNORE INTO outbox(event_id,token) VALUES(?,?)", (event["id"], value))
            else:
                self.db.execute("DELETE FROM devices WHERE token=? AND user_id=?", (value, uid))
            return {"ok": True}
        if path == "/alerts" and method == "GET":
            elders = self.rows("SELECT id FROM elders WHERE owner=? OR id IN (SELECT elder_id FROM members WHERE user_id=?)", (uid, uid))
            return {"elders": [{"id": e["id"], "events": self.event_rows(e["id"], uid)} for e in elders]}
        if path == "/elders" and method == "GET":
            return {"elders": [self.snapshot(e, uid) for e in self.rows("SELECT * FROM elders WHERE owner=? OR id IN (SELECT elder_id FROM members WHERE user_id=?)", (uid, uid))]}
        if path == "/elders" and method == "POST":
            name = data.get("name", "")
            require(isinstance(name, str) and 1 <= len(name.strip()) <= 40, "请填写老人称呼")
            eid, code = secrets.token_hex(12), secrets.token_hex(5).upper()
            settings = {"fence": None, "trip": None, "outside_delay": 120, "offline_after": 600}
            self.db.execute("INSERT INTO elders(id,name,owner,pair_code,pair_expires,created,settings) VALUES(?,?,?,?,?,?,?)", (eid, name.strip(), uid, code, now + 900, now, json.dumps(settings)))
            return {"id": eid, "code": code, "expires": now + 900}
        if path == "/invites/accept" and method == "POST":
            invite = self.one("SELECT * FROM invites WHERE code=? AND expires>?", (data.get("code"), now))
            require(invite, "邀请无效或已过期", 404)
            elder = self.one("SELECT owner FROM elders WHERE id=?", (invite["elder_id"],))
            require(elder["owner"] != uid, "主管理员无需接受自己的邀请")
            self.db.execute("INSERT INTO members VALUES(?,?,?) ON CONFLICT(elder_id,user_id) DO UPDATE SET can_edit=excluded.can_edit", (invite["elder_id"], uid, invite["can_edit"]))
            self.db.execute("DELETE FROM invites WHERE code=?", (invite["code"],))
            return {"ok": True}
        parts = path.strip("/").split("/")
        require(len(parts) >= 2 and parts[0] == "elders", "接口不存在", 404)
        eid = parts[1]
        if len(parts) == 2 and method == "GET":
            return self.snapshot(self.access(eid, uid), uid)
        action = parts[2] if len(parts) > 2 else ""
        if action == "setup-request" and method == "POST":
            elder = self.access(eid, uid, edit=True)
            require(elder["consent"], "请先绑定老人手机", 409)
            action_name = data.get("action")
            require(action_name in ("location", "background", "battery", "notifications", "startup"), "不支持此设置提醒")
            previous = self.setup_request(eid)
            if previous and previous["action"] == action_name and previous["state"] in ("pending", "received", "notified"):
                return previous
            require(not previous or now - previous["requested_at"] >= 30, "请间隔30秒再发送设置提醒", 429)
            request_id = secrets.token_hex(12)
            self.db.execute("INSERT OR REPLACE INTO elder_setup_requests VALUES(?,?,?,?,?,?)", (eid, request_id, action_name, now, now + 3600, "pending"))
            self.enqueue_elder(eid, "setup", 3600, request_id)
            return self.setup_request(eid)
        if action == "location-request" and method == "POST":
            elder = self.access(eid, uid)
            require(elder["consent"], "请先绑定老人手机", 409)
            previous = self.location_request(eid)
            if previous and previous["state"] in ("pending", "received"):
                return previous
            require(not previous or now - previous["requested_at"] >= 30, "请稍后再请求定位", 429)
            self.db.execute("INSERT OR REPLACE INTO location_requests(elder_id,id,requested_at,expires,state,completed_at,completion_source) VALUES(?,?,?,?,?,NULL,NULL)",
                            (eid, secrets.token_hex(12), now, now + 180, "pending"))
            pending = self.location_request(eid)
            self.enqueue_elder(eid, "location", 180, pending["id"])
            return pending
        if action == "pair-code" and method == "POST":
            elder = self.access(eid, uid, owner=True)
            require(type(data.get("replace", False)) is bool, "重新绑定参数无效")
            require(not elder["consent"] or data.get("replace") is True,
                    "设备已绑定，请使用重新绑定入口", 409)
            code = secrets.token_hex(5).upper()
            self.db.execute("UPDATE elders SET pair_code=?,pair_expires=? WHERE id=?", (code, now + 900, eid))
            return {"code": code, "expires": now + 900}
        if action == "settings" and method == "PUT":
            elder = self.access(eid, uid, edit=True)
            require(data.get("version") == elder["version"], "设置已被其他家属修改，请刷新后重试", 409)
            settings = data.get("settings")
            require(isinstance(settings, dict), "设置格式错误")
            interval = settings.get("automatic_interval", json.loads(elder["settings"]).get("automatic_interval", 60))
            require(type(interval) is int and 30 <= interval <= 120, "自动采集间隔需30–120秒整数")
            number(settings, "outside_delay", 30, 1800)
            number(settings, "offline_after", 180, 3600)
            fence, trip = settings.get("fence"), settings.get("trip")
            if fence is not None:
                require(isinstance(fence, dict), "围栏格式错误")
                coordinates(fence)
                number(fence, "radius", 1, 10000)
            if trip is not None:
                require(isinstance(trip, dict), "行程格式错误")
                coordinates(trip)
                number(trip, "radius", 1, 2000)
                require(isinstance(trip.get("name"), str) and 1 <= len(trip["name"]) <= 100, "请填写目的地名称")
                require(trip.get("status") in ("active", "arrived", "cancelled"), "行程状态无效")
                old_trip = json.loads(elder["settings"]).get("trip")
                if trip != old_trip:
                    number(trip, "deadline", now + 60, now + 7 * 86400)
            settings = {"fence": ({k: fence[k] for k in ("lat", "lon", "radius")} if fence else None),
                        "trip": ({k: trip[k] for k in ("name", "lat", "lon", "radius", "deadline", "status")} if trip else None),
                        "outside_delay": settings["outside_delay"], "offline_after": settings["offline_after"], "automatic_interval": interval}
            self.db.execute("UPDATE elders SET settings=?,version=version+1,outside_since=NULL,outside_count=0 WHERE id=?", (json.dumps(settings), eid))
            self.enqueue_elder(eid, "settings", 3600)
            self.resolve(eid, "outside")
            self.resolve(eid, "overdue")
            if not automatic_guard(settings):
                self.resolve(eid, "offline")
            return self.snapshot(self.one("SELECT * FROM elders WHERE id=?", (eid,)), uid)
        if action == "invites" and method == "POST":
            self.access(eid, uid, owner=True)
            require(type(data.get("can_edit", False)) is bool, "权限格式错误")
            code = secrets.token_urlsafe(12)
            self.db.execute("INSERT INTO invites VALUES(?,?,?,?)", (code, eid, int(data.get("can_edit", False)), now + 86400))
            return {"code": code, "expires": now + 86400}
        if action == "members" and len(parts) == 4 and method == "DELETE":
            self.access(eid, uid, owner=True)
            self.db.execute("DELETE FROM members WHERE elder_id=? AND user_id=?", (eid, parts[3]))
            return {"ok": True}
        if action == "events" and len(parts) == 4 and method == "DELETE":
            self.access(eid, uid, edit=True)
            event = self.one("SELECT * FROM events WHERE id=? AND elder_id=?", (parts[3], eid))
            require(event, "提醒不存在或已被删除", 404)
            if event["active"]:
                # Remember only the current incident kind, never the deleted content/location.
                self.db.execute("INSERT OR IGNORE INTO muted_incidents VALUES(?,?)", (eid, event["kind"]))
            self.db.execute("DELETE FROM outbox WHERE event_id=?", (event["id"],))
            self.db.execute("DELETE FROM events WHERE id=? AND elder_id=?", (event["id"], eid))
            return {"ok": True}
        if action == "events" and len(parts) == 5 and parts[4] == "ack" and method == "POST":
            self.access(eid, uid)
            event = self.one("SELECT * FROM events WHERE id=? AND elder_id=?", (parts[3], eid))
            require(event, "提醒不存在", 404)
            require(not event["acknowledged_by"] or event["acknowledged_by"] == uid, "已有其他家属接手，请刷新", 409)
            self.db.execute("UPDATE events SET acknowledged_by=?,acknowledged_at=? WHERE id=?", (uid, now, parts[3]))
            return {"ok": True}
        raise APIError(404, "接口不存在")


class PushWorker:
    def __init__(self, store):
        self.store = store

    def send(self, item):
        import httpx
        import jwt
        with open(os.environ["APNS_KEY_PATH"]) as f:
            key = f.read()
        auth = jwt.encode({"iss": os.environ["APNS_TEAM_ID"], "iat": int(time.time())}, key, algorithm="ES256", headers={"kid": os.environ["APNS_KEY_ID"]})
        host = "api.push.apple.com" if os.getenv("APNS_ENV") == "production" else "api.sandbox.push.apple.com"
        payload = {"aps": {"alert": {"title": "家人守护提醒", "body": item["message"]}, "sound": "default"}, "elder_id": item["elder_id"], "event_id": item["event_id"]}
        # Exact coordinates are fetched after authenticated app launch, not exposed on the lock screen.
        with httpx.Client(http2=True, timeout=10) as client:
            response = client.post(f"https://{host}/3/device/{item['token']}", json=payload, headers={"authorization": "bearer " + auth, "apns-topic": os.environ["APNS_TOPIC"], "apns-push-type": "alert", "apns-priority": "10", "apns-expiration": str(int(time.time() + 3600))})
        return response.status_code, response.text[:200]

    def run_once(self):
        s = self.store
        if not all(os.getenv(k) for k in ("APNS_KEY_PATH", "APNS_KEY_ID", "APNS_TEAM_ID", "APNS_TOPIC")):
            return  # Remains pending, never falsely marked as delivered.
        with s.lock:
            items = s.rows("SELECT o.*,e.elder_id,e.message,e.active,e.acknowledged_by FROM outbox o JOIN events e ON e.id=o.event_id WHERE state='pending' AND next_attempt<=? LIMIT 20", (s.clock(),))
        for item in items:
            with s.lock:
                current = s.one("SELECT active,acknowledged_by FROM events WHERE id=?", (item["event_id"],))
                d = s.one("SELECT user_id FROM devices WHERE token=?", (item["token"],))
                authorized = False
                if d:
                    try:
                        s.access(item["elder_id"], d["user_id"])
                        authorized = True
                    except APIError:
                        pass
            state, error = "cancelled", None
            if authorized and current and current["active"] and not current["acknowledged_by"]:
                try:
                    status, error = self.send(item)
                    state = "accepted" if status == 200 else "failed" if status in (400, 403, 410) else "pending"
                    if status == 410:
                        with s.lock, s.db:
                            s.db.execute("DELETE FROM devices WHERE token=?", (item["token"],))
                except Exception as exc:
                    state, error = "pending", type(exc).__name__
            attempts = item["attempts"] + 1
            if attempts >= 8 and state == "pending":
                state = "failed"
            with s.lock, s.db:
                s.db.execute("UPDATE outbox SET state=?,attempts=?,next_attempt=?,last_error=? WHERE event_id=? AND token=?", (state, attempts, s.clock() + min(3600, 15 * 2 ** attempts), error, item["event_id"], item["token"]))


class Handler(BaseHTTPRequestHandler):
    store = None
    attempts = {}
    rate_lock = threading.Lock()

    def log_message(self, fmt, *args):
        # Do not log URLs, credentials, tokens or locations.
        pass

    def handle_api(self):
        try:
            path = urlsplit(self.path).path
            if path.startswith("/auth/") or path == "/device/pair" or path == "/invites/accept":
                key = (self.client_address[0], path)
                with self.rate_lock:
                    now = time.time()
                    self.attempts = {k: v for k, v in self.attempts.items() if now - v[0] < 60}
                    start, count = self.attempts.get(key, (now, 0))
                    require(count < 20, "请求过于频繁，请稍后重试", 429)
                    self.attempts[key] = (start, count + 1)
                    type(self).attempts = self.attempts
            length = int(self.headers.get("Content-Length", 0))
            require(0 <= length <= 65536, "请求内容过大", 413)
            data = json.loads(self.rfile.read(length)) if length else {}
            require(isinstance(data, dict), "请求必须是 JSON 对象")
            token = self.headers.get("Authorization", "").removeprefix("Bearer ")
            if self.command == "GET" and path == "/device/events":
                stream = self.store.open_command_stream(token)
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    for chunk in stream:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                except OSError:
                    pass
                finally:
                    stream.close()
                    self.close_connection = True
                return
            result = self.store.dispatch(self.command, path, data, token)
            self.respond(200, result)
        except APIError as exc:
            self.respond(exc.status, {"error": exc.message})
        except (ValueError, TypeError, UnicodeDecodeError):
            self.respond(400, {"error": "请求格式错误"})
        except Exception:
            self.respond(500, {"error": "服务暂时不可用"})

    def respond(self, status, body):
        payload = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    do_GET = do_POST = do_PUT = do_DELETE = handle_api


def main():
    os.umask(0o077)
    host = os.getenv("HOST", "127.0.0.1")
    try:
        port = int(os.getenv("PORT", "8087"))
        require(0 < port <= 65535, "PORT 必须在 1 至 65535 之间")
    except (ValueError, APIError):
        print("PORT 必须是 1 至 65535 之间的整数。", file=sys.stderr)
        return 2
    try:
        server = ThreadingHTTPServer((host, port), Handler)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            print(f"启动失败：{host}:{port} 已被占用。请停止已有后台，或使用其他端口，例如：\nPORT={port + 1 if port < 65535 else 8087} python3 -m backend.server\n手机 App 中的服务地址也需要使用相同端口。", file=sys.stderr)
            return 1
        raise
    Handler.store = Store(os.getenv("DATABASE_PATH", "family.sqlite3"))
    push = PushWorker(Handler.store)
    stopped = threading.Event()
    command_worker = threading.Thread(target=run_command_push, args=(Handler.store, stopped), daemon=True)
    command_worker.start()
    def monitor():
        while not stopped.is_set():
            try:
                Handler.store.tick()
                push.run_once()
            except Exception as exc:
                print("Monitor error:", type(exc).__name__, flush=True)
            stopped.wait(15)
    worker = threading.Thread(target=monitor, daemon=True)
    worker.start()
    print(f"Family safety API: http://{host}:{port}; APNs requires environment configuration", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n后台已停止。", flush=True)
    finally:
        stopped.set()
        Handler.store.close_command_streams()
        Handler.store.command_ready.set()
        server.server_close()
        worker.join(timeout=1)
        command_worker.join(timeout=1)
        if not worker.is_alive() and not command_worker.is_alive():
            Handler.store.db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
