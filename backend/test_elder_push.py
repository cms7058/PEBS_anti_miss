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

    def test_new_location_request_wakes_dispatcher_and_precedes_settings(self):
        self.register()
        self.s.command_ready.clear()
        self.call("POST", f"/elders/{self.eid}/location-request")
        self.assertTrue(self.s.command_ready.is_set())
        sent = []
        self.client.send.side_effect = lambda *_: sent.append(self.s.rows("SELECT kind FROM elder_outbox WHERE attempts>0"))
        self.worker.run_once()
        self.assertEqual(sent[0], [])
        self.assertEqual(sent[1], [{"kind": "location"}])

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

    def test_accepted_without_phone_receipt_retries_then_stops_on_receipt(self):
        self.register()
        self.call("GET", "/device/commands", token=self.device)
        self.call("POST", f"/elders/{self.eid}/location-request")
        self.worker.run_once()
        self.assertEqual(self.client.send.call_count, 1)
        self.now += 19
        self.worker.run_once()
        self.assertEqual(self.client.send.call_count, 1)
        self.now += 1
        self.worker.run_once()
        self.assertEqual(self.client.send.call_count, 2)
        self.assertEqual(self.s.location_request(self.eid)["state"], "pending")
        self.call("GET", "/device/commands", token=self.device)
        self.now += 61
        self.worker.run_once()
        self.assertEqual(self.client.send.call_count, 2)
        self.assertEqual(self.s.one("SELECT state FROM elder_outbox WHERE kind='location'")["state"], "received")

    def test_accepted_hints_have_a_send_limit_and_original_expiry(self):
        self.register()
        for _ in range(7):
            self.worker.run_once()
            self.now += 61
        self.assertEqual(self.client.send.call_count, 5)
        row = self.s.one("SELECT * FROM elder_outbox WHERE kind='settings'")
        self.assertEqual(row["attempts"], 5)
        self.assertEqual(row["state"], "accepted")
        self.now += 3600
        self.worker.run_once()
        self.assertEqual(self.s.one("SELECT state FROM elder_outbox WHERE kind='settings'")["state"], "expired")
        self.assertEqual(self.client.send.call_count, 5)

    def test_ack_during_accepted_retry_is_not_overwritten(self):
        self.register()
        self.worker.run_once()
        self.now += 20
        self.client.send.side_effect = lambda *args: self.call("GET", "/device/commands", token=self.device)
        self.worker.run_once()
        self.assertEqual(self.s.one("SELECT state FROM elder_outbox")["state"], "received")

    def test_location_completed_during_send_stays_cancelled(self):
        self.register()
        self.call("GET", "/device/commands", token=self.device)
        request = self.call("POST", f"/elders/{self.eid}/location-request")
        self.now += 1
        self.client.send.side_effect = lambda *args: self.call("POST", "/device/location", {
            "lat":31, "lon":121, "accuracy":20, "recorded_at":self.now,
            "battery":70, "applied_version":0, "request_id":request["id"]}, self.device)
        self.worker.run_once()
        self.assertEqual(self.s.location_request(self.eid)["state"], "completed")
        self.assertEqual(self.s.one("SELECT state FROM elder_outbox WHERE kind='location'")["state"], "cancelled")
        self.now += 30
        self.worker.run_once()
        self.assertEqual(self.client.send.call_count, 1)

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

    def test_rebinding_removes_old_push_identity(self):
        self.register()
        code = self.call("POST", f"/elders/{self.eid}/pair-code", {"replace": True})["code"]
        self.assertTrue(self.s.rows("SELECT * FROM elder_push_devices"))
        paired = self.call("POST", "/device/pair", {"code": code, "consent": True})
        self.assertFalse(self.s.rows("SELECT * FROM elder_push_devices"))
        self.assertFalse(self.s.rows("SELECT * FROM elder_outbox"))
        self.worker.run_once()
        self.client.send.assert_not_called()
        self.device = paired["token"]
        self.register()
        self.assertTrue(self.s.rows("SELECT * FROM elder_push_devices"))

    def test_device_diagnostics_are_authenticated_and_scoped(self):
        data={"app_version":"0.1.4","push_consent":True,"cid_available":False,"registration_state":"waiting_cid"}
        with self.assertRaises(APIError): self.call("POST","/device/diagnostics",data)
        self.call("POST","/device/diagnostics",data,self.device)
        diag=self.call("GET",f"/elders/{self.eid}")["device_diagnostics"]
        self.assertEqual(diag["app_version"],"0.1.4")
        self.assertIs(diag["push_consent"],True)
        self.assertIs(diag["cid_available"],False)
        self.assertIsNone(diag["sdk_online"])
        for invalid in ({"app_version":"x"*50},{"sdk_online":1},{"registration_state":"unknown"}):
            with self.assertRaises(APIError): self.call("POST","/device/diagnostics",dict(data,**invalid),self.device)
        self.call("POST","/device/diagnostics",dict(data,registration_state="initialization_failed"),self.device)
        self.call("POST","/device/unpair",token=self.device)
        self.assertIsNone(self.call("GET",f"/elders/{self.eid}")["device_diagnostics"])

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
