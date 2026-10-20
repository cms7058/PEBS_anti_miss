import os

bind = os.getenv("HOST", "127.0.0.1") + ":" + os.getenv("PORT", "8087")
# SQLite, in-memory rate limits and the monitor are designed for one worker.
workers = 1
worker_class = "gthread"
threads = 8
preload_app = False
timeout = 45
graceful_timeout = 30
keepalive = 2
limit_request_line = 4094
limit_request_fields = 50
limit_request_field_size = 4094
forwarded_allow_ips = "127.0.0.1,::1"
accesslog = None
errorlog = "-"
capture_output = True
