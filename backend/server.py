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
from backend.elder_push import ElderPushWorker, configured as elder_push_configured


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
        CREATE TABLE IF NOT EXISTS location_requests(elder_id TEXT PRIMARY KEY REFERENCES elders(id),
          id TEXT, requested_at REAL, expires REAL, state TEXT, completed_at REAL);
        CREATE TABLE IF NOT EXISTS elder_push_devices(elder_id TEXT PRIMARY KEY REFERENCES elders(id), cid TEXT UNIQUE, app_id TEXT);
        CREATE TABLE IF NOT EXISTS elder_outbox(elder_id TEXT REFERENCES elders(id), kind TEXT,
          generation TEXT, expires REAL, state TEXT, attempts INTEGER DEFAULT 0,
          next_attempt REAL DEFAULT 0, last_error TEXT, PRIMARY KEY(elder_id,kind));
        CREATE TABLE IF NOT EXISTS devices(token TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS outbox(event_id TEXT REFERENCES events(id), token TEXT,
          state TEXT DEFAULT 'pending', attempts INTEGER DEFAULT 0, next_attempt REAL DEFAULT 0,
          last_error TEXT, PRIMARY KEY(event_id,token));
        """)

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
        if self.one("SELECT id FROM events WHERE elder_id=? AND kind=? AND active=1", (elder["id"], kind)):
            return
        eid = secrets.token_hex(12)
        self.db.execute("INSERT INTO events(id,elder_id,kind,message,created,location) VALUES(?,?,?,?,?,?)",
                        (eid, elder["id"], kind, message, self.clock(), elder["last_location"]))
        for d in self.rows("SELECT token FROM devices WHERE user_id=? OR user_id IN (SELECT user_id FROM members WHERE elder_id=?)",
                           (elder["owner"], elder["id"])):
            self.db.execute("INSERT OR IGNORE INTO outbox(event_id,token) VALUES(?,?)", (eid, d["token"]))

    def resolve(self, elder_id, kind):
        self.db.execute("UPDATE events SET active=0 WHERE elder_id=? AND kind=?", (elder_id, kind))

    def enqueue_elder(self, elder_id, kind, ttl, generation=None):
        self.db.execute("INSERT OR REPLACE INTO elder_outbox(elder_id,kind,generation,expires,state) VALUES(?,?,?,?, 'pending')",
                        (elder_id, kind, generation or secrets.token_hex(12), self.clock() + ttl))

    def elder_push_status(self, elder_id):
        device = self.one("SELECT app_id FROM elder_push_devices WHERE elder_id=?", (elder_id,))
        ready = bool(device and device["app_id"] == os.getenv("GETUI_APP_ID", "").strip())
        return {"configured": elder_push_configured(), "registered": ready,
                "location_delivery": self.one("SELECT state,last_error FROM elder_outbox WHERE elder_id=? AND kind='location'", (elder_id,)),
                "settings_delivery": self.one("SELECT state,last_error FROM elder_outbox WHERE elder_id=? AND kind='settings'", (elder_id,))}

    def location_request(self, elder_id):
        self.db.execute("UPDATE location_requests SET state='expired' WHERE elder_id=? AND state IN ('pending','received') AND expires<=?", (elder_id, self.clock()))
        return self.one("SELECT id,requested_at,expires,state,completed_at FROM location_requests WHERE elder_id=?", (elder_id,))

    def snapshot(self, elder, uid):
        result = {k: elder[k] for k in ("id", "name", "last_seen", "version", "applied_version", "created")}
        result["location"] = json.loads(elder["last_location"]) if elder["last_location"] else None
        result["settings"] = json.loads(elder["settings"])
        result["location_request"] = self.location_request(elder["id"])
        result["elder_push"] = self.elder_push_status(elder["id"])
        result["paired"] = bool(elder["consent"])
        result["is_owner"] = elder["owner"] == uid
        member = self.one("SELECT can_edit FROM members WHERE elder_id=? AND user_id=?", (elder["id"], uid))
        result["can_edit"] = result["is_owner"] or bool(member and member["can_edit"])
        result["events"] = self.rows("SELECT e.*,u.name AS handler FROM events e LEFT JOIN users u ON u.id=e.acknowledged_by WHERE elder_id=? ORDER BY created DESC LIMIT 100", (elder["id"],))
        for event in result["events"]:
            event["location"] = json.loads(event["location"]) if event["location"] else None
            # Read notification state only for this account's devices.
            event["delivery"] = self.rows("SELECT state,attempts,last_error FROM outbox WHERE event_id=? AND token IN (SELECT token FROM devices WHERE user_id=?)", (event["id"], uid))
        if result["is_owner"]:
            result["members"] = self.rows("SELECT u.id,u.name,m.can_edit FROM members m JOIN users u ON u.id=m.user_id WHERE elder_id=?", (elder["id"],))
        else:
            result["members"] = []
        return result

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
            return self._dispatch(method, path, data, token)

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
            elder = self.one("SELECT * FROM elders WHERE pair_code=? AND pair_expires>? AND consent=0", (data.get("code"), now))
            require(elder, "绑定码无效或已过期", 404)
            device_token = secrets.token_urlsafe(32)
            self.db.execute("UPDATE elders SET consent=1,device_token=?,pair_code=NULL,created=?,last_location=NULL,last_seen=NULL,outside_since=NULL,outside_count=0,applied_version=0 WHERE id=?", (digest(device_token), now, elder["id"]))
            return {"token": device_token, "elder_id": elder["id"], "name": elder["name"]}
        if path.startswith("/device/"):
            elder = self.one("SELECT * FROM elders WHERE device_token=? AND consent=1", (digest(token),))
            require(elder, "设备尚未绑定", 401)
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
                return {"location_request": request, "version": elder["version"], "settings": json.loads(elder["settings"])}
            if method == "GET" and path == "/device/settings":
                return {"version": elder["version"], "settings": json.loads(elder["settings"])}
            if method == "POST" and path == "/device/unpair":
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
                self.db.execute("UPDATE elders SET last_location=?,last_seen=?,applied_version=? WHERE id=?", (json.dumps(loc), now, data["applied_version"], elder["id"]))
                if now - loc["recorded_at"] < 120:
                    self.resolve(elder["id"], "offline")
                settings = json.loads(elder["settings"])
                fence = settings.get("fence")
                trip = settings.get("trip")
                if previous and loc["recorded_at"] - previous["recorded_at"] > 120:
                    self.db.execute("UPDATE elders SET outside_since=NULL,outside_count=0 WHERE id=?", (elder["id"],))
                if fence and not (trip and trip["status"] in ("active", "arrived")) and loc["accuracy"] <= 100 and now - loc["recorded_at"] < 120 and distance(loc, fence) - loc["accuracy"] > fence["radius"]:
                    self.db.execute("UPDATE elders SET outside_since=COALESCE(outside_since,?),outside_count=outside_count+1 WHERE id=?", (loc["recorded_at"], elder["id"]))
                else:
                    # Uncertain or low-quality samples cannot substantiate continuous outside dwell.
                    self.db.execute("UPDATE elders SET outside_since=NULL,outside_count=0 WHERE id=?", (elder["id"],))
                if request_id and request["state"] in ("pending", "received"):
                    self.db.execute("UPDATE location_requests SET state='completed',completed_at=? WHERE elder_id=?", (now, elder["id"]))
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
        if action == "location-request" and method == "POST":
            elder = self.access(eid, uid)
            require(elder["consent"], "请先绑定老人手机", 409)
            previous = self.location_request(eid)
            if previous and previous["state"] in ("pending", "received"):
                return previous
            require(not previous or now - previous["requested_at"] >= 30, "请稍后再请求定位", 429)
            self.db.execute("INSERT OR REPLACE INTO location_requests VALUES(?,?,?,?,?,NULL)",
                            (eid, secrets.token_hex(12), now, now + 180, "pending"))
            pending = self.location_request(eid)
            self.enqueue_elder(eid, "location", 180, pending["id"])
            return pending
        if action == "pair-code" and method == "POST":
            elder = self.access(eid, uid, owner=True)
            require(not elder["consent"], "设备已绑定，请先在老人手机解除共享", 409)
            code = secrets.token_hex(5).upper()
            self.db.execute("UPDATE elders SET pair_code=?,pair_expires=? WHERE id=?", (code, now + 900, eid))
            return {"code": code, "expires": now + 900}
        if action == "settings" and method == "PUT":
            elder = self.access(eid, uid, edit=True)
            require(data.get("version") == elder["version"], "设置已被其他家属修改，请刷新后重试", 409)
            settings = data.get("settings")
            require(isinstance(settings, dict), "设置格式错误")
            number(settings, "outside_delay", 30, 1800)
            number(settings, "offline_after", 180, 3600)
            fence, trip = settings.get("fence"), settings.get("trip")
            if fence is not None:
                require(isinstance(fence, dict), "围栏格式错误")
                coordinates(fence)
                number(fence, "radius", 100, 10000)
            if trip is not None:
                require(isinstance(trip, dict), "行程格式错误")
                coordinates(trip)
                number(trip, "radius", 100, 2000)
                require(isinstance(trip.get("name"), str) and 1 <= len(trip["name"]) <= 100, "请填写目的地名称")
                require(trip.get("status") in ("active", "arrived", "cancelled"), "行程状态无效")
                old_trip = json.loads(elder["settings"]).get("trip")
                if trip != old_trip:
                    number(trip, "deadline", now + 60, now + 7 * 86400)
            settings = {"fence": ({k: fence[k] for k in ("lat", "lon", "radius")} if fence else None),
                        "trip": ({k: trip[k] for k in ("name", "lat", "lon", "radius", "deadline", "status")} if trip else None),
                        "outside_delay": settings["outside_delay"], "offline_after": settings["offline_after"]}
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
    elder_push = ElderPushWorker(Handler.store)
    stopped = threading.Event()
    def monitor():
        while not stopped.is_set():
            try:
                Handler.store.tick()
                push.run_once()
                elder_push.run_once()
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
        server.server_close()
        worker.join(timeout=1)
        if not worker.is_alive():
            Handler.store.db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
