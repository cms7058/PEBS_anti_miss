"""Cloud HTTP entry point. Gunicorn serves requests; one locked scheduler owns monitoring."""
import atexit
import fcntl
import ipaddress
import json
import os
import threading
import time
from http import HTTPStatus
from pathlib import Path

from backend.elder_push import run_command_push
from backend.server import APIError, PushWorker, Store, require


class Application:
    def __init__(self, store=None, start_monitor=True, trust_proxy=None):
        self.database_path = os.getenv("DATABASE_PATH", "family.sqlite3")
        self.store = store if store is not None else Store(self.database_path)
        self.trust_proxy = os.getenv("TRUST_PROXY", os.getenv("TRUST_LOCAL_PROXY", "0")) == "1" if trust_proxy is None else trust_proxy
        self.trusted_proxies = tuple(ipaddress.ip_network(value.strip()) for value in
            os.getenv("TRUST_PROXY_NETWORKS", "127.0.0.1/32,::1/128").split(",") if value.strip())
        self.attempts = {}
        self.rate_lock = threading.Lock()
        self.stopped = threading.Event()
        self.monitor = None
        if start_monitor:
            self.monitor = threading.Thread(target=self.run_monitor, daemon=True)
            self.monitor.start()
            atexit.register(self.stop)

    def stop(self):
        self.stopped.set()
        self.store.command_ready.set()
        self.store.close_command_streams()
        if self.monitor:
            self.monitor.join(timeout=2)

    def run_monitor(self):
        # A file lock prevents two schedulers from sending the same queued notification
        # during a worker restart. Do not delete a live lock file.
        lock_path = str(Path(self.database_path).resolve()) + ".monitor.lock"
        with open(lock_path, "a") as lock:
            while not self.stopped.is_set():
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    self.stopped.wait(1)
            else:
                return
            try:
                push = PushWorker(self.store)
                command_worker = threading.Thread(target=run_command_push, args=(self.store, self.stopped), daemon=True)
                command_worker.start()
                while not self.stopped.is_set():
                    try:
                        self.store.tick()
                        push.run_once()
                    except Exception as exc:
                        print("Monitor error:", type(exc).__name__, flush=True)
                    self.stopped.wait(15)
            finally:
                # Keep scheduler ownership until any in-flight Getui call has exited.
                if 'command_worker' in locals():
                    command_worker.join()
                fcntl.flock(lock, fcntl.LOCK_UN)

    def client_ip(self, environ):
        peer = environ.get("REMOTE_ADDR", "unknown")
        # Caddy explicitly overwrites X-Real-IP; accept it only from its configured address.
        try:
            address = ipaddress.ip_address(peer)
            if self.trust_proxy and any(address in network for network in self.trusted_proxies):
                forwarded = environ.get("HTTP_X_REAL_IP", "")
                return str(ipaddress.ip_address(forwarded))
        except ValueError:
            pass
        return peer

    def rate_limit(self, ip, path):
        if not (path.startswith("/auth/") or path in ("/device/pair", "/invites/accept")):
            return
        now = time.monotonic()
        key = (ip, path)
        with self.rate_lock:
            self.attempts = {k: v for k, v in self.attempts.items() if now - v[0] < 60}
            require(key in self.attempts or len(self.attempts) < 10000, "请求过于频繁，请稍后重试", 429)
            start, count = self.attempts.get(key, (now, 0))
            require(count < 20, "请求过于频繁，请稍后重试", 429)
            self.attempts[key] = (start, count + 1)

    def __call__(self, environ, start_response):
        try:
            path = environ.get("PATH_INFO", "/")
            method = environ.get("REQUEST_METHOD", "GET")
            self.rate_limit(self.client_ip(environ), path)
            length = int(environ.get("CONTENT_LENGTH") or 0)
            require(0 <= length <= 65536, "请求内容过大", 413)
            if length:
                raw = environ["wsgi.input"].read(length)
                require(len(raw) == length, "请求内容不完整")
                data = json.loads(raw)
            else:
                data = {}
            require(isinstance(data, dict), "请求必须是 JSON 对象")
            token = environ.get("HTTP_AUTHORIZATION", "").removeprefix("Bearer ")
            if method == "GET" and path == "/device/events":
                stream = self.store.open_command_stream(token)
                try:
                    start_response("200 OK", [("Content-Type", "text/event-stream; charset=utf-8"), ("Cache-Control", "no-store"), ("X-Accel-Buffering", "no")])
                except BaseException:
                    stream.close()
                    raise
                return stream
            result = self.store.dispatch(method, path, data, token)
            status = 200
        except APIError as exc:
            status, result = exc.status, {"error": exc.message}
        except (ValueError, TypeError, UnicodeDecodeError):
            status, result = 400, {"error": "请求格式错误"}
        except Exception as exc:
            print("Request error:", type(exc).__name__, flush=True)
            status, result = 500, {"error": "服务暂时不可用"}
        payload = json.dumps(result, ensure_ascii=False, allow_nan=False).encode()
        start_response(f"{status} {HTTPStatus(status).phrase}", [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(payload))),
            ("Cache-Control", "no-store"),
        ])
        return [payload]


def create_app():
    os.umask(0o077)
    return Application()
