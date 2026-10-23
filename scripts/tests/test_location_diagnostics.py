import json
from pathlib import Path
import tempfile
import unittest
from backend.server import Store
from scripts.diagnose_location import diagnose


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
            before = store.db.total_changes
            result = diagnose(database, Path(__file__).resolve().parents[2], now + 200)
            self.assertEqual(store.db.total_changes, before)
            self.assertEqual(result["devices"][0]["request"]["state"], "completed")
            self.assertTrue(result["devices"][0]["request"]["post_request_capture_present"])
            raw = json.dumps(result)
            for secret in ("PRIVATE_NAME", "PRIVATE_PASSWORD_123", "PRIVATE_ELDER", owner, device, eid, elder["code"], "31.1234567", "121.9876543", '"battery"'):
                self.assertNotIn(secret, raw)
            store.db.close()

    def test_missing_database_is_not_created(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / "missing.sqlite3"
            with self.assertRaises(sqlite3.OperationalError): diagnose(database, folder)
            self.assertFalse(database.exists())


if __name__ == "__main__":
    unittest.main()
