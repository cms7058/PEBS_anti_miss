import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from wsgiref.util import setup_testing_defaults
from wsgiref.validate import validator

from backend.server import Store
from backend.wsgi import Application
from deploy.backup import backup


class CloudEntryTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.app = Application(self.store, start_monitor=False, trust_proxy=True)

    def tearDown(self):
        self.store.db.close()

    def call(self, path, data=None, token="", method=None, check_wsgi=True, **overrides):
        environ = {}
        setup_testing_defaults(environ)
        raw = json.dumps(data).encode() if data is not None else b""
        environ.update(PATH_INFO=path, REQUEST_METHOD=method or ("POST" if data is not None else "GET"),
                       CONTENT_LENGTH=str(len(raw)), CONTENT_TYPE="application/json", QUERY_STRING="",
                       REMOTE_ADDR="127.0.0.1", HTTP_X_REAL_IP="203.0.113.20",
                       HTTP_AUTHORIZATION="Bearer " + token)
        environ["wsgi.input"] = io.BytesIO(raw)
        environ.update(overrides)
        response = []
        def start_response(status, headers, exc_info=None):
            response.append((int(status.split()[0]), dict(headers)))
        application = validator(self.app) if check_wsgi else self.app
        iterable = application(environ, start_response)
        try:
            payload = b"".join(iterable)
        finally:
            if hasattr(iterable, "close"): iterable.close()
        status, headers = response[0]
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(int(headers["Content-Length"]), len(payload))
        return status, json.loads(payload)

    def test_mobile_contract_over_cloud_entry(self):
        self.assertEqual(self.call("/health")[0], 200)
        self.assertEqual(self.call("/elders")[0], 401)
        status, session = self.call("/auth/register", {"name": "cloud-family", "password": "cloud-test-password"})
        self.assertEqual(status, 200)
        status, elder = self.call("/elders", {"name": "测试家人"}, session["token"])
        self.assertEqual(status, 200)
        status, paired = self.call("/device/pair", {"code": elder["code"], "consent": True})
        self.assertEqual(status, 200)
        self.assertIn("token", paired)
        status, result = self.call("/elders", token=session["token"])
        self.assertEqual(status, 200)
        self.assertTrue(result["elders"][0]["paired"])

    def test_body_size_and_json_validation(self):
        self.assertEqual(self.call("/auth/register", {}, CONTENT_LENGTH="65537")[0], 413)
        self.assertEqual(self.call("/auth/register", {}, CONTENT_LENGTH="-1", check_wsgi=False)[0], 413)
        self.assertEqual(self.call("/auth/register", {}, CONTENT_LENGTH="wrong", check_wsgi=False)[0], 400)
        self.assertEqual(self.call("/auth/register", ["bad"])[0], 400)
        self.assertEqual(self.call("/auth/register", {}, CONTENT_LENGTH="10")[0], 400)

    def test_proxy_cannot_be_forged_by_non_proxy_peer(self):
        self.assertEqual(self.app.client_ip({"REMOTE_ADDR": "203.0.113.5", "HTTP_X_REAL_IP": "203.0.113.6"}), "203.0.113.5")
        self.assertEqual(self.app.client_ip({"REMOTE_ADDR": "127.0.0.1", "HTTP_X_REAL_IP": "203.0.113.6"}), "203.0.113.6")
        self.assertEqual(self.app.client_ip({"REMOTE_ADDR": "127.0.0.1", "HTTP_X_REAL_IP": "bad, ip"}), "127.0.0.1")

    def test_container_proxy_address_is_explicit(self):
        with patch.dict(os.environ, {"TRUST_PROXY_NETWORKS": "172.30.87.2/32"}):
            app = Application(self.store, start_monitor=False, trust_proxy=True)
        self.assertEqual(app.client_ip({"REMOTE_ADDR": "172.30.87.2", "HTTP_X_REAL_IP": "203.0.113.8"}), "203.0.113.8")
        self.assertEqual(app.client_ip({"REMOTE_ADDR": "172.30.87.3", "HTTP_X_REAL_IP": "203.0.113.8"}), "172.30.87.3")

    def test_rate_limit_is_per_real_client(self):
        for _ in range(21):
            status, _ = self.call("/auth/login", {})
        self.assertEqual(status, 429)
        self.assertEqual(self.call("/auth/login", {}, HTTP_X_REAL_IP="203.0.113.21")[0], 400)

    def test_online_backup_includes_live_wal_and_is_private(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "live.sqlite3"
            live = sqlite3.connect(path)
            try:
                live.execute("PRAGMA journal_mode=WAL")
                live.execute("CREATE TABLE readings(id INTEGER)")
                live.execute("INSERT INTO readings VALUES(42)")
                live.commit()
                result = backup(path, Path(folder) / "backups")
                with sqlite3.connect(result) as copy:
                    self.assertEqual(copy.execute("SELECT id FROM readings").fetchone()[0], 42)
                self.assertEqual(result.stat().st_mode & 0o777, 0o600)
            finally:
                live.close()

    def test_scheduler_file_lock_allows_only_one_monitor(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"DATABASE_PATH": folder + "/state.sqlite3"}), patch("backend.wsgi.PushWorker.run_once"), patch("backend.wsgi.ElderPushWorker.run_once"):
            first_store, second_store = Mock(), Mock()
            first_tick, second_tick = threading.Event(), threading.Event()
            first_store.tick.side_effect = first_tick.set
            second_store.tick.side_effect = second_tick.set
            first = Application(first_store)
            second = None
            try:
                self.assertTrue(first_tick.wait(2))
                second = Application(second_store)
                self.assertFalse(second_tick.wait(0.15))
                first.stop()
                self.assertTrue(second_tick.wait(2))
            finally:
                first.stop()
                if second: second.stop()


if __name__ == "__main__":
    unittest.main()
