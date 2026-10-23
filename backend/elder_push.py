"""Getui command hints. No credentials or location data are put in push payloads."""
import hashlib
import json
import os
import re
import secrets
import time
import urllib.request


def configured():
    return all(os.getenv(k, "").strip() for k in ("GETUI_APP_ID", "GETUI_APP_KEY", "GETUI_MASTER_SECRET"))


class GetuiClient:
    def __init__(self):
        self.token = None
        self.expires = 0

    def post(self, path, data, token=None):
        app_id = os.environ["GETUI_APP_ID"].strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{10,100}", app_id):
            raise ValueError("invalid app id")
        headers = {"Content-Type": "application/json"}
        if token:
            headers["token"] = token
        request = urllib.request.Request("https://restapi.getui.com/v2/" + app_id + path,
                                         data=json.dumps(data).encode(), headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read(65536))

    def authenticate(self):
        timestamp = str(int(time.time() * 1000))
        key = os.environ["GETUI_APP_KEY"].strip()
        secret = os.environ["GETUI_MASTER_SECRET"].strip()
        sign = hashlib.sha256((key + timestamp + secret).encode()).hexdigest()
        result = self.post("/auth", {"appkey": key, "timestamp": timestamp, "sign": sign})
        if result.get("code") != 0:
            raise ValueError("Getui authentication failed")
        self.token = result["data"]["token"]
        self.expires = int(result["data"]["expire_time"]) / 1000

    def send(self, cid, ttl):
        if not self.token or self.expires <= time.time() + 60:
            self.authenticate()
        payload = {"request_id": secrets.token_hex(16), "settings": {"ttl": max(1000, int(ttl * 1000))},
                   "audience": {"cid": [cid]},
                   "push_message": {"transmission": json.dumps({"type": "sync_commands"})}}
        result = self.post("/push/single/cid", payload, self.token)
        if result.get("code") == 10001:
            self.authenticate()
            result = self.post("/push/single/cid", payload, self.token)
        if result.get("code") != 0:
            raise ValueError("Getui rejected push")
        # API acceptance is NOT proof that the phone received it.


class ElderPushWorker:
    def __init__(self, store, client=None):
        self.store = store
        self.client = client or GetuiClient()

    def run_once(self):
        s = self.store
        with s.lock, s.db:
            s.db.execute("UPDATE elder_outbox SET state='expired' WHERE expires<=? AND state IN ('pending','accepted')", (s.clock(),))
            items = s.rows("SELECT * FROM elder_outbox WHERE state IN ('pending','accepted') AND attempts<5 AND next_attempt<=? AND expires>? LIMIT 20", (s.clock(), s.clock()))
        if not configured():
            return
        started = time.monotonic()
        for item in items:
            if time.monotonic() - started > 10:
                break
            with s.lock:
                device = s.one("SELECT p.cid FROM elder_push_devices p JOIN elders e ON e.id=p.elder_id WHERE e.id=? AND e.consent=1 AND p.app_id=?", (item["elder_id"], os.environ["GETUI_APP_ID"].strip()))
                current = s.one("SELECT generation,state FROM elder_outbox WHERE elder_id=? AND kind=?", (item["elder_id"], item["kind"]))
            if not device or not current or current["generation"] != item["generation"] or current["state"] not in ("pending", "accepted"):
                continue
            state, error = "accepted", None
            try:
                self.client.send(device["cid"], item["expires"] - s.clock())
            except Exception:
                # Never persist upstream error bodies, tokens or secrets.
                state, error = "pending", "推送发送失败，请检查个推配置和服务器网络"
            attempts = item["attempts"] + 1
            if state == "pending" and attempts >= 5:
                state = "failed"
            # Acceptance is not a phone acknowledgement. Retry hints until /device/commands
            # confirms receipt, bounded by five sends and the original request expiry.
            delay = min(60, 20 * 2 ** (attempts - 1)) if state == "accepted" else min(60, 5 * 2 ** attempts)
            with s.lock, s.db:
                s.db.execute("UPDATE elder_outbox SET state=?,attempts=?,next_attempt=?,last_error=? WHERE elder_id=? AND kind=? AND generation=? AND state IN ('pending','accepted')",
                             (state, attempts, s.clock() + delay, error,
                              item["elder_id"], item["kind"], item["generation"]))
