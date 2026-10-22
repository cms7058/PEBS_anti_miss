import hashlib
import json
import os
import unittest
from unittest.mock import Mock, patch
from backend.server import APIError, Store
from backend.elder_push import ElderPushWorker, GetuiClient

ENV = {"GETUI_APP_ID": "NtGxfjmcjPAb27hjz2R1e1", "GETUI_APP_KEY": "test-key", "GETUI_MASTER_SECRET": "test-secret"}


class ElderPushTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, ENV)
        self.env.start()
        self.now = 1800000000.0
        self.s = Store(":memory:", lambda: self.now)
        self.user = self.s.dispatch("POST", "/auth/register", {"name": "guardian", "password": "test-password-123"})["token"]
        elder = self.call("POST", "/elders", {"name": "测试"})
        self.eid = elder["id"]
        self.device = self.s.dispatch("POST", "/device/pair", {"code": elder["code"], "consent": True})["token"]
        self.client = Mock()
        self.worker = ElderPushWorker(self.s, self.client)

    def tearDown(self):
        self.s.db.close()
        self.env.stop()

    def call(self, method, path, data=None, token=None):
        return self.s.dispatch(method, path, data or {}, token or self.user)

    def register(self):
        return self.call("POST", "/device/push", {"cid": "a" * 32, "app_id": ENV["GETUI_APP_ID"]}, self.device)

    def test_location_and_settings_queue_and_receive(self):
        self.register()
        request = self.call("POST", f"/elders/{self.eid}/location-request")
        self.worker.run_once()
        self.assertEqual(self.client.send.call_count, 2)
        self.assertEqual(self.s.one("SELECT state FROM elder_outbox WHERE kind='location'")["state"], "accepted")
        self.assertEqual(self.s.location_request(self.eid)["state"], "pending")
        self.call("GET", "/device/commands", token=self.device)
        self.assertEqual(self.s.location_request(self.eid)["state"], "received")
        self.assertEqual(self.s.one("SELECT state FROM elder_outbox WHERE kind='location'")["state"], "received")
        snapshot = self.call("GET", f"/elders/{self.eid}")
        settings = snapshot["settings"]
        settings["fence"] = {"lat": 31, "lon": 121, "radius": 500}
        self.call("PUT", f"/elders/{self.eid}/settings", {"version": snapshot["version"], "settings": settings})
        self.assertEqual(self.s.one("SELECT state FROM elder_outbox WHERE kind='settings'")["state"], "pending")
        self.assertEqual(self.s.location_request(self.eid)["id"], request["id"])

    def test_missing_credentials_and_device_do_not_claim_acceptance(self):
        self.call("POST", f"/elders/{self.eid}/location-request")
        self.worker.run_once()
        self.client.send.assert_not_called()
        self.register()
        with patch.dict(os.environ, {"GETUI_MASTER_SECRET": ""}):
            self.worker.run_once()
            status = self.call("GET", f"/elders/{self.eid}")["elder_push"]
            self.assertFalse(status["configured"])
        self.client.send.assert_not_called()
        self.assertEqual(self.s.one("SELECT state FROM elder_outbox WHERE kind='location'")["state"], "pending")

    def test_expiry_stop_and_unpair(self):
        self.register()
        self.call("POST", f"/elders/{self.eid}/location-request")
        self.now += 181
        self.worker.run_once()
        self.assertEqual(self.s.one("SELECT state FROM elder_outbox WHERE kind='location'")["state"], "expired")
        self.client.reset_mock()
        self.call("POST", "/device/push", {"enabled": False}, self.device)
        self.worker.run_once()
        self.client.send.assert_not_called()
        self.assertFalse(self.s.rows("SELECT * FROM elder_push_devices"))
        self.register()
        self.call("POST", "/device/unpair", token=self.device)
        self.assertFalse(self.s.rows("SELECT * FROM elder_outbox"))
        with self.assertRaises(APIError): self.register()

    def test_retry_redacts_errors_and_concurrent_fetch_preserves_received(self):
        self.register()
        self.client.send.side_effect = RuntimeError("secret must never be logged")
        self.worker.run_once()
        row = self.s.one("SELECT * FROM elder_outbox")
        self.assertEqual(row["attempts"], 1)
        self.assertNotIn("secret", row["last_error"])
        self.now += 11
        self.client.send.side_effect = lambda *args: self.call("GET", "/device/commands", token=self.device)
        self.worker.run_once()
        self.assertEqual(self.s.one("SELECT state FROM elder_outbox")["state"], "received")

    def test_registration_scoped_and_idempotent(self):
        with self.assertRaises(APIError):
            self.call("POST", "/device/push", {"cid": "a" * 32, "app_id": ENV["GETUI_APP_ID"]})
        with self.assertRaises(APIError):
            self.call("POST", "/device/push", {"cid": "a" * 32, "app_id": "wrong"}, self.device)
        self.register()
        self.call("GET", "/device/commands", token=self.device)
        self.register()
        self.assertEqual(self.s.one("SELECT state FROM elder_outbox")["state"], "received")

    def test_api_authentication_and_signal_has_no_location_or_credentials(self):
        client = GetuiClient()
        results = [{"code": 0, "data": {"token": "test-token", "expire_time": "9999999999999"}}, {"code": 0}]
        with patch.object(client, "post", side_effect=results) as post, patch("time.time", return_value=1800000000):
            client.send("a" * 32, 180)
        auth = post.call_args_list[0].args[1]
        self.assertEqual(auth["sign"], hashlib.sha256(b"test-key1800000000000test-secret").hexdigest())
        path, body, token = post.call_args_list[1].args
        self.assertEqual(path, "/push/single/cid")
        self.assertEqual(body["settings"]["ttl"], 180000)
        self.assertEqual(json.loads(body["push_message"]["transmission"]), {"type": "sync_commands"})
        self.assertNotIn("test-secret", json.dumps(body))
        self.assertEqual(token, "test-token")
