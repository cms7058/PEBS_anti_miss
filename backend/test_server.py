import copy
import json
import os
import unittest
from unittest.mock import patch
from backend.server import APIError, PushWorker, Store, distance


class SafetyFlowTests(unittest.TestCase):
    def setUp(self):
        self.now = 1800000000.0
        self.s = Store(":memory:", lambda: self.now)
        self.owner = self.register("daughter")
        self.other = self.register("son")
        self.stranger = self.register("outsider")
        self.created = self.call("POST", "/elders", {"name": "妈妈"})
        self.eid = self.created["id"]
        self.device = self.s.dispatch("POST", "/device/pair", {"code": self.created["code"], "consent": True})["token"]

    def tearDown(self):
        self.s.db.close()

    def register(self, name):
        return self.s.dispatch("POST", "/auth/register", {"name": name, "password": "a test password 123"})["token"]

    def call(self, method, path, data=None, token=None):
        return self.s.dispatch(method, path, data or {}, self.owner if token is None else token)

    def elder(self, token=None):
        return self.call("GET", "/elders/" + self.eid, token=token)

    def settings(self, **kwargs):
        elder = self.elder()
        settings = copy.deepcopy(elder["settings"])
        settings.update(kwargs)
        return self.call("PUT", f"/elders/{self.eid}/settings", {"version": elder["version"], "settings": settings})

    def upload(self, lat=31.0, lon=121.0, accuracy=10, age=0):
        return self.call("POST", "/device/location", {"lat": lat, "lon": lon, "accuracy": accuracy,
            "recorded_at": self.now - age, "battery": 70, "applied_version": self.elder()["version"]}, self.device)

    def active(self, kind):
        return [e for e in self.elder()["events"] if e["kind"] == kind and e["active"]]

    def invite(self, can_edit=False):
        code = self.call("POST", f"/elders/{self.eid}/invites", {"can_edit": can_edit})["code"]
        self.call("POST", "/invites/accept", {"code": code}, self.other)
        return code

    def request_location(self):
        return self.call("POST", f"/elders/{self.eid}/location-request")

    def test_three_minute_freshness_preserves_history_and_requires_new_capture(self):
        self.assertEqual(self.elder()["location_freshness"]["state"], "missing")
        self.upload()
        capture = self.elder()["location"]
        self.now += 179.999
        self.assertEqual(self.elder()["location_freshness"]["state"], "recent")
        self.now += .001
        snapshot = self.elder()
        self.assertEqual(snapshot["location_freshness"]["state"], "historical")
        self.assertEqual(snapshot["location_freshness"]["expires_at"], capture["recorded_at"] + 180)
        self.assertEqual(snapshot["location"], capture)
        # Expiry must not erase the timestamp used for anti-replay or offline detection.
        request = self.request_location()
        self.assertEqual(self.elder()["location_request"]["state"], "pending")
        with self.assertRaises(APIError):
            self.call("POST", "/device/location", dict(capture, applied_version=0, request_id=request["id"]), self.device)
        self.assertEqual(self.elder()["location_request"]["state"], "pending")
        self.now += 1
        self.upload()
        snapshot = self.elder()
        self.assertEqual(snapshot["location_freshness"]["state"], "recent")
        self.assertEqual(snapshot["location_request"]["state"], "completed")

    def test_location_provider_roundtrip_and_legacy_uploads(self):
        self.upload()
        self.assertNotIn("provider", self.elder()["location"])
        for provider in ("network", "gps"):
            self.now += 10
            request = self.request_location()
            payload = {"lat": 31, "lon": 121, "accuracy": 30, "recorded_at": self.now,
                       "battery": 70, "applied_version": 0, "provider": provider,
                       "request_id": request["id"]}
            self.call("POST", "/device/location", payload, self.device)
            self.assertEqual(self.elder()["location"]["provider"], provider)
            self.assertEqual(self.elder()["location_request"]["state"], "completed")
            self.now += 31
        payload["recorded_at"] = self.now
        payload["provider"] = "unknown-source"
        payload.pop("request_id")
        with self.assertRaises(APIError):
            self.call("POST", "/device/location", payload, self.device)
        self.assertEqual(self.elder()["location"]["provider"], "gps")

    def test_remote_location_requires_new_correlated_capture(self):
        self.upload()
        self.now += 10
        request = self.request_location()
        self.assertEqual(request["state"], "pending")
        self.assertEqual(self.request_location()["id"], request["id"])
        command = self.call("GET", "/device/commands", token=self.device)
        self.assertEqual(command["location_request"]["state"], "received")
        payload = {"lat": 31, "lon": 121, "accuracy": 10, "recorded_at": self.now - 1,
                   "battery": 70, "applied_version": 0, "request_id": request["id"]}
        with self.assertRaises(APIError):
            self.call("POST", "/device/location", payload, self.device)
        payload["recorded_at"] = self.now + 31
        with self.assertRaises(APIError):
            self.call("POST", "/device/location", payload, self.device)
        self.now += 2
        payload["recorded_at"] = self.now
        self.call("POST", "/device/location", payload, self.device)
        self.assertEqual(self.elder()["location_request"]["state"], "completed")
        self.assertEqual(self.elder()["location_request"]["completion_source"], "requested")
        self.assertEqual(self.elder()["location"]["recorded_at"], self.now)
        self.assertIsNone(self.call("GET", "/device/commands", token=self.device)["location_request"])
        with self.assertRaises(APIError) as ctx:
            self.request_location()
        self.assertEqual(ctx.exception.status, 429)

    def test_remote_location_permissions_expiry_and_unpair(self):
        with self.assertRaises(APIError):
            self.call("POST", f"/elders/{self.eid}/location-request", token=self.stranger)
        self.invite(False)
        request = self.call("POST", f"/elders/{self.eid}/location-request", token=self.other)
        self.now += 181
        self.assertEqual(self.elder()["location_request"]["state"], "expired")
        self.assertIsNone(self.call("GET", "/device/commands", token=self.device)["location_request"])
        self.assertNotEqual(self.request_location()["id"], request["id"])
        self.call("POST", "/device/unpair", token=self.device)
        self.assertIsNone(self.elder()["location_request"])
        with self.assertRaises(APIError): self.request_location()
        with self.assertRaises(APIError): self.call("GET", "/device/commands", token=self.device)

    def test_expired_request_cannot_be_completed_by_late_capture(self):
        request = self.request_location()
        self.now += 181
        self.call("POST", "/device/location", {"lat": 31, "lon": 121, "accuracy": 10,
            "recorded_at": self.now, "battery": 70, "applied_version": 0,
            "request_id": request["id"]}, self.device)
        self.assertEqual(self.elder()["location_request"]["state"], "expired")
        self.assertIsNone(self.elder()["location_request"]["completed_at"])

    def test_fresh_automatic_upload_answers_query_without_claiming_push_delivery(self):
        self.request_location()
        self.now += 1
        self.upload()
        self.assertEqual(self.elder()["location_request"]["state"], "completed")
        self.assertEqual(self.elder()["location_request"]["completion_source"], "automatic")
        self.assertEqual(self.s.one("SELECT state FROM elder_outbox WHERE kind='location'")["state"], "cancelled")
        with self.assertRaises(APIError):
            self.call("POST", "/device/location", {"lat": 31, "lon": 121, "accuracy": 10,
                "recorded_at": self.now + 1, "battery": 70, "applied_version": 0,
                "request_id": "wrong"}, self.device)

    def test_old_or_late_automatic_position_does_not_falsely_answer_query(self):
        self.request_location()
        self.now += 10
        self.upload(age=11)
        self.assertEqual(self.elder()["location_request"]["state"], "pending")
        self.now += 171
        self.upload()
        self.assertEqual(self.elder()["location_request"]["state"], "expired")
        self.assertEqual(self.elder()["location"]["recorded_at"], self.now)

    def test_delete_event_removes_server_content_queue_and_stops_same_incident_reappearing(self):
        self.invite(True)
        self.settings(fence={"lat":31,"lon":121,"radius":500})
        self.call("POST", "/push/device", {"token":"a"*64})
        self.upload()
        self.now += 601; self.s.tick()
        event=self.active("offline")[0]
        self.assertTrue(self.s.rows("SELECT * FROM outbox WHERE event_id=?",(event["id"],)))
        self.call("DELETE", f"/elders/{self.eid}/events/{event['id']}",token=self.other)
        self.assertIsNone(self.s.one("SELECT * FROM events WHERE id=?",(event["id"],)))
        self.assertFalse(self.s.rows("SELECT * FROM outbox WHERE event_id=?",(event["id"],)))
        self.assertFalse(self.elder()["events"])
        self.s.tick()
        self.assertFalse(self.active("offline"))
        self.now += 1; self.upload()
        self.now += 601; self.s.tick()
        self.assertEqual(len(self.active("offline")),1)
        self.assertNotEqual(self.active("offline")[0]["id"],event["id"])

    def test_event_deletion_authorization_and_elder_scope(self):
        self.invite(False)
        self.settings(fence={"lat":31,"lon":121,"radius":500})
        self.now += 601; self.s.tick()
        event=self.active("offline")[0]
        path=f"/elders/{self.eid}/events/{event['id']}"
        for token in (self.other,self.stranger):
            with self.assertRaises(APIError) as ctx: self.call("DELETE",path,token=token)
            self.assertEqual(ctx.exception.status,403)
        second=self.call("POST","/elders",{"name":"另一位"})
        with self.assertRaises(APIError):
            self.call("DELETE",f"/elders/{second['id']}/events/{event['id']}")
        self.assertTrue(self.active("offline"))
        self.now += 1; self.upload()
        self.call("DELETE",path)
        self.assertFalse(self.s.rows("SELECT * FROM muted_incidents"))
        with self.assertRaises(APIError) as ctx: self.call("DELETE",path)
        self.assertEqual(ctx.exception.status,404)

    def test_location_request_schema_upgrade_preserves_existing_request(self):
        import sqlite3, tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"legacy.sqlite3"
            db=sqlite3.connect(str(path))
            db.execute("CREATE TABLE location_requests(elder_id TEXT PRIMARY KEY,id TEXT,requested_at REAL,expires REAL,state TEXT,completed_at REAL)")
            db.execute("INSERT INTO location_requests VALUES(?,?,?,?,?,?)",("old","request",self.now,self.now+180,"pending",None))
            db.commit();db.close()
            migrated=Store(str(path),lambda:self.now)
            try:
                request=migrated.location_request("old")
                self.assertEqual(request["id"],"request")
                self.assertIsNone(request["completion_source"])
            finally: migrated.db.close()

    def test_pair_requires_consent_and_cannot_be_replayed(self):
        item = self.call("POST", "/elders", {"name": "爸爸"})
        with self.assertRaises(APIError):
            self.call("POST", "/device/pair", {"code": item["code"], "consent": False}, "")
        self.call("POST", "/device/pair", {"code": item["code"], "consent": True}, "")
        with self.assertRaises(APIError):
            self.call("POST", "/device/pair", {"code": item["code"], "consent": True}, "")

    def rebind_code(self, token=None):
        return self.call("POST", f"/elders/{self.eid}/pair-code", {"replace": True}, token)["code"]

    def test_rebind_keeps_old_device_until_new_consent_then_revokes_it(self):
        self.invite(True)
        self.settings(fence={"lat": 31, "lon": 121, "radius": 500})
        self.upload()
        self.request_location()
        code = self.rebind_code()
        self.assertEqual(self.call("GET", "/device/settings", token=self.device)["version"], 1)
        with self.assertRaises(APIError):
            self.call("POST", "/device/pair", {"code": code, "consent": False}, "")
        self.assertTrue(self.elder()["paired"])
        paired = self.call("POST", "/device/pair", {"code": code, "consent": True}, "")
        with self.assertRaises(APIError): self.call("GET", "/device/commands", token=self.device)
        settings = self.call("GET", "/device/settings", token=paired["token"])
        self.assertEqual(settings["settings"]["fence"]["radius"], 500)
        self.assertEqual(len(self.elder()["members"]), 1)
        self.assertIsNone(self.elder()["location_request"])
        self.assertFalse(self.s.rows("SELECT * FROM elder_outbox"))
        with self.assertRaises(APIError):
            self.call("POST", "/device/pair", {"code": code, "consent": True}, "")

    def test_rebind_is_owner_only_and_requires_explicit_replacement(self):
        self.invite(True)
        for token in (self.other, self.stranger):
            with self.assertRaises(APIError) as ctx: self.rebind_code(token)
            self.assertEqual(ctx.exception.status, 403)
        with self.assertRaises(APIError) as ctx:
            self.call("POST", f"/elders/{self.eid}/pair-code")
        self.assertEqual(ctx.exception.status, 409)
        self.assertTrue(self.call("GET", "/device/settings", token=self.device))

    def test_expired_rebind_code_does_not_disconnect_current_device(self):
        code = self.rebind_code()
        self.now += 901
        with self.assertRaises(APIError):
            self.call("POST", "/device/pair", {"code": code, "consent": True}, "")
        self.assertTrue(self.call("GET", "/device/settings", token=self.device))
        first = self.rebind_code()
        second = self.rebind_code()
        self.assertNotEqual(first, second)
        with self.assertRaises(APIError):
            self.call("POST", "/device/pair", {"code": first, "consent": True}, "")

    def test_expired_pair_and_session(self):
        item = self.call("POST", "/elders", {"name": "爸爸"})
        self.now += 901
        with self.assertRaises(APIError):
            self.call("POST", "/device/pair", {"code": item["code"], "consent": True}, "")
        self.now += 31 * 86400
        with self.assertRaises(APIError) as ctx:
            self.elder()
        self.assertEqual(ctx.exception.status, 401)

    def test_permissions_invites_and_revocation(self):
        with self.assertRaises(APIError): self.elder(self.stranger)
        code = self.invite()
        self.assertFalse(self.elder(self.other)["can_edit"])
        current = self.elder()
        with self.assertRaises(APIError): self.call("PUT", f"/elders/{self.eid}/settings", {"version": current["version"], "settings": current["settings"]}, self.other)
        with self.assertRaises(APIError): self.call("POST", "/invites/accept", {"code": code}, self.stranger)
        self.invite(True)
        self.assertTrue(self.elder(self.other)["can_edit"])
        with self.assertRaises(APIError): self.call("POST", f"/elders/{self.eid}/invites", {}, self.other)
        uid = self.s.user(self.other)
        self.call("DELETE", f"/elders/{self.eid}/members/{uid}")
        with self.assertRaises(APIError): self.elder(self.other)

    def test_simultaneous_settings_cannot_overwrite(self):
        old = self.elder()
        self.settings(offline_after=300)
        with self.assertRaises(APIError) as ctx:
            self.call("PUT", f"/elders/{self.eid}/settings", {"version": old["version"], "settings": old["settings"]})
        self.assertEqual(ctx.exception.status, 409)
        self.assertEqual(self.elder()["settings"]["offline_after"], 300)

    def test_outside_debounce_and_reentry(self):
        self.settings(fence={"lat": 31, "lon": 121, "radius": 500})
        self.upload(lat=31.02)
        self.assertFalse(self.active("outside"))
        self.now += 60; self.upload(lat=31.02)
        self.now += 61; self.upload(lat=31.02)
        self.assertEqual(len(self.active("outside")), 1)
        self.now += 30; self.upload(lat=31.02)
        self.assertEqual(len(self.active("outside")), 1)
        self.now += 30; self.upload()
        self.assertFalse(self.active("outside"))

    def test_one_fix_alone_does_not_trigger_outside(self):
        self.settings(fence={"lat": 31, "lon": 121, "radius": 500})
        self.upload(lat=31.02)
        self.now += 121; self.s.tick()
        self.assertFalse(self.active("outside"))

    def test_gps_noise_and_poor_accuracy_do_not_trigger(self):
        self.settings(fence={"lat": 31, "lon": 121, "radius": 500}, outside_delay=30)
        for _ in range(4):
            self.now += 40; self.upload(lat=31.0045, accuracy=40)
        self.assertFalse(self.active("outside"))
        for _ in range(4):
            self.now += 40; self.upload(lat=32, accuracy=500)
        self.assertFalse(self.active("outside"))

    def test_missing_samples_reset_dwell(self):
        self.settings(fence={"lat": 31, "lon": 121, "radius": 500})
        self.upload(lat=31.02)
        self.now += 500; self.upload(lat=31.02)
        self.assertFalse(self.active("outside"))

    def test_uncertain_sample_breaks_continuous_outside_dwell(self):
        self.settings(fence={"lat": 31, "lon": 121, "radius": 500})
        self.upload(lat=31.02)
        self.now += 60; self.upload(lat=31.02, accuracy=500)
        self.now += 61; self.upload(lat=31.02)
        self.assertFalse(self.active("outside"))

    def test_meter_radius_roundtrips_and_invalid_bounds_are_rejected(self):
        for radius in (1, 37, 10000):
            self.settings(fence={"lat":31,"lon":121,"radius":radius})
            self.assertEqual(self.elder()["settings"]["fence"]["radius"], radius)
        for radius in (1, 37, 2000):
            self.settings(trip={"name":"公园","lat":31,"lon":121,"radius":radius,"deadline":self.now+600,"status":"active"})
            self.assertEqual(self.elder()["settings"]["trip"]["radius"], radius)
        for radius in (0, -1, 10001):
            with self.assertRaises(APIError): self.settings(fence={"lat":31,"lon":121,"radius":radius})
        for radius in (0, -1, 2001):
            with self.assertRaises(APIError): self.settings(trip={"name":"公园","lat":31,"lon":121,"radius":radius,"deadline":self.now+600,"status":"active"})

    def test_small_destination_retains_accuracy_margin_and_trip_exemption(self):
        self.settings(fence={"lat":30,"lon":120,"radius":1}, trip={"name":"公园","lat":31,"lon":121,"radius":1,"deadline":self.now+600,"status":"active"})
        self.upload(accuracy=10)
        self.assertEqual(self.elder()["settings"]["trip"]["status"], "active")
        self.assertFalse(self.active("outside"))
        self.now += 61
        self.upload(accuracy=0.5)
        self.assertEqual(self.elder()["settings"]["trip"]["status"], "arrived")
        self.assertFalse(self.active("outside"))

    def test_moving_fence_samples_within_three_minutes_still_confirm_dwell(self):
        self.settings(fence={"lat":31,"lon":121,"radius":500})
        self.upload(lat=31.02)
        self.now += 150; self.upload(lat=31.025)
        self.assertEqual(len(self.active("outside")),1)
        self.assertEqual(self.elder()["fence_status"]["state"],"outside_alert")

    def test_resumed_fence_samples_reach_open_manager_alert_feed(self):
        self.settings(fence={"lat":31,"lon":121,"radius":500})
        self.upload()
        # A sleeping device produces no captures; elapsed wall time alone is not crossing proof.
        self.now += 500
        self.s.tick()
        self.assertFalse(self.active("outside"))
        for offset in (0, 61, 122):
            if offset: self.now += 61
            self.upload(lat=31.02)
        events = self.call("GET", "/alerts")["elders"][0]["events"]
        self.assertEqual(len([e for e in events if e["kind"] == "outside" and e["active"]]), 1)

    def test_alert_feed_is_authorized_and_contains_no_current_telemetry(self):
        self.settings(fence={"lat":31,"lon":121,"radius":500})
        self.upload();self.now += 601;self.s.tick()
        data=self.call("GET","/alerts")
        self.assertEqual(set(data),{"elders"})
        row=data["elders"][0]
        self.assertEqual(set(row),{"id","events"})
        self.assertEqual(row["events"][0]["kind"],"offline")
        self.assertEqual(self.call("GET","/alerts",token=self.stranger)["elders"],[])
        self.invite(False)
        self.assertEqual(len(self.call("GET","/alerts",token=self.other)["elders"]),1)
        uid=self.s.user(self.other)
        self.call("DELETE",f"/elders/{self.eid}/members/{uid}")
        self.assertEqual(self.call("GET","/alerts",token=self.other)["elders"],[])

    def test_fence_status_explains_trip_and_inaccurate_location(self):
        self.settings(fence={"lat":31,"lon":121,"radius":500})
        self.assertEqual(self.elder()["fence_status"]["state"],"waiting_location")
        self.upload(accuracy=500)
        self.assertEqual(self.elder()["fence_status"]["state"],"imprecise")
        self.settings(trip={"name":"公园","lat":32,"lon":121,"radius":200,"deadline":self.now+600,"status":"active"})
        self.assertEqual(self.elder()["fence_status"]["state"],"trip_exempt")
        self.settings(trip=None)
        self.now += 1;self.upload()
        self.assertEqual(self.elder()["fence_status"]["state"],"inside")
        status=self.call("GET","/device/settings",token=self.device)
        self.assertEqual(status["last_recorded_at"],self.now)

    def test_trip_exemption_lasts_until_guardian_ends_it(self):
        self.settings(fence={"lat": 31, "lon": 121, "radius": 500}, trip={"name": "公园", "lat": 31.03, "lon": 121, "radius": 200, "deadline": self.now + 600, "status": "active"})
        for _ in range(4):
            self.now += 50; self.upload(lat=31.02)
        self.assertFalse(self.active("outside"))
        self.now += 50; self.upload(lat=31.03)
        self.assertEqual(self.elder()["settings"]["trip"]["status"], "arrived")
        for _ in range(4):
            self.now += 50; self.upload(lat=31.03)
        self.assertFalse(self.active("outside"))
        self.settings(trip=None)
        for _ in range(4):
            self.now += 50; self.upload(lat=31.03)
        self.assertEqual(len(self.active("outside")), 1)

    def test_overdue_without_any_position_and_no_duplicate(self):
        self.settings(trip={"name": "医院", "lat": 32, "lon": 121, "radius": 200, "deadline": self.now + 120, "status": "active"})
        self.now += 121; self.s.tick(); self.s.tick()
        self.assertEqual(len(self.active("overdue")), 1)

    def test_stale_or_inaccurate_location_cannot_confirm_arrival(self):
        self.settings(trip={"name": "医院", "lat": 32, "lon": 121, "radius": 200, "deadline": self.now + 120, "status": "active"})
        self.upload(lat=32, accuracy=500)
        self.now += 200; self.upload(lat=32, age=150)
        self.s.tick()
        self.assertEqual(self.elder()["settings"]["trip"]["status"], "active")
        self.assertEqual(len(self.active("overdue")), 1)

    def test_on_demand_mode_does_not_raise_stale_position_alarm(self):
        self.now += 86400
        self.s.tick()
        self.assertFalse(self.active("offline"))
        request = self.request_location()
        self.assertEqual(request["state"], "pending")
        self.now += 181
        self.assertEqual(self.elder()["location_request"]["state"], "expired")
        self.assertFalse(self.active("offline"))

    def test_disabling_last_rule_clears_position_alarm(self):
        self.settings(fence={"lat": 31, "lon": 121, "radius": 500})
        self.now += 601
        self.s.tick()
        self.assertTrue(self.active("offline"))
        self.settings(fence=None)
        self.assertFalse(self.active("offline"))

    def test_active_trip_requires_updates_but_arrived_trip_does_not(self):
        self.settings(trip={"name": "公园", "lat": 31, "lon": 121, "radius": 200,
                            "deadline": self.now + 3600, "status": "active"})
        self.now += 601
        self.s.tick()
        self.assertTrue(self.active("offline"))
        self.upload()
        self.assertEqual(self.elder()["settings"]["trip"]["status"], "arrived")
        self.now += 601
        self.s.tick()
        self.assertFalse(self.active("offline"))

    def test_offline_even_without_first_position_and_recovers(self):
        self.settings(fence={"lat": 31, "lon": 121, "radius": 500})
        self.now += 601; self.s.tick()
        self.assertEqual(len(self.active("offline")), 1)
        self.upload()
        self.assertFalse(self.active("offline"))

    def test_replayed_location_cannot_hide_offline(self):
        self.settings(fence={"lat": 31, "lon": 121, "radius": 500})
        self.upload()
        self.now += 700
        self.upload(age=650)
        self.s.tick()
        self.assertEqual(len(self.active("offline")), 1)
        with self.assertRaises(APIError): self.upload(age=700)

    def test_invalid_location_and_future_clock_rejected(self):
        for lat in (91, float("nan"), True):
            with self.assertRaises(APIError): self.upload(lat=lat)
        with self.assertRaises(APIError): self.upload(age=-31)

    def test_event_position_is_snapshot_and_ack_is_shared(self):
        self.settings(fence={"lat": 31, "lon": 121, "radius": 500})
        self.invite()
        self.upload()
        self.now += 601; self.s.tick()
        event = self.active("offline")[0]
        self.call("POST", f"/elders/{self.eid}/events/{event['id']}/ack", {}, self.other)
        self.assertEqual(self.active("offline")[0]["handler"], "son")
        with self.assertRaises(APIError): self.call("POST", f"/elders/{self.eid}/events/{event['id']}/ack")
        self.now += 1; self.upload(lat=32)
        self.assertEqual(self.elder()["events"][0]["location"]["lat"], 31)

    def test_unpair_stops_access_and_allows_new_consent(self):
        self.upload()
        self.call("POST", "/device/unpair", {}, self.device)
        with self.assertRaises(APIError): self.upload()
        self.assertFalse(self.elder()["paired"])
        code = self.call("POST", f"/elders/{self.eid}/pair-code")["code"]
        self.call("POST", "/device/pair", {"code": code, "consent": True}, "")
        self.assertIsNone(self.elder()["location"])

    def test_push_pending_without_credentials_and_revocation_cancels(self):
        self.settings(fence={"lat": 31, "lon": 121, "radius": 500})
        self.invite()
        device = "a" * 64
        self.call("POST", "/push/device", {"token": device}, self.other)
        self.now += 601; self.s.tick()
        self.assertEqual(len(self.s.rows("SELECT * FROM outbox")), 1)
        with patch.dict(os.environ, {}, clear=True): PushWorker(self.s).run_once()
        self.assertEqual(self.s.one("SELECT state FROM outbox")["state"], "pending")
        self.call("DELETE", f"/elders/{self.eid}/members/{self.s.user(self.other)}")
        env = dict(APNS_KEY_PATH="unused", APNS_KEY_ID="key", APNS_TEAM_ID="team", APNS_TOPIC="topic")
        with patch.dict(os.environ, env), patch.object(PushWorker, "send") as sender:
            PushWorker(self.s).run_once(); sender.assert_not_called()
        self.assertEqual(self.s.one("SELECT state FROM outbox")["state"], "cancelled")

    def test_push_acceptance_and_retry_are_not_device_delivery(self):
        self.settings(fence={"lat": 31, "lon": 121, "radius": 500})
        self.call("POST", "/push/device", {"token": "a" * 64})
        self.now += 601; self.s.tick()
        env = dict(APNS_KEY_PATH="unused", APNS_KEY_ID="key", APNS_TEAM_ID="team", APNS_TOPIC="topic")
        with patch.dict(os.environ, env), patch.object(PushWorker, "send", return_value=(503, "unavailable")):
            PushWorker(self.s).run_once()
        row = self.s.one("SELECT * FROM outbox")
        self.assertEqual(row["state"], "pending"); self.assertEqual(row["attempts"], 1)
        self.now += 31
        with patch.dict(os.environ, env), patch.object(PushWorker, "send", return_value=(200, "")):
            PushWorker(self.s).run_once()
        self.assertEqual(self.s.one("SELECT state FROM outbox")["state"], "accepted")

    def test_push_registered_after_alarm_receives_pending_event(self):
        self.settings(fence={"lat": 31, "lon": 121, "radius": 500})
        self.now += 601; self.s.tick()
        self.call("POST", "/push/device", {"token": "a" * 64})
        self.assertEqual(len(self.s.rows("SELECT * FROM outbox")), 1)

    def test_login_and_logout_invalidates_session(self):
        with self.assertRaises(APIError): self.s.dispatch("POST", "/auth/login", {"name": "daughter", "password": "wrong password 123"})
        session = self.s.dispatch("POST", "/auth/login", {"name": "daughter", "password": "a test password 123"})["token"]
        self.assertTrue(self.call("GET", "/elders", token=session)["elders"])
        self.call("POST", "/auth/logout", token=session)
        with self.assertRaises(APIError): self.call("GET", "/elders", token=session)

    def test_distance_uses_meters(self):
        self.assertAlmostEqual(distance({"lat": 0, "lon": 0}, {"lat": 0, "lon": 1}), 111194.9, delta=1)


if __name__ == "__main__":
    unittest.main()
