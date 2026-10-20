"""Real HTTP boundary smoke tests. Uses an ephemeral loopback port and in-memory database."""
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from backend.server import Handler, Store


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = Store(":memory:")
        cls.handler = type("TestHandler", (Handler,), {"store": cls.store, "attempts": {}})
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), cls.handler)
        cls.base = "http://127.0.0.1:" + str(cls.server.server_port)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(); cls.store.db.close()

    def request(self, path, body=None, token="", method=None):
        data = json.dumps(body).encode() if body is not None else None
        req = Request(self.base + path, data=data, method=method, headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
        try:
            with urlopen(req, timeout=3) as response:
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def test_health_and_authentication(self):
        status, body = self.request("/health")
        self.assertEqual(status, 200); self.assertTrue(body["ok"])
        self.assertEqual(self.request("/elders")[0], 401)
        status, auth = self.request("/auth/register", {"name": "http-user", "password": "long password 1234"})
        self.assertEqual(status, 200)
        status, elder = self.request("/elders", {"name": "妈妈"}, auth["token"])
        self.assertEqual(status, 200)
        status, pair = self.request("/device/pair", {"code": elder["code"], "consent": True})
        self.assertEqual(status, 200); self.assertIn("token", pair)
        status, elders = self.request("/elders", token=auth["token"])
        self.assertEqual(status, 200); self.assertEqual(elders["elders"][0]["name"], "妈妈")

    def test_invalid_json_shape(self):
        status, body = self.request("/auth/register", ["bad"])
        self.assertEqual(status, 400); self.assertIn("error", body)

    def test_http_rate_limit(self):
        for _ in range(21):
            status, _ = self.request("/auth/login", {"name": "unknown", "password": "some password 123"})
        self.assertEqual(status, 429)


if __name__ == "__main__": unittest.main()
