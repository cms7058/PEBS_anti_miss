import copy
import unittest
from backend.server import Store, APIError


class RemoteSettingsTests(unittest.TestCase):
    def setUp(self):
        self.now = 1800000000.
        self.s = Store(':memory:', lambda: self.now)
        self.owner = self.s.dispatch('POST', '/auth/register', {'name': 'owner', 'password': 'test-password-123'})['token']
        self.viewer = self.s.dispatch('POST', '/auth/register', {'name': 'viewer', 'password': 'test-password-123'})['token']
        elder = self.call('POST', '/elders', {'name': 'test'})
        self.eid = elder['id']
        self.device = self.s.dispatch('POST', '/device/pair', {'code': elder['code'], 'consent': True})['token']
        self.s.db.execute('INSERT INTO members VALUES(?,?,0)', (self.eid, self.s.user(self.viewer)))
        self.s.db.commit()

    def tearDown(self):
        self.s.db.close()

    def call(self, method, path, data=None, token=None):
        return self.s.dispatch(method, path, data or {}, token or self.owner)

    def snapshot(self):
        return self.call('GET', '/elders/' + self.eid)

    def payload(self):
        return dict(precise_location=True, background_location=False, battery_unrestricted=False,
                    notifications=True, location_enabled=True, network_location=True,
                    guard_enabled=True, service_running=True, settings_version=self.snapshot()['version'], automatic_interval=60)

    def reminder(self, action='battery', token=None):
        return self.call('POST', '/elders/' + self.eid + '/setup-request', {'action': action}, token)

    def test_interval_preserved_for_old_clients_and_conflicts_rejected(self):
        before = self.snapshot()
        settings = copy.deepcopy(before['settings'])
        settings['automatic_interval'] = 120
        after = self.call('PUT', '/elders/' + self.eid + '/settings', {'version': before['version'], 'settings': settings})
        self.assertEqual(after['settings']['automatic_interval'], 120)
        settings.pop('automatic_interval')  # Old clients do not know this optional field.
        newer = self.call('PUT', '/elders/' + self.eid + '/settings', {'version': after['version'], 'settings': settings})
        self.assertEqual(newer['settings']['automatic_interval'], 120)
        self.assertEqual(newer['applied_version'], 0)
        for interval in [True, 29, 121, 30.5]:
            invalid = dict(newer['settings'], automatic_interval=interval)
            with self.assertRaises(APIError):
                self.call('PUT', '/elders/' + self.eid + '/settings', {'version': newer['version'], 'settings': invalid})
        with self.assertRaises(APIError) as error:
            self.call('PUT', '/elders/' + self.eid + '/settings', {'version': before['version'], 'settings': settings})
        self.assertEqual(error.exception.status, 409)

    def test_state_requires_bound_device_and_reports_without_location(self):
        self.assertIsNone(self.snapshot()['device_state'])
        payload = self.payload()
        with self.assertRaises(APIError):
            self.call('POST', '/device/state', payload)
        self.call('POST', '/device/state', payload, self.device)
        snapshot = self.snapshot()
        self.assertFalse(snapshot['device_state']['battery_unrestricted'])
        self.assertIsNone(snapshot['location'])
        self.assertEqual(snapshot['device_state']['updated_at'], self.now)
        with self.assertRaises(APIError):
            self.call('POST', '/device/state', dict(payload, battery_unrestricted='yes'), self.device)

    def test_reminders_require_edit_authority_and_do_not_repeat_push(self):
        with self.assertRaises(APIError) as error:
            self.reminder(token=self.viewer)
        self.assertEqual(error.exception.status, 403)
        first = self.reminder()
        self.assertEqual(first['id'], self.reminder()['id'])
        self.assertEqual(len(self.s.rows("SELECT * FROM elder_outbox WHERE kind='setup'")), 1)
        with self.assertRaises(APIError): self.reminder('location')
        with self.assertRaises(APIError): self.reminder('grant_permissions_silently')
        self.now += 31
        self.assertNotEqual(first['id'], self.reminder('location')['id'])

    def test_reminder_receipt_and_open_are_not_permission_grants(self):
        request = self.reminder()
        commands = self.call('GET', '/device/commands', token=self.device)
        self.assertEqual(commands['setup_request']['id'], request['id'])
        self.assertEqual(self.snapshot()['setup_request']['state'], 'pending')
        payload = self.payload()
        for state in ('received', 'notified', 'opened'):
            self.call('POST', '/device/state', dict(payload, setup_request_id=request['id'], setup_state=state), self.device)
            snapshot = self.snapshot()
            self.assertEqual(snapshot['setup_request']['state'], state)
            self.assertFalse(snapshot['device_state']['battery_unrestricted'])
        self.assertIsNone(self.call('GET', '/device/commands', token=self.device)['setup_request'])
        # A late 'received' report must not revert an already opened reminder.
        self.call('POST', '/device/state', dict(payload, setup_request_id=request['id'], setup_state='received'), self.device)
        self.assertEqual(self.snapshot()['setup_request']['state'], 'opened')

    def test_expiry_unknown_ack_and_unpair_cleanup(self):
        request = self.reminder()
        payload = self.payload()
        with self.assertRaises(APIError):
            self.call('POST', '/device/state', dict(payload, setup_request_id='other', setup_state='opened'), self.device)
        self.assertIsNone(self.snapshot()['device_state'])  # Whole invalid write rolls back.
        self.now += 3601
        self.assertIsNone(self.call('GET', '/device/commands', token=self.device)['setup_request'])
        self.assertEqual(self.snapshot()['setup_request']['state'], 'expired')
        self.call('POST', '/device/state', payload, self.device)
        self.call('POST', '/device/unpair', token=self.device)
        self.assertIsNone(self.snapshot()['device_state'])
        self.assertIsNone(self.snapshot()['setup_request'])
