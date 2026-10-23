"""Authenticated, bounded-capacity server events. Events contain only a sync hint."""
import time


class CommandStream:
    HEARTBEAT = 60

    def __init__(self, store, elder_id, token_digest):
        self.store, self.elder_id, self.token_digest = store, elder_id, token_digest
        self.closed = False
        self.first = True
        self.version = store.command_versions.get(elder_id, 0)

    def __iter__(self):
        return self

    def __next__(self):
        s = self.store
        deadline = time.monotonic() + self.HEARTBEAT
        with s.command_condition:
            while True:
                if self.closed or s.command_streams.get(self.elder_id) is not self:
                    self.close()
                    raise StopIteration
                device = s.one("SELECT id FROM elders WHERE id=? AND device_token=? AND consent=1", (self.elder_id, self.token_digest))
                if not device:
                    self.close()
                    raise StopIteration
                version = s.command_versions.get(self.elder_id, 0)
                if self.first or version != self.version:
                    self.first, self.version = False, version
                    return b'event: command\ndata: sync_commands\n\n'
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return b': keepalive\n\n'
                s.command_condition.wait(remaining)

    def close(self):
        s = self.store
        with s.command_condition:
            self.closed = True
            if s.command_streams.get(self.elder_id) is self:
                del s.command_streams[self.elder_id]
            s.command_condition.notify_all()
