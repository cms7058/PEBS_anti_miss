import io
import json
import threading
import unittest
from backend.server import Store, APIError
from backend.wsgi import Application
from wsgiref.util import setup_testing_defaults
from wsgiref.validate import validator


class CommandStreamTests(unittest.TestCase):
    def setUp(self):
        self.s = Store(':memory:')
        self.owner = self.s.dispatch('POST', '/auth/register', {'name': 'test', 'password': 'test-password-123'})['token']
        self.eid, self.device = self.pair()

    def tearDown(self):
        self.s.close_command_streams()
        self.s.db.close()

    def pair(self):
        elder = self.s.dispatch('POST', '/elders', {'name': 'test'}, self.owner)
        device = self.s.dispatch('POST', '/device/pair', {'code': elder['code'], 'consent': True})['token']
        return elder['id'], device

    def test_authenticated_event_wakes_without_getui_and_requires_command_fetch(self):
        for token in ('', self.owner, 'invalid'):
            with self.assertRaises(APIError): self.s.open_command_stream(token)
        stream = self.s.open_command_stream(self.device)
        self.assertTrue(self.s.dispatch('GET', f'/elders/{self.eid}', {}, self.owner)['elder_push']['command_stream_registered'])
        self.assertIn(b'sync_commands', next(stream))
        result, finished = [], threading.Event()
        def read():
            result.append(next(stream))
            finished.set()
        thread = threading.Thread(target=read)
        thread.start()
        try:
            self.assertFalse(finished.wait(.05))
            request = self.s.dispatch('POST', f'/elders/{self.eid}/location-request', {}, self.owner)
            self.assertTrue(finished.wait(1))
            self.assertEqual(result, [b'event: command\ndata: sync_commands\n\n'])
            self.assertEqual(self.s.location_request(self.eid)['state'], 'pending')
            commands = self.s.dispatch('GET', '/device/commands', {}, self.device)
            self.assertEqual(commands['location_request']['id'], request['id'])
            self.assertEqual(self.s.location_request(self.eid)['state'], 'received')
            # A new capture can satisfy this request without any Getui sender running.
            self.s.dispatch('POST', '/device/location', {'lat': 31, 'lon': 121, 'accuracy': 25,
                'battery': 70, 'recorded_at': self.s.clock(), 'applied_version': 0, 'request_id': request['id']}, self.device)
            self.assertEqual(self.s.location_request(self.eid)['state'], 'completed')
        finally:
            stream.close()
            thread.join(1)

    def test_reconnect_replaces_old_connection_and_close_before_iteration_releases_slot(self):
        first = self.s.open_command_stream(self.device)
        second = self.s.open_command_stream(self.device)
        with self.assertRaises(StopIteration): next(first)
        first.close()
        self.assertIs(self.s.command_streams[self.eid], second)
        second.close()
        self.assertFalse(self.s.command_streams)

    def test_stream_capacity_reserves_http_threads(self):
        streams = [self.s.open_command_stream(self.device)]
        for _ in range(3):
            _, device = self.pair()
            streams.append(self.s.open_command_stream(device))
        _, extra = self.pair()
        with self.assertRaises(APIError) as error: self.s.open_command_stream(extra)
        self.assertEqual(error.exception.status, 503)
        streams[0].close()
        self.s.open_command_stream(extra).close()

    def test_unpair_revokes_stream_and_never_emits_other_device_commands(self):
        stream = self.s.open_command_stream(self.device)
        next(stream)
        stream.HEARTBEAT = .01
        other, _ = self.pair()
        self.s.dispatch('POST', f'/elders/{other}/location-request', {}, self.owner)
        self.assertEqual(next(stream), b': keepalive\n\n')
        self.s.dispatch('POST', '/device/unpair', {}, self.device)
        with self.assertRaises(StopIteration): next(stream)

    def test_wsgi_stream_obeys_iterator_close_contract_and_has_no_payload_credentials(self):
        app = validator(Application(self.s, start_monitor=False))
        env = {}; setup_testing_defaults(env)
        env.update(PATH_INFO='/device/events', QUERY_STRING='', HTTP_AUTHORIZATION='Bearer ' + self.device,
                   CONTENT_LENGTH='0', **{'wsgi.input': io.BytesIO(b'')})
        response = []
        stream = app(env, lambda status, headers: response.append((status, dict(headers))))
        try:
            payload = next(stream)
            self.assertEqual(response[0][0], '200 OK')
            self.assertIn('text/event-stream', response[0][1]['Content-Type'])
            self.assertNotIn(self.device.encode(), payload)
            self.assertNotIn(b'lat', payload)
        finally: stream.close()
        self.assertFalse(self.s.command_streams)
