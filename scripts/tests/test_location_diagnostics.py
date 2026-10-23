import json
import io
import os
from unittest.mock import patch, MagicMock
from pathlib import Path
import tempfile
import unittest
from backend.server import Store
from scripts.diagnose_location import diagnose, query_push_states


class LocationDiagnosticsTests(unittest.TestCase):
    def test_read_only_redacted_report_distinguishes_fetch_and_upload(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / "test.sqlite3"
            now = 1800000000.0
            store = Store(str(database), lambda: now)
            owner = store.dispatch("POST", "/auth/register", {"name":"PRIVATE_NAME", "password":"PRIVATE_PASSWORD_123"})["token"]
            elder = store.dispatch("POST", "/elders", {"name":"PRIVATE_ELDER"}, owner)
            device = store.dispatch("POST", "/device/pair", {"code":elder["code"], "consent":True})["token"]
            eid = elder["id"]
            store.dispatch("POST", f"/elders/{eid}/location-request", {}, owner)
            initial = diagnose(database, Path(__file__).resolve().parents[2], now)
            self.assertFalse(initial["devices"][0]["request"]["command_fetch_recorded"])
            expired_view = diagnose(database, Path(__file__).resolve().parents[2], now + 200)
            self.assertLess(expired_view["devices"][0]["request"]["remaining_seconds"], 0)
            self.assertEqual(store.one("SELECT state FROM location_requests")["state"], "pending")
            store.dispatch("GET", "/device/commands", {}, device)
            store.dispatch("POST", "/device/location", {"lat":31.1234567,"lon":121.9876543,"accuracy":20,"battery":87,"recorded_at":now,"applied_version":0}, device)
            with store.db:
                store.db.execute("INSERT INTO elder_device_state VALUES(?,?,?)", (eid, json.dumps({"battery_unrestricted": False, "service_running": True,
                    "command_stream_connected": False, "extra": "DEVICE_STATE_PRIVATE", "lat": 31.1234567}), now))
            before = store.db.total_changes
            result = diagnose(database, Path(__file__).resolve().parents[2], now + 200)
            self.assertEqual(store.db.total_changes, before)
            self.assertEqual(result["devices"][0]["request"]["state"], "completed")
            self.assertTrue(result["devices"][0]["request"]["post_request_capture_present"])
            self.assertEqual(result["devices"][0]["phone_state_at_last_report"], {"battery_unrestricted": False, "service_running": True, "command_stream_connected": False})
            self.assertEqual(result["devices"][0]["phone_state_age_seconds"], 200)
            raw = json.dumps(result)
            for secret in ("PRIVATE_NAME", "PRIVATE_PASSWORD_123", "PRIVATE_ELDER", "DEVICE_STATE_PRIVATE", owner, device, eid, elder["code"], "31.1234567", "121.9876543", '"battery"'):
                self.assertNotIn(secret, raw)
            cid = "CID_PRIVATE_1234567890"
            app_id = "APP_ID_1234567890"
            with store.db:
                store.db.execute("INSERT INTO elder_push_devices VALUES(?,?,?)", (eid,cid,app_id))
            with patch.dict(os.environ, {"GETUI_APP_ID":app_id,"GETUI_APP_KEY":"KEY_PRIVATE","GETUI_MASTER_SECRET":"SECRET_PRIVATE"}):
                with patch("scripts.diagnose_location.query_push_states", return_value=({"succeeded":True,"api_code":0},{cid:"offline"})) as query:
                    result = diagnose(database, Path(__file__).resolve().parents[2], now, live_push=True)
                query.assert_called_once_with([cid])
                self.assertEqual(result["devices"][0]["getui_status_now"], "offline")
                self.assertTrue(result["getui_live_query"]["succeeded"])
                for secret in (cid, "KEY_PRIVATE", "SECRET_PRIVATE"):
                    self.assertNotIn(secret, json.dumps(result))
                with patch("scripts.diagnose_location.query_push_states", side_effect=RuntimeError("SECRET_PRIVATE")):
                    failed = diagnose(database, Path(__file__).resolve().parents[2], now, live_push=True)
                self.assertFalse(failed["getui_live_query"]["succeeded"])
                self.assertEqual(failed["devices"][0]["getui_status_now"], "unknown")
                self.assertNotIn("SECRET_PRIVATE", json.dumps(failed))
            store.db.close()

    def test_live_api_uses_status_get_and_reauthenticates_without_sending_push(self):
        cid = "CID_PRIVATE_1234567890"
        client = MagicMock(token="TOKEN_PRIVATE")
        replies = [io.BytesIO(json.dumps({"code":10001}).encode()),
                   io.BytesIO(json.dumps({"code":0,"data":{cid:{"status":"online","extra":"DO_NOT_RETURN"}}}).encode())]
        with patch.dict(os.environ, {"GETUI_APP_ID":"APP_ID_1234567890"}), patch("backend.elder_push.GetuiClient",return_value=client), patch("urllib.request.urlopen",side_effect=replies) as opened:
            result, states = query_push_states([cid])
        self.assertEqual(client.authenticate.call_count,2)
        client.send.assert_not_called()
        self.assertEqual(states,{cid:"online"})
        self.assertNotIn("DO_NOT_RETURN",json.dumps(result))
        self.assertNotIn("TOKEN_PRIVATE",json.dumps(result))
        self.assertTrue(all(call.args[0].get_method()=="GET" for call in opened.call_args_list))

    def test_missing_database_is_not_created(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / "missing.sqlite3"
            with self.assertRaises(sqlite3.OperationalError): diagnose(database, folder)
            self.assertFalse(database.exists())


if __name__ == "__main__":
    unittest.main()
